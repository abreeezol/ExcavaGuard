# -*- coding: utf-8 -*-
"""
verdict_table.py —— 「判定汇总表」10 列版式（与用户提供的样例图片同构）
=========================================================================

版式（Excel 第 1 行 = 表头，第 2 行起 = 数据）：

    A 监测项目 | B 点号 | C 本次变化量(单位) | D 变化速率(单位/d) | E 累计变化量(单位)
    | F 报警值(单位) | G 控制值(单位) | H 等级 | I 规范条文 | J 规范依据摘要

I / J 两列的口径（本模块的核心）
--------------------------------
- **I 规范条文**：该监测项在**内置规范判据库**（GB 50497-2019 表 8.0.4 / 表 8.0.5）
  中有适用判据 → 填表号（如 `表8.0.4`）；判据库中查不到（如「立柱内力」）→
  退化为知识库检索，填 `RAG命中 GB50497-2019`；两者都无 → `无适用条文`。
- **J 规范依据摘要**：`依据{表号}（{规范名}，{注}）；RAG命中《{规范名}》{条文号}（相关度）`；
  判据库无该项时以 `RAG命中《…》…：{摘要}` 为主。

本模块**不自行读取原始文件**：输入是 `fill_summary_table.py` 已清洗、已按期派生的记录。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import rate_rules

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
STANDARD_FULL = "GB 50497-2019《建筑基坑工程监测技术标准》"
STANDARD_SHORT = "GB50497-2019"

LEVEL_OK = "正常"
LEVEL_YELLOW = "黄色"
LEVEL_ORANGE = "橙色"
LEVEL_RED = "红色"
LEVEL_UNKNOWN = "未知"
LEVEL_ORDER = [LEVEL_OK, LEVEL_YELLOW, LEVEL_ORANGE, LEVEL_RED]

UNKNOWN_LIMIT = "未知"

# 监测项目（skill 规范名） → 内置判据库 metric key
METRIC_TO_KEY = {
    # 附录 C / D 族
    "土压力": "earth_pressure",
    "孔隙水压力": "pore_pressure",
    "围护墙内力": "wall_internal_force",
    "立柱内力": "column_internal_force",
    "支撑轴力": "support_axial_force",
    "锚杆轴力": "anchor_axial_force",
    # 附录 E / F 族
    "地下水位": "groundwater_level",
    "周边地表竖向位移": "surface_settlement",
    "土体分层竖向位移": "soil_layered_vertical_displacement",
    "坑底隆起": "basal_heave",
    "裂缝": "crack_width_building",
}

# 设计值符号（写入 J 列，便于溯源）
DESIGN_SYMBOL = {
    "earth_pressure": "f1",
    "pore_pressure": "f1",
    "wall_internal_force": "f2",
    "support_axial_force": "f2",
    "anchor_axial_force": "fy",
}

VERDICT_COLUMNS = [
    "监测项目", "点号",
    "本次变化量", "变化速率", "累计变化量",
    "报警值", "控制值",
    "等级", "规范条文", "规范依据摘要",
]
N_VERDICT_COL = len(VERDICT_COLUMNS)


# ---------------------------------------------------------------------------
# 判据库
# ---------------------------------------------------------------------------
def load_library(path: str | Path) -> dict:
    """载入 GB 50497-2019 预警值判据库；失败返回空库（不抛异常）。"""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"metrics": {}}


def _pick_rule(entry: dict, safety_level: str, crack_state: str | None = None) -> dict | None:
    rules = (entry or {}).get("rules") or []
    if not rules:
        return None
    lvl = str(safety_level or "一级").strip()
    cands = [r for r in rules if lvl in (r.get("safety_level") or [])] or list(rules)
    if crack_state:
        by_state = [r for r in cands if crack_state in (r.get("crack_state") or [])]
        if by_state:
            cands = by_state
    return cands[0]


def _clauses_of(entry: dict) -> list[str]:
    out: list[str] = []
    for r in (entry or {}).get("rules") or []:
        cl = ((r.get("evidence") or {}).get("clause") or "").strip()
        if cl and cl not in out:
            out.append(cl)
    return out


def resolve_limit(metric: str, safety_level: str, lib: dict,
                  limits: dict | None = None,
                  design: dict | None = None,
                  unit: str = "",
                  crack_state: str = "新增裂缝") -> dict:
    """解析某监测项的生效限值。

    优先级：
      ① 显式 `--limits`（绝对量，warn / control / rate）
      ② 内置判据库 —— 位移/水位类取累计值区间；内力/轴力类取设计值占比
      ③ 均无 → 未知

    返回 dict：
      warn / control / rate      —— 数值限值（不可用为 None）
      warn_disp / control_disp   —— 表格展示文本
      mode                       —— `absolute` / `ratio_max` / `ratio_min` / `none`
      clause / standard / note   —— 规范依据
      basis                      —— 判定对象（`累计变化量` / `本次测值`）
      detail                     —— 限值推导过程（写入说明页）
    """
    metric = str(metric).strip()
    out = dict(warn=None, control=None, rate=None,
               warn_disp=UNKNOWN_LIMIT, control_disp=UNKNOWN_LIMIT,
               mode="none", clause="", standard="", note="",
               basis="累计变化量", detail="", ratio_text="")

    # ① 显式阈值
    spec = None
    if limits:
        spec = limits.get(metric) or limits.get("*")
    if spec:
        warn, ctrl, rate = spec.get("warn"), spec.get("control"), spec.get("rate")
        out.update(warn=warn, control=ctrl, rate=rate, mode="absolute",
                   clause=spec.get("clause", ""),
                   standard=spec.get("standard", "项目专项监测方案"),
                   note=spec.get("note", "阈值由项目专项监测方案给定"),
                   basis="累计变化量",
                   detail="限值来自 --limits（项目专项监测方案）")
        out["warn_disp"] = f"{warn:g}" if isinstance(warn, (int, float)) else UNKNOWN_LIMIT
        out["control_disp"] = f"{ctrl:g}" if isinstance(ctrl, (int, float)) else UNKNOWN_LIMIT
        return out

    # ② 内置判据库
    entry = (lib.get("metrics") or {}).get(METRIC_TO_KEY.get(metric, ""))
    if not entry:
        out["note"] = "内置判据库未收录该监测项"
        out["detail"] = "内置判据库未收录该监测项，无法给出预警值"
        return out

    rules = entry.get("rules") or []
    if not rules:
        out["note"] = entry.get("note") or "该监测项在 GB 50497-2019 中未给出预警值"
        out["detail"] = out["note"]
        return out

    rule = _pick_rule(entry, safety_level, crack_state)
    ev = rule.get("evidence") or {}
    out["clause"] = (ev.get("clause") or "").strip()
    out["standard"] = ev.get("standard") or "GB 50497-2019"
    out["note"] = (ev.get("note") or "").strip()
    mode = entry.get("limit_mode")

    if mode in ("displacement", "crack"):
        cum = rule.get("cumulative_mm") or {}
        rate = rule.get("rate_mm_per_day") or {}
        out["mode"] = "absolute"
        out["warn"] = cum.get("min")
        out["control"] = cum.get("max")
        out["rate"] = rate.get("min")
        out["basis"] = "累计变化量"
        out["warn_disp"] = f"{out['warn']:g}" if out["warn"] is not None else UNKNOWN_LIMIT
        out["control_disp"] = f"{out['control']:g}" if out["control"] is not None else UNKNOWN_LIMIT
        state = rule.get("crack_state")
        state_txt = f"（{'/'.join(state)}）" if state else ""
        base = (f"{out['clause']}{state_txt}：累计值 "
                f"{out['warn_disp']}~{out['control_disp']} {unit}")
        if out["rate"] is not None:
            base += f"，变化速率 {out['rate']:g} {unit}/d"
        if rule.get("requires_continuous_development"):
            base += "；持续发展时应预警"
        out["detail"] = base
        return out

    if mode in ("max_ratio", "min_ratio"):
        key = "max_ratio_of_design" if mode == "max_ratio" else "min_ratio_of_design"
        rng = rule.get(key) or {}
        rmin, rmax = rng.get("min"), rng.get("max")
        sym = DESIGN_SYMBOL.get(METRIC_TO_KEY.get(metric, ""), "f")
        out["mode"] = "ratio_max" if mode == "max_ratio" else "ratio_min"
        out["basis"] = "本次测值"
        out["ratio_text"] = f"{rmin:.0%}~{rmax:.0%}{sym}"
        d = None
        if design:
            d = design.get(metric)
            if d is None:
                d = design.get(METRIC_TO_KEY.get(metric, ""))
        if isinstance(d, (int, float)) and d > 0:
            out["warn"] = round(rmin * d, 2)
            out["control"] = round(rmax * d, 2)
            out["warn_disp"] = f"{out['warn']:g}"
            out["control_disp"] = f"{out['control']:g}"
            out["detail"] = (f"{out['clause']}：{('最大值' if mode == 'max_ratio' else '最小值')} "
                             f"{out['ratio_text']}，{sym}={d:g} {unit} → "
                             f"报警值 {out['warn']:g} {unit}、控制值 {out['control']:g} {unit}")
        else:
            out["warn_disp"] = f"{rmin:.0%}{sym}"
            out["control_disp"] = f"{rmax:.0%}{sym}"
            out["detail"] = (f"{out['clause']}：{('最大值' if mode == 'max_ratio' else '最小值')} "
                             f"{out['ratio_text']}；未提供设计值 {sym}，无法换算绝对量限值，"
                             f"等级不作判定")
        return out

    out["note"] = entry.get("note") or "该监测项在 GB 50497-2019 中未给出预警值"
    out["detail"] = out["note"]
    return out


# ---------------------------------------------------------------------------
# 等级判定
# ---------------------------------------------------------------------------
def _grade_core(row: dict, lim: dict) -> tuple[str, str]:
    """返回 (等级, 判定理由)。**判据不足时返回「未知」= 弃权，不是「安全」。**"""
    mode = lim.get("mode")
    warn, ctrl = lim.get("warn"), lim.get("control")

    if mode == "none":
        return LEVEL_UNKNOWN, lim.get("detail") or "无适用判据，须由项目专项监测方案确认"

    if mode == "ratio_max":
        if warn is None or ctrl is None:
            return LEVEL_UNKNOWN, lim.get("detail") or "未提供设计值，无法换算限值"
        v = row.get("value")
        if v is None:
            return LEVEL_UNKNOWN, "测值缺失"
        a = abs(v)
        if a >= ctrl:
            return LEVEL_RED, f"测值 {a:g} 达到/超过控制值 {ctrl:g}（{lim.get('ratio_text')}）"
        if a >= warn:
            return LEVEL_ORANGE, f"测值 {a:g} 达到/超过报警值 {warn:g}（{lim.get('ratio_text')}）"
        return LEVEL_OK, f"测值 {a:g} 低于报警值 {warn:g}（{lim.get('ratio_text')}）"

    if mode == "ratio_min":
        if warn is None or ctrl is None:
            return LEVEL_UNKNOWN, lim.get("detail") or "未提供设计值，无法换算限值"
        v = row.get("value")
        if v is None:
            return LEVEL_UNKNOWN, "测值缺失"
        a = abs(v)
        if a < warn:
            return LEVEL_RED, f"测值 {a:g} 低于下限 {warn:g}（{lim.get('ratio_text')}），预应力松弛报警"
        if a > ctrl:
            return LEVEL_ORANGE, f"测值 {a:g} 超过上限 {ctrl:g}（{lim.get('ratio_text')}）"
        return LEVEL_OK, f"测值 {a:g} 处于 {lim.get('ratio_text')} 区间内"

    # absolute（位移/水位类 或 显式阈值）：以累计变化量为主判据
    cum = row.get("cumulative")
    rate = row.get("rate")
    reasons: list[str] = []
    lvl = LEVEL_OK
    if cum is not None and ctrl is not None and abs(cum) >= ctrl:
        lvl = LEVEL_RED
        reasons.append(f"累计变化量 {abs(cum):g} 达到/超过控制值 {ctrl:g}")
    elif cum is not None and warn is not None and abs(cum) >= warn:
        lvl = LEVEL_ORANGE
        reasons.append(f"累计变化量 {abs(cum):g} 达到/超过报警值 {warn:g}")
    elif cum is not None and warn is not None and abs(cum) >= warn * 0.7:
        lvl = LEVEL_YELLOW
        reasons.append(f"累计变化量 {abs(cum):g} 达到报警值 70%（{warn * 0.7:g}）")

    rl = lim.get("rate")
    if rl is not None and rate is not None and abs(rate) >= rl:
        if LEVEL_ORDER.index(lvl) < LEVEL_ORDER.index(LEVEL_ORANGE):
            lvl = LEVEL_ORANGE
        reasons.append(f"变化速率 {abs(rate):g} 达到/超过速率限值 {rl:g}")

    if not reasons:
        reasons.append("各判据均未达预警线")
    return lvl, "；".join(reasons)


def grade_row(row: dict, lim: dict, *, rate_rules_enabled: bool = True,
              sudden_factor: float = 3.0,
              sudden_ack: bool = False) -> tuple[str, str]:
    """在累计量判据之上叠加**速率口径判据**后返回 (等级, 判定理由)。

    速率口径判据（GB 50497-2019 第 8.0.3 条「连续 3 次超 70%」、第 8.0.9-1 条「突然明显增大」）
    需要**期次序列**（`row["series_changes"]` / `row["series_rates"]`）；序列缺失或为亚日级时主动弃权。
    """
    level, reason = _grade_core(row, lim)
    rr = rate_rules.evaluate_series(
        row.get("series_changes"), row.get("series_rates"), lim.get("rate"),
        enable=rate_rules_enabled, sudden_factor=sudden_factor,
        interval_minutes=row.get("interval_minutes"), sudden_ack=sudden_ack)
    if rr.get("sudden_blocked"):
        row["_sudden_blocked"] = rr["sudden_blocked"]
    if rr["level"]:
        level = rate_rules.bump_level(level, rr["level"])
        clauses = "；".join(rr["clauses"])
        reason = "；".join([reason] + rr["reasons"] + ([f"依据 {clauses}"] if clauses else []))
    return level, reason


# ---------------------------------------------------------------------------
# I / J 两列
# ---------------------------------------------------------------------------
def _clip(text: str, n: int = 60) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= n else t[:n] + "…"


def clause_column(metric: str, lim: dict, rag_hit: dict | None) -> str:
    """I 列 · 规范条文。"""
    cl = lim.get("clause")
    if cl:
        return cl
    if lim.get("mode") != "none":
        return cl or "无适用条文"
    if rag_hit and rag_hit.get("ok"):
        return f"RAG命中 {STANDARD_SHORT}"
    return "无适用条文"


def basis_column(metric: str, lim: dict, rag_hit: dict | None,
                 rag_available: bool = True) -> str:
    """J 列 · 规范依据摘要。"""
    parts: list[str] = []
    cl = lim.get("clause")
    if cl:
        note = lim.get("note")
        tail = f"，{note}" if note and note not in (cl,) else ""
        parts.append(f"依据{cl}（{STANDARD_FULL.split('《')[0].strip()}{tail}）")
        if lim.get("mode") in ("ratio_max", "ratio_min"):
            parts.append(f"判定对象为本次测值，限值 {lim.get('ratio_text')}")
        elif lim.get("detail"):
            parts.append(lim["detail"])
    else:
        parts.append(lim.get("detail") or "内置判据库未收录该监测项")

    if rag_hit and rag_hit.get("ok"):
        src = rag_hit.get("source") or ""
        rcl = (rag_hit.get("clause") or "").strip()
        score = rag_hit.get("score")
        cite = f"RAG命中《{src}》" + (f" {rcl}" if rcl else "")
        if score is not None:
            cite += f"（相关度 {score}）"
        if not cl:
            cite += f"：{_clip(rag_hit.get('content'), 60)}"
        parts.append(cite)
    elif not rag_available:
        parts.append("未接入知识库，未做 RAG 命中")
    return "；".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# 组装行
# ---------------------------------------------------------------------------
def build_verdict_rows(period_rows: list[dict], lib: dict, *,
                       limits: dict | None = None,
                       design: dict | None = None,
                       rag: dict | None = None,
                       safety_level: str = "一级",
                       rag_available: bool = True,
                       rate_rules_enabled: bool = True,
                       sudden_factor: float = 3.0,
                       sudden_ack: bool = False) -> list[dict]:
    """把清洗后的记录组装成判定汇总表的行。"""
    hits = (rag or {}).get("hits") or {}
    out: list[dict] = []
    for r in period_rows:
        metric = r["metric"]
        unit = r.get("unit") or ("kPa" if r.get("sheet") == "表C" else "kN")
        lim = resolve_limit(metric, safety_level, lib, limits, design, unit)
        hit = hits.get(metric)
        lvl, reason = grade_row(r, lim, rate_rules_enabled=rate_rules_enabled,
                                sudden_factor=sudden_factor, sudden_ack=sudden_ack)
        out.append(dict(
            metric=metric, point=r["pid"], sheet=r.get("sheet"), unit=unit,
            change=r.get("change"), rate=r.get("rate"), cumulative=r.get("cumulative"),
            value=r.get("value"), depth=r.get("depth"), ts=r.get("ts"),
            interval_minutes=r.get("interval_minutes"),
            warn_disp=lim.get("warn_disp"), control_disp=lim.get("control_disp"),
            level=lvl, clause=clause_column(metric, lim, hit),
            basis=basis_column(metric, lim, hit, rag_available),
            reason=reason, limit=lim, rag_hit=hit,
        ))
    out.sort(key=lambda x: (
        {"表C": 0, "表D": 1}.get(x.get("sheet"), 9),
        ["土压力", "孔隙水压力", "围护墙内力", "立柱内力", "支撑轴力", "锚杆轴力"].index(x["metric"])
        if x["metric"] in ["土压力", "孔隙水压力", "围护墙内力", "立柱内力", "支撑轴力", "锚杆轴力"] else 99,
        str(x["point"]),
    ))
    return out


# ---------------------------------------------------------------------------
# 写表
# ---------------------------------------------------------------------------
def _fmt_num(v, digits: int = 3):
    if v is None:
        return "—"
    try:
        return round(float(v), digits)
    except (TypeError, ValueError):
        return "—"


def write_verdict_sheet(ws, rows: list[dict], sheet_key: str) -> None:
    """写出单张判定汇总 sheet（严格 10 列，第 1 行为表头）。"""
    from openpyxl.styles import Alignment, Border, Font, Side
    from openpyxl.utils import get_column_letter

    unit = "kPa" if sheet_key == "表C" else "kN"
    headers = [
        "监测项目", "点号",
        f"本次变化量({unit})", f"变化速率({unit}/d)", f"累计变化量({unit})",
        f"报警值({unit})", f"控制值({unit})",
        "等级", "规范条文", "规范依据摘要",
    ]
    thin = Side(style="thin", color="FF999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for ci, name in enumerate(headers, start=1):
        c = ws.cell(row=1, column=ci, value=name)
        c.font = Font(bold=True, size=10)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border

    for ri, r in enumerate(rows, start=2):
        vals = [
            r["metric"], r["point"],
            _fmt_num(r["change"]), _fmt_num(r["rate"]), _fmt_num(r["cumulative"]),
            r["warn_disp"], r["control_disp"],
            r["level"], r["clause"], r["basis"],
        ]
        if len(vals) != N_VERDICT_COL:                  # 列数错位保护
            vals = (vals + ["—"] * N_VERDICT_COL)[:N_VERDICT_COL]
        for ci, v in enumerate(vals, start=1):
            c = ws.cell(row=ri, column=ci, value=v)
            c.font = Font(size=10)
            c.border = border
            if ci in (3, 4, 5):
                c.alignment = Alignment(horizontal="right", vertical="center")
                if isinstance(v, (int, float)):
                    c.number_format = "0.000"
            elif ci == 6 or ci == 7:
                c.alignment = Alignment(horizontal="right", vertical="center")
            elif ci == 10:
                c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            else:
                c.alignment = Alignment(horizontal="center", vertical="center")

    widths = [14, 11, 13, 14, 14, 12, 12, 8, 14, 62]
    for ci, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(N_VERDICT_COL)}{len(rows) + 1}"


def write_notes_sheet(ws, meta: dict, rows: list[dict], rag: dict | None,
                      rag_available: bool) -> None:
    """写出「说明」页：抬头 / 判据来源 / 判定口径 / 边界声明 / RAG 命中明细。"""
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    def put(r, text, bold=False, size=10):
        c = ws.cell(row=r, column=1, value=text)
        c.font = Font(bold=bold, size=size)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
        return r + 1

    r = 1
    r = put(r, f"{meta.get('project', '××工程')}监测数据判定汇总表（草稿）", bold=True, size=14)
    r = put(r, f"报表编号：{meta.get('report_no', '＿＿＿＿')}　　"
               f"目标期：{meta.get('period', '＿＿＿＿')}　　"
               f"基坑设计安全等级：{meta.get('safety_level', '一级')}")
    r = put(r, f"数据来源：{meta.get('source', '用户上传监测数据')}　　"
               f"测点行数：{len(rows)}")
    r += 1

    r = put(r, "一、判据来源", bold=True, size=11)
    r = put(r, f"1. 内置判据库：{STANDARD_FULL} 表 8.0.4（基坑及支护结构监测预警值）、"
               f"表 8.0.5（基坑工程周边环境监测预警值）。")
    r = put(r, "2. 知识库检索：" + (
        "已接入规范知识库（jikeng-rag），命中结果见本页第五节。"
        if rag_available else
        "未接入，I/J 两列的 RAG 部分留空并注明，不补造条文。"))
    r = put(r, "3. 优先级：显式 --limits（项目专项监测方案）> 内置判据库 > 知识库检索。")
    r = put(r, "4. 速率口径判据：" + (meta.get("rate_rules_note") or
               "已启用 GB 50497-2019 第 8.0.3 条「变化速率连续 3 次超过规定值 70%」；"
               "第 8.0.9-1 条「位移值突然明显增大」按工程经验阈值判定，"
               "该阈值规范未定量，用于真实工程前须由项目专项监测方案确认。"))
    r += 1

    r = put(r, "二、判定口径", bold=True, size=11)
    r = put(r, "1. 位移 / 水位类（限值为累计量区间）：|累计变化量| ≥ 控制值 → 红色；"
               "≥ 报警值 → 橙色；≥ 报警值×70% → 黄色；否则 正常。"
               "|变化速率| ≥ 速率限值 → 至少橙色。")
    r = put(r, "2. 内力 / 轴力类（限值为设计值占比，判定对象是**本次测值**）："
               "提供设计值后按 测值 与 占比限值 比对；未提供设计值 → 等级 未知。")
    r = put(r, "3. 报警值 = 规范区间下限，控制值 = 规范区间上限（与判据库区间取法一致）。")
    r = put(r, "4. 等级「未知」表示**弃权，不是「安全」**，必须转人工复核。")
    ivs = sorted({round(x["interval_minutes"]) for x in rows
                  if x.get("interval_minutes") and round(x["interval_minutes"]) > 0})
    if ivs:
        iv = ivs[0]
        r = put(r, f"5. 本次变化量 = 末期测值 − 相邻上一期测值；变化速率 = 本次变化量 ÷ 实际采样间隔。"
                   f"本表数据的相邻期间隔为 **{iv} 分钟**"
                   + (f"（即速率为变化量的 {1440 / iv:.0f} 倍，属外推值，仅供趋势参考）"
                      if iv else "")
                   + "。若需按「日」口径（当日末次 − 前日末次），改用 --period daily。")
    else:
        r = put(r, "5. 本次变化量 = 末期测值 − 相邻上一期测值；变化速率 = 本次变化量 ÷ 实际采样间隔。")
    r += 1

    r = put(r, "三、边界声明", bold=True, size=11)
    r = put(r, "1. 本表为监测数据整理与判定的**辅助材料**，由责任人员复核后进入签发、归档流程，"
               "不替代责任单位出具的正式监测报告。")
    r = put(r, "2. 表式以 GB 50497-2019 附录 A~G 为基准；本表为**判定汇总视图**，"
               "不替代附录 C / D 原始记录表式。")
    r = put(r, "3. 判定阈值以**项目专项监测方案**为准（GB 50497-2019 第 8.0.1 条："
               "监测预警值应由基坑工程设计方确定）；未配置阈值的一律不作判定。")
    r = put(r, "4. 红色等级须经人工确认，正式预警发布与工程处置沿用既有责任流程。")
    r = put(r, "5. 表中「—」表示数据源未提供或该期数据缺失，**未作插值填补**。")
    r += 1

    r = put(r, "四、限值推导过程（按监测项目）", bold=True, size=11)
    seen: dict[str, str] = {}
    for row in rows:
        seen.setdefault(row["metric"], row["limit"].get("detail") or "—")
    for metric, detail in seen.items():
        r = put(r, f"· {metric}：{detail}")
    r += 1

    r = put(r, "五、知识库（RAG）命中明细", bold=True, size=11)
    hit_rows = []
    for metric in seen:
        h = ((rag or {}).get("hits") or {}).get(metric)
        if h and h.get("ok"):
            hit_rows.append(h)
    if hit_rows:
        hdr = ["监测项目", "规范名", "条文号", "相关度", "命中摘要"]
        for ci, h in enumerate(hdr, start=1):
            c = ws.cell(row=r, column=ci, value=h)
            c.font = Font(bold=True, size=10)
        r += 1
        for metric in seen:
            h = ((rag or {}).get("hits") or {}).get(metric)
            if not (h and h.get("ok")):
                continue
            for ci, v in enumerate([metric, h.get("source", ""), h.get("clause", "") or "—",
                                    h.get("score"), _clip(h.get("content"), 120)], start=1):
                c = ws.cell(row=r, column=ci, value=v)
                c.font = Font(size=10)
                c.alignment = Alignment(wrap_text=True, vertical="top")
            r += 1
    else:
        r = put(r, "（本次未接入知识库或未命中）")
    r += 1

    r = put(r, "六、签署", bold=True, size=11)
    r = put(r, "编制：＿＿＿＿　　　　审核：＿＿＿＿　　　　签发：＿＿＿＿（留空待签，不得代填）")

    for ci, w in enumerate([22, 34, 14, 10, 60, 20], start=1):
        ws.column_dimensions[get_column_letter(ci)].width = w
