# -*- coding: utf-8 -*-
"""
appendix_table.py —— GB 50497-2019 附录 C / D / E / F 原表式输出
==================================================================

版式**严格参考** `监测日报_附表AF_RAG.xlsx` 中的 附表C / 附表D / 附表E / 附表F：

| Excel 行 | 内容 |
|:--:|---|
| 1 | `第（N）次` |
| 2 | `工程名称：…　报表编号：…` |
| 3 | `天气：…　观测者：…　计算者：…　校核者：…`（表 D / F 无「天气」） |
| 4 | `仪器型号：…　仪器编号：…　检定有效期：…` |
| 5 | `本次监测时间：…　上次监测时间：…` |
| **6** | **表头** |
| 7+ | 数据行 |
| … | （空行 ×2） |
| … | `工况描述：…` |
| … | `简要分析及判断性结论：…`（表 F 为「当日监测的…」） |
| … | `工程负责人：…　监测单位：…` |
| … | `第 　页 共 　页` |
| … | （空行） |
| … | `简要分析及判断性结论` + 逐条统计 + `结论：…` |

表头（第 6 行）：

| 表 | 表头 |
|---|---|
| 表 C / 表 D | `深度(m)｜本次测值｜上次测值｜本次变化｜累计变化｜组号｜点号｜备注` |
| 表 E | `初始高程｜本次高程｜上次高程｜本次变化｜累计变化｜变化速率｜编号｜点号｜备注` |
| 表 F | `长度(mm)｜宽度(mm)｜本次测试值｜单次变化｜累计变化｜变化速率｜点号｜形态｜备注` |

「备注」列内嵌判定信息，与参考文档同构：
`预警等级：黄色(需关注)；报警值：112 kPa；占报警值：116.1%；超报警值：是`
"""

from __future__ import annotations

from collections import defaultdict

import rate_rules
import verdict_table as vt

ROW_HEADER = 6
ROW_DATA = 7

FAMILY_TITLE = {
    "表C": "围护墙内力等",
    "表D": "支撑轴力等",
    "表E": "地下水位等",
    "表F": "裂缝",
}
FAMILY_UNIT = {"表C": "kPa", "表D": "kN", "表E": "mm", "表F": "mm"}

# 等级显示口径（与参考文档的「备注」写法一致）
LEVEL_DISPLAY = {
    "正常": "正常",
    "黄色预警": "黄色(需关注)",
    "橙色预警": "橙色(预警)",
    "红色预警": "红色(报警)",
    vt.LEVEL_OK: "正常",
    vt.LEVEL_YELLOW: "黄色(需关注)",
    vt.LEVEL_ORANGE: "橙色(预警)",
    vt.LEVEL_RED: "红色(报警)",
    vt.LEVEL_UNKNOWN: "未判定",
}

SPEC: dict[str, dict] = {
    "表C": {
        "header": ["深度(m)", "本次测值", "上次测值", "本次变化", "累计变化", "组号", "点号", "备注"],
        "ncol": 8, "weather": True, "date_col": False, "kind": "cd",
        "widths": [10, 12, 12, 12, 12, 7, 11, 60],
    },
    "表D": {
        "header": ["深度(m)", "本次测值", "上次测值", "本次变化", "累计变化", "组号", "点号", "备注"],
        "ncol": 8, "weather": False, "date_col": False, "kind": "cd",
        "widths": [10, 12, 12, 12, 12, 7, 11, 60],
    },
    "表E": {
        "header": ["初始高程", "本次高程", "上次高程", "本次变化", "累计变化", "变化速率", "编号", "点号", "备注"],
        "ncol": 9, "weather": True, "date_col": False, "kind": "e",
        "widths": [11, 11, 11, 11, 11, 11, 7, 11, 56],
    },
    "表F": {
        "header": ["长度(mm)", "宽度(mm)", "本次测试值", "单次变化", "累计变化", "变化速率", "点号", "形态", "备注"],
        "ncol": 9, "weather": False, "date_col": False, "kind": "f",
        "widths": [11, 11, 12, 11, 11, 11, 11, 9, 56],
    },
}


# ---------------------------------------------------------------------------
# 数值与备注
# ---------------------------------------------------------------------------
def _num(v, digits: int = 3):
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return round(f, digits)


def _fmt(v):
    """把数值格式化为无多余小数点的字符串。"""
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if abs(f - round(f)) < 1e-9:
        return f"{int(round(f))}"
    return f"{f:.2f}".rstrip("0").rstrip(".")


