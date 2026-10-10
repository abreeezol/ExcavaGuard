# -*- coding: utf-8 -*-
"""
report_core.py — Core logic for spec compliance checking and daily-report generation
(offline, portable).

Pipeline (mirrors the interactive test flow requested by the user):
  1. Parse the tester's field-monitoring description into structured items
     (point / item / cumulative value / rate).
  2. For each item, retrieve matching spec clauses from the RAG knowledge base
     (used as the cited basis for the check).
  3. Check each item against the alarm-value rule table (derived from
     GB 50497-2019; overridable via config/alarm_rules.json):
     OK (<70%) / Watch (70%-100%) / Alarm (>=100%).
  4. Generate a daily report (Markdown) following the project's
     "Monitoring Daily Report Compilation Rules" template.

Note: comments and docstrings are in English to avoid encoding issues on
machines with non-UTF-8 locales; user-facing report text stays in Chinese
because the deliverable itself is a Chinese report.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "data" / "chroma_db"
MODEL_DIR = ROOT / "models" / "bge-small-zh"
MODEL_NAME = "BAAI/bge-small-zh"
COLLECTION = "jikeng_norms"

# ------------------------------------------------------------ Alarm-value rule table
# Derived from GB 50497-2019 clauses 8.0.x (safety level 1 / 2 excavations).
# The retrieved clause text prevails as citation; this table drives the
# structured judgement. Override via config/alarm_rules.json.
DEFAULT_ALARM_RULES = {
    "沉降":            {"level1": {"cum": (20, 25), "rate": (2, 3)}, "level2": {"cum": (30, 40), "rate": (3, 5)}, "unit": "mm"},
    "支护顶部沉降":      {"level1": {"cum": (20, 25), "rate": (2, 3)}, "level2": {"cum": (30, 40), "rate": (3, 5)}, "unit": "mm"},
    "周边地表沉降":      {"level1": {"cum": (25, 30), "rate": (2, 3)}, "level2": {"cum": (35, 45), "rate": (3, 5)}, "unit": "mm"},
    "建筑物沉降":        {"level1": {"cum": (10, 20), "rate": (1, 2)}, "level2": {"cum": (10, 20), "rate": (1, 2)}, "unit": "mm"},
    "水平位移":          {"level1": {"cum": (25, 30), "rate": (2, 3)}, "level2": {"cum": (40, 50), "rate": (4, 6)}, "unit": "mm"},
    "支护顶部水平位移":   {"level1": {"cum": (25, 30), "rate": (2, 3)}, "level2": {"cum": (40, 50), "rate": (4, 6)}, "unit": "mm"},
    "深层水平位移":      {"level1": {"cum": (30, 40), "rate": (2, 3)}, "level2": {"cum": (50, 60), "rate": (4, 6)}, "unit": "mm"},
    "地下水位":          {"level1": {"cum": (1000, 1000), "rate": (500, 500)}, "level2": {"cum": (1000, 1000), "rate": (500, 500)}, "unit": "mm"},
    "支撑轴力":          {"level1": {"cum_pct": 80, "rate": None}, "level2": {"cum_pct": 80, "rate": None}, "unit": "kN"},
    "锚杆拉力":          {"level1": {"cum_pct": 80, "rate": None}, "level2": {"cum_pct": 80, "rate": None}, "unit": "kN"},
}

# Canonical item name -> keyword aliases found in free-text descriptions
ITEM_KEYWORDS = {
    "深层水平位移": ["深层水平位移", "测斜"],
    "支护顶部水平位移": ["顶部水平位移", "桩顶水平位移", "墙顶水平位移", "坡顶水平位移"],
    "水平位移": ["水平位移"],
    "支护顶部沉降": ["顶部沉降", "桩顶沉降", "墙顶沉降", "坡顶沉降", "顶部竖向位移"],
    "周边地表沉降": ["地表沉降", "地表竖向位移", "地面沉降"],
    "建筑物沉降": ["建筑物沉降", "房屋沉降", "建筑沉降"],
    "沉降": ["沉降", "竖向位移"],
    "地下水位": ["水位", "地下水位"],
    "支撑轴力": ["轴力", "支撑轴力", "支撑内力"],
    "锚杆拉力": ["锚杆拉力", "锚索拉力", "锚杆锚力", "拉力"],
}

# ------------------------------------------------------------ Data structures
@dataclass
class MeasureItem:
    point: str = ""            # monitoring point id / description
    item: str = ""             # canonical monitoring item name
    raw_item: str = ""         # keyword as it appeared in the source text
    cumulative: float | None = None   # cumulative value (mm; % for axial force)
    rate: float | None = None         # change rate (mm/d)
    value: float | None = None        # current reading (water level m / force kN ...)
    unit: str = ""

@dataclass
class CheckResult:
    item: MeasureItem
    status: str = "未判定"           # 正常 / 需关注 / 报警 / 未判定
    cum_limit: str = "-"
    rate_limit: str = "-"
    cum_ratio: float | None = None
    rate_ratio: float | None = None
    evidence: list = field(default_factory=list)  # spec clauses retrieved from KB
    note: str = ""

# ------------------------------------------------------------ 1. Description parsing
NUM = r"(\d+(?:\.\d+)?)"

def parse_description(text: str, safety_level: str = "一级") -> list[MeasureItem]:
    """Extract monitoring items from a free-text description. Supported phrasing e.g.:
    '3号测点今日累计沉降32mm，日变化速率4.2mm/d，水位下降0.8m'
    'CX1测斜孔深层水平位移累计28.5mm，速率2.6mm/d；ZC3支撑轴力1850kN，设计值2600kN'
    """
    items: list[MeasureItem] = []
    segments = re.split(r"[；;。\n]", text)
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        # One segment may hold several items; split further by keyword anchors
        for it in _parse_segment(seg):
            items.append(it)
    return items

def _parse_segment(seg: str) -> list[MeasureItem]:
    # Monitoring point id
    point = ""
    m = re.search(r"([A-Za-z]{1,3}[-_]?\d+|\d+\s*号\s*(?:测点|监测点|点|孔|断面))", seg)
    if m:
        point = re.sub(r"\s+", "", m.group(1))
    # Match keywords longest-first with interval masking, so that
    # "深层水平位移" is not broken apart by the shorter "水平位移".
    flat = [(kw, canon) for canon, kws in ITEM_KEYWORDS.items() for kw in kws]
    flat.sort(key=lambda x: -len(x[0]))
    masked = list(seg)
    hits = []  # (pos, canon, kw)
    for kw, canon in flat:
        for mm in re.finditer(re.escape(kw), seg):
            s, e = mm.span()
            if any(masked[i] != "\0" for i in range(s, e)):
                hits.append((s, canon, kw))
                for i in range(s, e):
                    masked[i] = "\0"
    hits.sort()
    if not hits:
        return []
    # Anchor on each keyword; the numeric zone runs until the next keyword
    zones = []
    for i, (pos, canon, kw) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(seg)
        zones.append((canon, kw, seg[pos:end]))
    # Merge adjacent zones of the same canonical item
    # (e.g. "测斜孔" + "深层水平位移累计45mm")
    merged_zones = []
    for canon, kw, zone in zones:
        if merged_zones and merged_zones[-1][0] == canon:
            pk, pz = merged_zones[-1][1], merged_zones[-1][2]
            merged_zones[-1] = (canon, pk, pz + zone)
        else:
            merged_zones.append((canon, kw, zone))
    found = []
    for canon, kw, zone in merged_zones:
        it = MeasureItem(point=point, item=canon, raw_item=kw)
        mc = re.search(r"累计(?:变化)?(?:值|量)?(?:为|达|:|：)?\s*" + NUM + r"\s*(mm|毫米|m|米)?", zone)
        mr = re.search(r"(?:日)?(?:变化)?速率(?:为|达|:|：)?\s*" + NUM + r"\s*(mm/d|mm／d|毫米/天|mm每天)?", zone)
        mv = re.search(r"(?:本次值|本次|今[日次]|监测值|观测值|读数)(?:为|达|:|：)?\s*" + NUM + r"\s*(mm|毫米|m|米|kN|千牛)?", zone)
        md = re.search(r"(?:下降|上升|变化)(?:了|为|达|:|：)?\s*" + NUM + r"\s*(mm|毫米|m|米)?", zone)
        ma = re.search(r"设计(?:值|轴力|拉力)?\s*" + NUM + r"\s*(kN|千牛)?", zone)
        if mc:
            v, u = float(mc.group(1)), mc.group(2) or "mm"
            it.cumulative = v * 1000 if u in ("m", "米") and canon != "地下水位" else v
            if canon == "地下水位" and u in ("m", "米"):
                it.cumulative = v * 1000
        if mr:
            it.rate = float(mr.group(1))
        if mv:
            it.value = float(mv.group(1))
            it.unit = mv.group(2) or ""
        if md and it.cumulative is None:
            v, u = float(md.group(1)), md.group(2) or "mm"
            it.cumulative = v * 1000 if u in ("m", "米") else v
        if ma:
            it.value = it.value
            it.unit = it.unit or "kN"
            # Axial-force family: reading / design value -> occupancy percentage
            if it.value:
                it.cumulative = round(it.value / float(ma.group(1)) * 100, 1)  # percent
        # Fallback: bare number right after the keyword, e.g. "沉降32mm"
        if it.cumulative is None:
            m2 = re.search(re.escape(kw) + r"[^0-9]{0,6}" + NUM + r"\s*(mm|毫米|m|米)?", zone)
            if m2:
                v, u = float(m2.group(1)), m2.group(2) or "mm"
                it.cumulative = v * 1000 if u in ("m", "米") else v
        found.append(it)
    return found

# ------------------------------------------------------------ 2. Knowledge-base retrieval
_coll = None

def _get_coll():
    global _coll
    if _coll is None:
        import chromadb
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        model_path = str(MODEL_DIR) if (MODEL_DIR / "config.json").exists() else MODEL_NAME
        ef = SentenceTransformerEmbeddingFunction(model_name=model_path, device="cpu")
        client = chromadb.PersistentClient(path=str(DB_DIR))
        _coll = client.get_collection(name=COLLECTION, embedding_function=ef)
    return _coll

def kb_search(query: str, topk: int = 3):
    try:
        coll = _get_coll()
    except Exception:
        return []
    q = "为这个句子生成表示以用于检索相关文章：" + query  # bge query instruction prefix
    res = coll.query(query_texts=[q], n_results=topk)
    hits = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        hits.append({"score": round(1 - dist, 4), "source": meta.get("source", ""),
                     "clause": meta.get("clause", ""), "content": doc})
    return hits

# ------------------------------------------------------------ 3. Compliance checking
def load_rules():
    cfg = ROOT / "config" / "alarm_rules.json"
    if cfg.exists():
        return json.loads(cfg.read_text(encoding="utf-8"))
    return DEFAULT_ALARM_RULES

def check_item(it: MeasureItem, safety_level: str = "一级", rules=None) -> CheckResult:
    rules = rules or DEFAULT_ALARM_RULES
    r = CheckResult(item=it)
    rule = rules.get(it.item)
    lvl = "level1" if safety_level in ("一级", "1", "l1", "level1") else "level2"
    if not rule:
        r.note = "规则表未覆盖该项目"
    else:
        lim = rule.get(lvl) or rule.get("level1")
        if it.item in ("支撑轴力", "锚杆拉力"):
            pct_lim = lim.get("cum_pct", 80)
            r.cum_limit = f"设计值 {pct_lim}%"
            if it.cumulative is not None:  # already converted to percent
                r.cum_ratio = round(it.cumulative / pct_lim, 3)
        else:
            cum_rng, rate_rng = lim.get("cum"), lim.get("rate")
            cum_lim = max(cum_rng) if cum_rng else None
            rate_lim = max(rate_rng) if rate_rng else None
            r.cum_limit = f"{cum_rng[0]}~{cum_rng[1]} mm" if cum_rng and cum_rng[0] != cum_rng[1] else (f"{cum_lim} mm" if cum_lim else "-")
            r.rate_limit = f"{rate_rng[0]}~{rate_rng[1]} mm/d" if rate_rng and rate_rng[0] != rate_rng[1] else (f"{rate_lim} mm/d" if rate_lim else "-")
            if it.cumulative is not None and cum_lim:
                r.cum_ratio = round(it.cumulative / cum_lim, 3)
            if it.rate is not None and rate_lim:
                r.rate_ratio = round(it.rate / rate_lim, 3)
        # Judgement against the 70% / 100% thresholds
        ratios = [x for x in (r.cum_ratio, r.rate_ratio) if x is not None]
        if ratios:
            mx = max(ratios)
            r.status = "报警" if mx >= 1.0 else ("需关注" if mx >= 0.7 else "正常")
        else:
            r.status = "未判定"
            r.note = "描述中未给出可比数值"
    # Retrieve basis clauses from the knowledge base
    q = f"{it.item} 监测 报警值 累计值 变化速率 基坑"
    r.evidence = kb_search(q, topk=2)
    return r

# ------------------------------------------------------------ 4. Report generation
LEVEL_CN = {"正常": "✅ 正常", "需关注": "⚠️ 需关注", "报警": "🚨 报警", "未判定": "— 未判定"}

def generate_report(results: list[CheckResult], meta: dict) -> str:
    date_str = meta.get("date") or datetime.now().strftime("%Y-%m-%d")
    proj = meta.get("project", "基坑智守项目")
    lvl = meta.get("safety_level", "一级")
    weather = meta.get("weather", "晴")
    stage = meta.get("stage", "土方开挖阶段")
    overall = "报警" if any(r.status == "报警" for r in results) else (
        "需关注" if any(r.status == "需关注" for r in results) else "正常")

    L = []
    L.append(f"# {proj} 监测日报")
    L.append("")
    L.append(f"**文件编号**：基坑智守项目监测日报-{date_str.replace('-', '')}  ")
    L.append(f"**监测日期**：{date_str}　**天气**：{weather}　**基坑安全等级**：{lvl}")
    L.append("")
    L.append("## 第一节 工程概况与当日施工工况")
    L.append("")
    L.append(f"- 工程名称：{proj}")
    L.append(f"- 当日施工工况：{stage}")
    L.append(f"- 天气情况：{weather}")
    L.append("")
    L.append("## 第二节 监测数据汇总表")
    L.append("")
    L.append("| 测点 | 监测项目 | 本次值 | 累计变化量 | 变化速率 | 报警值(累计/速率) | 判定 |")
    L.append("|---|---|---|---|---|---|---|")
    for r in results:
        it = r.item
        cum = f"{it.cumulative}%" if it.item in ("支撑轴力", "锚杆拉力") and it.cumulative is not None else (
            f"{it.cumulative} mm" if it.cumulative is not None else "-")
        rate = f"{it.rate} mm/d" if it.rate is not None else "-"
        val = f"{it.value} {it.unit}" if it.value is not None else "-"
        mark = f"**{LEVEL_CN.get(r.status, r.status)}**" if r.status == "报警" else LEVEL_CN.get(r.status, r.status)
        L.append(f"| {it.point or '-'} | {it.item} | {val} | {cum} | {rate} | {r.cum_limit} / {r.rate_limit} | {mark} |")
    L.append("")
    L.append("## 第三节 数据分析与评价")
    L.append("")
    focus = [r for r in results if r.status in ("需关注", "报警")]
    if not focus:
        L.append("各监测项目本次监测数据变化平稳，累计变化量与变化速率均处于报警值 70% 以内，未见异常。")
    else:
        for r in focus:
            it = r.item
            L.append(f"- **{it.point or ''}{it.item}**：判定为「{r.status}」。" +
                     (f"累计变化占报警值 {round((r.cum_ratio or 0)*100)}%；" if r.cum_ratio else "") +
                     (f"变化速率占报警值 {round((r.rate_ratio or 0)*100)}%。" if r.rate_ratio else ""))
    L.append("")
    L.append("## 第四节 结论与建议")
    L.append("")
    L.append(f"**综合结论：{LEVEL_CN[overall]}**")
    L.append("")
    if overall == "报警":
        L.append("建议：1) 立即按 GB 50497-2019 第 8.0.9 条启动危险报警程序，电话/即时消息报告建设、监理、施工单位；"
                 "2) 加密监测频率至 1 次/2h，必要时连续监测；3) 暂停报警区域开挖作业，组织专家会诊。")
    elif overall == "需关注":
        L.append("建议：1) 提高监测频率；2) 加强报警值 70% 以上测点所在区域的巡视检查；3) 复核坑边堆载与降水运行情况。")
    else:
        L.append("建议：维持现有监测频率与施工方案，持续关注天气变化与坑边堆载。")
    L.append("")
    L.append("## 第五节 规范核对依据（知识库检索引用）")
    L.append("")
    seen = set()
    for r in results:
        for ev in r.evidence[:1]:
            key = (ev["source"], ev["clause"])
            if key in seen:
                continue
            seen.add(key)
            L.append(f"- 《{ev['source']}》条款 {ev['clause'] or '-'}：{ev['content'][:120]}…")
    L.append("")
    L.append("## 签字栏")
    L.append("")
    L.append("测试人：______　计算人：______　校核人：______　审核人：______")
    return "\n".join(L)

# ------------------------------------------------------------ One-stop entry
def run_pipeline(description: str, meta: dict) -> dict:
    rules = load_rules()
    items = parse_description(description, meta.get("safety_level", "一级"))
    results = [check_item(it, meta.get("safety_level", "一级"), rules) for it in items]
    report = generate_report(results, meta) if results else "未能从描述中识别出监测项目，请补充如「测点+项目+累计值/速率」的信息。"
    return {
        "parsed": [asdict(r.item) for r in results],
        "checks": [{
            "point": r.item.point, "item": r.item.item, "status": r.status,
            "cum_limit": r.cum_limit, "rate_limit": r.rate_limit,
            "cum_ratio": r.cum_ratio, "rate_ratio": r.rate_ratio,
            "evidence": r.evidence,
        } for r in results],
        "report_md": report,
    }


if __name__ == "__main__":
    demo = "3号测点今日累计沉降32mm，日变化速率4.2mm/d；CX1测斜孔深层水平位移累计28.5mm，速率2.6mm/d；水位下降0.8m"
    out = run_pipeline(demo, {"safety_level": "一级", "project": "基坑智守项目"})
    print(out["report_md"])
