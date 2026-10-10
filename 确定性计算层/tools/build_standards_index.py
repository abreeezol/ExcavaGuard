"""
扫描「基坑智守项目相关规范」目录，生成默认规范库索引。

只读原始规范文件（不复制、不改写 PDF 原文），仅提取：
  文件名、规范编号、规范名称、分类目录、路径、大小、页数、是否可解析文本、
  与基坑监测判定的相关性分级。

输出：standards/default/规范库索引.json
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

SPEC_ROOT = Path(r"C:\Study\bisai\Hai AI Agent\基坑智守项目相关规范")
OUT_DIR = Path(r"C:\Study\bisai\Hai AI Agent\ExcavaGuard\确定性计算层\standards\default")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 规范编号 -> 与基坑监测风险判定的相关性
RELEVANCE = {
    "GB50497-2019": ("primary", "监测类", "深基坑监测预警值、监测项目、监测频率、危险报警条件——本项目的**核心判据来源**"),
    "GB55003-2021": ("primary", "强制性通用规范", "地基基础通用规范，含基坑安全等级、变形控制、稳定性与监测要求（全文强制）"),
    "JGJ120-2012": ("primary", "配套行业标准", "基坑支护技术规程，含监测项目选择、报警危险征兆、稳定性验算"),
    "JGJ311-2013": ("secondary", "配套行业标准", "建筑深基坑工程施工安全技术规范"),
    "GB51004-2015": ("secondary", "施工与验收类", "建筑地基基础工程施工规范"),
    "GB50202-2018": ("secondary", "施工与验收类", "建筑地基基础工程施工质量验收标准"),
    "GB50007-2011": ("secondary", "勘察与设计类", "建筑地基基础设计规范（地基变形允许值，用于周边建筑沉降判据）"),
    "GB50330-2013": ("secondary", "勘察与设计类", "建筑边坡工程技术规范"),
    "JGJ111-2016": ("secondary", "配套行业标准", "建筑与市政工程地下水控制技术规范（地下水位/降水相关）"),
    "GB55030-2022": ("secondary", "强制性通用规范", "建筑与市政工程防水通用规范（渗漏水相关）"),
    "GB55001-2021": ("reference", "强制性通用规范", "工程结构通用规范"),
    "GB55017-2021": ("reference", "强制性通用规范", "工程勘察通用规范"),
    "GB55018-2021": ("reference", "强制性通用规范", "工程测量通用规范"),
    "GB55032-2022": ("reference", "强制性通用规范", "建筑与市政工程施工质量控制通用规范"),
    "GB55033-2022": ("reference", "强制性通用规范", "城市轨道交通工程项目规范"),
    "GB55034-2022": ("reference", "强制性通用规范", "施工现场安全卫生与职业健康通用规范"),
    "GB50021-2001": ("reference", "勘察与设计类", "岩土工程勘察规范"),
    "GB50201-2012": ("reference", "施工与验收类", "土方与爆破工程施工及验收规范"),
    "GB50300-2013": ("reference", "施工与验收类", "建筑工程施工质量验收统一标准"),
    "GB51254-2017": ("reference", "施工与验收类", "高填方地基技术规范"),
    "GBT51351-2019": ("reference", "施工与验收类", "建筑边坡工程施工质量验收标准"),
    "JGJ180-2009": ("reference", "配套行业标准", "建筑施工土石方工程安全技术规范"),
    "JGJ33-2012": ("reference", "配套行业标准", "建筑机械使用安全技术规范"),
    "JGJ46-2005": ("reference", "配套行业标准", "施工现场临时用电安全技术规范"),
    "JGJ59-2011": ("reference", "配套行业标准", "建筑施工安全检查标准"),
    "GB50025-2018": ("conditional", "特殊土与特殊条件", "湿陷性黄土地区建筑标准（仅黄土地区适用）"),
    "GB50324-2014": ("conditional", "特殊土与特殊条件", "冻土工程地质勘察规范（仅冻土地区适用）"),
    "GBT50942-2014": ("conditional", "特殊土与特殊条件", "盐渍土地区建筑技术规范（仅盐渍土地区适用）"),
    "GBT51238-2018": ("conditional", "特殊土与特殊条件", "岩溶地区建筑地基基础技术标准（仅岩溶地区适用）"),
}

CODE_RE = re.compile(r"(GB/?T?\s?\d{4,5}(?:-\d{4})?|JGJ\s?\d{2,3}(?:-\d{4})?)", re.I)


def norm_code(raw: str) -> str:
    s = raw.upper().replace(" ", "")
    s = s.replace("GB/T", "GBT").replace("GB", "GB")
    return s


entries = []
for p in sorted(SPEC_ROOT.rglob("*.pdf")):
    rel = p.relative_to(SPEC_ROOT)
    category = rel.parts[0] if len(rel.parts) > 1 else "根目录"
    m = CODE_RE.search(p.stem)
    code = norm_code(m.group(1)) if m else ""
    name = p.stem
    if code:
        name = p.stem.replace(m.group(1), "").strip(" -—").strip() or p.stem

    pages = None
    extractable = False
    err = None
    try:
        r = PdfReader(str(p))
        pages = len(r.pages)
        try:
            txt = r.pages[0].extract_text() or ""
            extractable = len(txt.strip()) > 20
        except Exception as exc:  # noqa: BLE001
            err = f"首页文本提取失败: {type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"

    relv, cat2, note = RELEVANCE.get(code, ("reference", category, "未纳入本项目核心判据，作为背景参考"))
    entries.append(
        {
            "code": code,
            "name": name,
            "file_name": p.name,
            "category": category,
            "path": str(p).replace("\\", "/"),
            "size_bytes": p.stat().st_size,
            "pages": pages,
            "text_extractable": extractable,
            "relevance": relv,
            "scope_note": note,
            "error": err,
        }
    )

by_rel: dict[str, list] = {}
for e in entries:
    by_rel.setdefault(e["relevance"], []).append(e["code"])

index = {
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "source_root": str(SPEC_ROOT).replace("\\", "/"),
    "description": "默认规范库索引。本目录内的规范被视为覆盖大多数情况的通用规范，作为阶段3「规范比对识别风险」的默认判据来源。",
    "readonly": True,
    "note": "索引仅记录规范元信息与路径，不复制、不改写 PDF 原文；条文级阈值另存于同目录 thresholds_gb50497_2019.json。",
    "stats": {
        "total": len(entries),
        "by_category": {},
        "by_relevance": {k: len(v) for k, v in by_rel.items()},
        "text_extractable": sum(1 for e in entries if e["text_extractable"]),
        "scanned_pages": sum(1 for e in entries if e["pages"]),
    },
    "relevance_legend": {
        "primary": "核心判据来源，直接提供监测预警值与风险判定规则",
        "secondary": "支撑性依据，提供变形允许值、施工要求、地下水控制等补充判据",
        "conditional": "条件适用，仅在特定地质/地区条件下启用",
        "reference": "背景参考，不直接用于风险判定",
    },
    "standards": entries,
}
for e in entries:
    index["stats"]["by_category"].setdefault(e["category"], 0)
    index["stats"]["by_category"][e["category"]] += 1

out = OUT_DIR / "规范库索引.json"
out.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"written: {out}")
print(json.dumps(index["stats"], ensure_ascii=False, indent=2))
print("\nprimary / secondary：")
for e in entries:
    if e["relevance"] in ("primary", "secondary"):
        print(f"  [{e['relevance']:<9}] {e['code']:<14} p{e['pages']:<4} {e['name'][:40]}")