def resolve_row(row: dict, lib: dict, *, limits=None, design=None,
                safety_level: str = "一级", unit: str = "",
                rate_rules_enabled: bool = True,
                sudden_factor: float = 3.0,
                sudden_ack: bool = False) -> dict:
    """解析单行的 等级 / 报警值 / 占报警值。输入自带的判定信息优先。"""
    level = row.get("level_in")
    warn_abs = row.get("warn_in")
    pct = row.get("pct_in")
    lim = vt.resolve_limit(row["metric"], safety_level, lib, limits, design, unit)

    if not level:
        level, _ = vt.grade_row(row, lim)
    if warn_abs is None:
        warn_abs = lim.get("warn")

    warn_text = row.get("warn_text_in")
    if not warn_text:
        warn_text = f"{_fmt(warn_abs)} {unit}".strip() if warn_abs is not None else "未知"

    if pct is None and warn_abs and row.get("cumulative") is not None:
        try:
            pct = abs(float(row["cumulative"])) / float(warn_abs) * 100.0
        except (TypeError, ValueError, ZeroDivisionError):
            pct = None

    # 速率口径判据（GB 50497-2019 第 8.0.3 条 / 第 8.0.9-1 条）
    rr = rate_rules.evaluate_series(
        row.get("series_changes"), row.get("series_rates"), lim.get("rate"),
        enable=rate_rules_enabled, sudden_factor=sudden_factor,
        interval_minutes=row.get("interval_minutes"), sudden_ack=sudden_ack)
    if rr["level"]:
        level = rate_rules.bump_level(level, rr["level"])

    return {"level": level, "warn": warn_abs, "warn_text": warn_text,
            "pct": pct, "limit": lim,
            "rate_reasons": rr["reasons"], "rate_clauses": rr["clauses"],
            "rate_skipped": rr["skipped"], "sudden_blocked": rr["sudden_blocked"]}


def build_remark(info: dict, unit: str, extra: str = "") -> str:
    parts = [f"预警等级：{LEVEL_DISPLAY.get(info['level'], info['level'])}"]
    parts.append(f"报警值：{info.get('warn_text') or '未知'}")
    if info["pct"] is not None:
        parts.append(f"占报警值：{info['pct']:.1f}%")
        parts.append(f"超报警值：{'是' if info['pct'] >= 100 else '否'}")
    else:
        parts.append("占报警值：—")
    if info.get("rate_reasons"):
        clauses = "；".join(info.get("rate_clauses") or [])
        parts.append("速率口径判据：" + "；".join(info["rate_reasons"]) +
                     (f"（依据 {clauses}）" if clauses else ""))
    if info.get("sudden_blocked"):
        parts.append("突变判据未确认，已停用（" + info["sudden_blocked"] +
                     "；加 --ack-sudden-factor 后启用）")
    if extra:
        parts.append(extra)
    return "；".join(parts)


# ---------------------------------------------------------------------------
# 行构造
# ---------------------------------------------------------------------------
DERIVED_NOTE = "本次变化量/变化速率由累计序列推算"


def _row_values(kind: str, row: dict, info: dict, unit: str,
                derived_note: str = "auto") -> list:
    # 备注末端的来源说明：参考文档在所有附表固定追加；本 Skill 默认仅在**确实推算**时追加
    if derived_note == "always":
        extra = DERIVED_NOTE
    elif derived_note == "never":
        extra = ""
    else:  # auto
        extra = DERIVED_NOTE if row.get("rate_in") is None else ""
    remark = build_remark(info, unit, extra)
    if kind == "cd":
        grp = row.get("group_raw")
        if grp in (None, ""):
            grp = row.get("group_out")
        if grp in (None, ""):
            grp = row.get("group") if row.get("sheet") == "表D" else 1
        return [
            _num(row.get("depth")), _num(row.get("value")), _num(row.get("prev_value")),
            _num(row.get("change")), _num(row.get("cumulative")),
            (grp if grp not in (None, "") else "—"), row["pid"], remark,
        ]
    if kind == "e":
        grp = row.get("group_raw") or row.get("group_out")
        return [
            _num(row.get("elev_init")), _num(row.get("elev_now") or row.get("value")),
            _num(row.get("elev_prev") or row.get("prev_value")),
            _num(row.get("change")), _num(row.get("cumulative")), _num(row.get("rate")),
            (grp if grp not in (None, "") else "—"), row["pid"], remark,
        ]
    # 表 F
    return [
        _num(row.get("length")), _num(row.get("width")), _num(row.get("value")),
        _num(row.get("change")), _num(row.get("cumulative")), _num(row.get("rate")),
        row["pid"], (row.get("form") or "—"), remark,
    ]


# ---------------------------------------------------------------------------
# 抬头 / 页脚 / 简要分析
# ---------------------------------------------------------------------------
def _head_rows(sheet_key: str, meta: dict) -> list[str]:
    spec = SPEC[sheet_key]
    obs = (f"观测者：{meta.get('observer', '＿＿＿＿')}　　"
           f"计算者：{meta.get('calculator', '＿＿＿＿')}　　"
           f"校核者：{meta.get('checker', '＿＿＿＿')}")
    row3 = f"天气：{meta.get('weather', '＿＿＿＿')}　　{obs}" if spec["weather"] else obs
    return [
        f"第（{meta.get('times', 1)}）次",
        f"工程名称：{meta.get('project', '＿＿＿＿')}　　　　报表编号：{meta.get('report_no', '＿＿＿＿')}",
        row3,
        (f"仪器型号：{meta.get('instrument_model', '＿＿＿＿')}　　"
         f"仪器编号：{meta.get('instrument_no', '＿＿＿＿')}　　"
         f"检定有效期：{meta.get('instrument_valid', '＿＿＿＿')}"),
        (f"本次监测时间：{meta.get('current_time', '＿＿＿＿')}　　　　"
         f"上次监测时间：{meta.get('previous_time', '＿＿＿＿')}"),
    ]


def _analysis_lines(sheet_key: str, rows: list[dict], unit: str) -> list[str]:
    """「简要分析及判断性结论」统计块（参考文档的数据区之后内容）。

    判定信息从 `row["_info"]` 读取（由 `write_appendix_sheet` 写回），**不按位置 zip**。
    """
    pts = sorted({r["pid"] for r in rows})
    dates = sorted({r["ts"].date() for r in rows if r.get("ts")})
    period = f"{dates[0]} ~ {dates[-1]}" if dates else "（未提供日期）"

    def info_of(r):
        return r.get("_info") or {}

    # 末次期次统计（每个测点取最后一行）
    last_of: dict[str, dict] = {}
    for r in rows:
        last_of[r["pid"]] = r
    cnt = defaultdict(int)
    for _pid, r in last_of.items():
        cnt[info_of(r).get("level", "")] += 1

    lines = [f"· 本附表共 {len(pts)} 个测点（{FAMILY_TITLE[sheet_key]}），监测期 {period}"]
    lines.append(
        "· 末次监测日统计："
        f"正常 {cnt.get('正常', 0) + cnt.get(vt.LEVEL_OK, 0)} 点、"
        f"需关注(黄色) {cnt.get('黄色预警', 0) + cnt.get(vt.LEVEL_YELLOW, 0)} 点、"
        f"报警(红色) {cnt.get('红色预警', 0) + cnt.get(vt.LEVEL_RED, 0)} 点、"
        f"未判定 {cnt.get('未判定(待复核)', 0) + cnt.get(vt.LEVEL_UNKNOWN, 0)} 点"
    )

    def _fmt_pts(sel, label):
        if not sel:
            return None
        items = []
        for r in sel:
            info = info_of(r)
            cum = _fmt(r.get("cumulative"))
            warn = info.get("warn_text") or "未知"
            items.append(f"{r['pid']} 累计 {cum} / 报警值 {warn}")
        return f"· {label}：" + "；".join(items)

    red = [r for r in rows if info_of(r).get("level") in ("红色预警", vt.LEVEL_RED)]
    yellow = [r for r in rows if info_of(r).get("level") in ("黄色预警", vt.LEVEL_YELLOW)]
    fast = [r for r in rows if r.get("rate") is not None and abs(r["rate"]) >= 2]
    sudden = [r for r in rows if info_of(r).get("rate_reasons")]
    blocked = [r for r in rows if info_of(r).get("sudden_blocked")]

    for sel, label in ((red, "红色报警测点（累计量已达/超报警值）"),
                       (yellow, "需关注(黄色)测点（累计≥报警值 70%）")):
        line = _fmt_pts(sel, label)
        if line:
            lines.append(line)
    if fast:
        items = "、".join(f"{r['pid']} {_fmt(abs(r['rate']))}" for r in fast)
        lines.append(f"· 变化速率较大（≥2 {unit}/天）的测点：{items}")
    if sudden:
        items = "；".join(f"{r['pid']}：{'；'.join(info_of(r)['rate_reasons'])}" for r in sudden)
        lines.append(f"· 速率口径判据触发：{items}")
    if blocked:
        items = "；".join(f"{r['pid']}：{info_of(r)['sudden_blocked']}" for r in blocked)
        lines.append(f"· 突变判据（第 8.0.9-1 条）本会触发但**未确认，已停用**：{items}"
                     f"　—— 该条阈值规范未定量，须由项目专项监测方案确认后加 --ack-sudden-factor 启用。")
    if red:
        lines.append("结论：存在红色报警测点，累计量已达或超过 GB 50497-2019 表 8.0.4 / 表 8.0.5 "
                     "报警值，须立即人工复核并按既有责任流程处置；本表不作预警发布。")
    elif yellow:
        lines.append("结论：本期无红色报警测点，存在需关注(黄色)测点，建议加密监测频率并核查坑边荷载。")
    else:
        lines.append("结论：本期各测点未见红色报警；判定阈值以项目专项监测方案为准，"
                     "标「未判定」者须转人工复核。")
    return lines


# ---------------------------------------------------------------------------
# 写 sheet
# ---------------------------------------------------------------------------
def write_appendix_sheet(ws, sheet_key: str, rows: list[dict], meta: dict,
                         lib: dict, *, limits=None, design=None,
                         safety_level: str = "一级", derived_note: str = "auto",
                         rate_rules_enabled: bool = True,
                         sudden_factor: float = 3.0,
                         sudden_ack: bool = False) -> list[dict]:
    from openpyxl.styles import Alignment, Border, Font, Side
    from openpyxl.utils import get_column_letter

    spec = SPEC[sheet_key]
    ncol = spec["ncol"]
    unit = FAMILY_UNIT[sheet_key]
    thin = Side(style="thin", color="FF999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for i, text in enumerate(_head_rows(sheet_key, meta), start=1):
        c = ws.cell(row=i, column=1, value=text)
        c.font = Font(size=10)
        c.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=ncol)

    for ci, name in enumerate(spec["header"], start=1):
        c = ws.cell(row=ROW_HEADER, column=ci, value=name)
        c.font = Font(bold=True, size=10)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border

    # 判定信息**写回行内**（`row["_info"]`），不再用平行列表按位置 zip —— 避免字段错位
    r = ROW_DATA
    for row in rows:
        info = resolve_row(row, lib, limits=limits, design=design,
                           safety_level=safety_level, unit=unit,
                           rate_rules_enabled=rate_rules_enabled,
                           sudden_factor=sudden_factor,
                           sudden_ack=sudden_ack)
        row["_info"] = info
        values = _row_values(spec["kind"], row, info, unit, derived_note)
        if len(values) != ncol:                      # 列数错位保护
            values = (values + ["—"] * ncol)[:ncol]
        for ci, v in enumerate(values, start=1):
            c = ws.cell(row=r, column=ci, value=v)
            c.font = Font(size=10)
            c.border = border
            if ci == ncol:
                c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            elif isinstance(v, (int, float)):
                c.alignment = Alignment(horizontal="right", vertical="center")
                c.number_format = "0.000"
            else:
                c.alignment = Alignment(horizontal="center", vertical="center")
        r += 1

    # 页脚
    foot = r + 1
    brief = "当日监测的简要分析及判断性结论" if sheet_key == "表F" else "简要分析及判断性结论"
    foot_lines = [
        f"工况描述：{meta.get('work_condition', '＿＿＿＿＿＿＿＿')}",
        f"{brief}：{meta.get('analysis', '＿＿＿＿＿＿＿＿')}",
        f"工程负责人：{meta.get('principal', '＿＿＿＿')}　　　　监测单位：{meta.get('unit_name', '＿＿＿＿')}",
        "第 　 页 共 　 页",
    ]
    for i, text in enumerate(foot_lines):
        c = ws.cell(row=foot + i, column=1, value=text)
        c.font = Font(size=10)
        c.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells(start_row=foot + i, start_column=1, end_row=foot + i, end_column=ncol)

    block = foot + len(foot_lines) + 1
    c = ws.cell(row=block, column=1, value="简要分析及判断性结论")
    c.font = Font(bold=True, size=10)
    ws.merge_cells(start_row=block, start_column=1, end_row=block, end_column=ncol)
    for i, text in enumerate(_analysis_lines(sheet_key, rows, unit), start=1):
        c = ws.cell(row=block + i, column=1, value=text)
        c.font = Font(size=10)
        c.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        ws.merge_cells(start_row=block + i, start_column=1, end_row=block + i, end_column=ncol)

    for ci, w in enumerate(spec["widths"], start=1):
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.freeze_panes = f"A{ROW_DATA}"
    return [row.get("_info", {}) for row in rows]
