"""Render and audit the report workbook/Markdown artifact bundle.

The module formats frozen facts only. It does not calculate monitoring values,
resolve thresholds, or change risk levels.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any
from uuid import UUID

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from report_adapter import canonical_json, cover_blocks, value_hash
from appendix_forms import APPENDIX_FORMS

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = REPO_ROOT / "var" / "report-artifacts"
FORM_TITLES = {
    "表A": "附表A_水平位移监测日报表",
    "表B": "附表B_深层水平位移监测日报表",
    "表C": "附表C_围护墙内力等监测日报表",
    "表D": "附表D_支撑轴力等监测日报表",
    "表E": "附表E_地下水位等监测日报表",
    "表F": "附表F_裂缝监测日报表",
}
RISK_FILLS = {
    "正常": "E2F0D9",
    "关注": "FFF2CC",
    "预警": "FCE4D6",
    "报警": "F8CBAD",
    "危险报警": "F4B084",
    "未知": "D9E1F2",
}
THIN = Side(style="thin", color="B7B7B7")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _display(value: Any) -> Any:
    if value is None or value == "":
        return "—"
    if isinstance(value, (dict, list)):
        return canonical_json(value)
    return value


def _markdown_cell(value: Any) -> str:
    displayed = _display(value)
    if isinstance(displayed, float):
        text = f"{displayed:.6f}".rstrip("0").rstrip(".")
    else:
        text = str(displayed)
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", "<br>")
    )


def _resolve_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(path)
    return current


def _new_sheet(header_row: int | None = None) -> dict[str, Any]:
    return {
        "cells": OrderedDict(),
        "merges": [],
        "header_row": header_row,
    }


def _put(
    sheet: dict[str, Any],
    row: int,
    column: int,
    value: Any,
    *,
    style: str = "body",
    fact_path: str | None = None,
) -> None:
    sheet["cells"][(row, column)] = {
        "value": _display(value),
        "style": style,
        "fact_path": fact_path,
    }


def _merge(
    sheet: dict[str, Any],
    row: int,
    start_column: int,
    end_column: int,
    value: Any,
    *,
    style: str,
) -> None:
    _put(sheet, row, start_column, value, style=style)
    sheet["merges"].append((row, start_column, row, end_column))


def _put_fact(
    sheet: dict[str, Any],
    payload: dict[str, Any],
    row: int,
    column: int,
    fact_path: str,
    *,
    style: str = "body",
) -> None:
    _put(
        sheet,
        row,
        column,
        _resolve_path(payload, fact_path),
        style=style,
        fact_path=fact_path,
    )


def _item_note(item: dict[str, Any]) -> str:
    parts = [f"监测项：{item.get('metric_name') or '未知'}",
             f"风险等级：{item.get('risk_level') or '未知'}",
             f"单位：{item.get('unit') or '未提供'}"]
    reasons = item.get("abstain_reasons") or item.get("abstain") or []
    if reasons:
        parts.append("待复核：" + "；".join(str(reason) for reason in reasons))
    flags = item.get("source_flags") or []
    if flags:
        parts.append("来源标记：" + "、".join(str(flag) for flag in flags))
    if item.get("unit") in (None, ""):
        parts.append("单位未在冻结载荷中唯一提供")
    return "；".join(parts)


def _form_row(
    form: str,
    item: dict[str, Any],
    payload: dict[str, Any],
    item_index: int,
) -> tuple[list[str], list[tuple[Any, str | None]]]:
    prefix = f"items.{item_index}"
    common = {
        "timestamp": (item.get("timestamp"), f"{prefix}.timestamp"),
        "point_id": (item.get("point_id"), f"{prefix}.point_id"),
        "metric_name": (item.get("metric_name"), f"{prefix}.metric_name"),
        "baseline": (item.get("baseline"), f"{prefix}.baseline"),
        "previous": (item.get("previous"), f"{prefix}.previous"),
        "current": (item.get("current"), f"{prefix}.current"),
        "single_change": (item.get("single_change"), f"{prefix}.single_change"),
        "cumulative": (item.get("cumulative"), f"{prefix}.cumulative"),
        "rate": (item.get("rate"), f"{prefix}.rate"),
        "risk_level": (item.get("risk_level"), f"{prefix}.risk_level"),
        "rule_id": (item.get("rule_id"), f"{prefix}.rule_id"),
    }
    unit = (item.get("unit"), None)
    note = (_item_note(item), None)
    blank = ("—", None)

    if form == "表A":
        return (
            ["监测时间", "点号", "监测项目", "累计变化", "本次变化", "变化速率", "单位", "风险等级", "规则ID", "备注"],
            [
                common["timestamp"],
                common["point_id"],
                common["metric_name"],
                common["cumulative"],
                common["single_change"],
                common["rate"],
                unit,
                common["risk_level"],
                common["rule_id"],
                note,
            ],
        )
    if form == "表B":
        return (
            ["监测时间", "孔号(点号)", "深度(m)", "监测项目", "累计位移", "本次变化", "变化速率", "单位", "风险等级", "备注"],
            [
                common["timestamp"],
                common["point_id"],
                blank,
                common["metric_name"],
                common["cumulative"],
                common["single_change"],
                common["rate"],
                unit,
                common["risk_level"],
                note,
            ],
        )
    if form in ("表C", "表D"):
        return (
            ["深度(m)", "本次测值", "上次测值", "本次变化", "累计变化", "单位", "组号", "点号", "监测项目", "风险等级", "备注"],
            [
                blank,
                common["current"],
                common["previous"],
                common["single_change"],
                common["cumulative"],
                unit,
                blank,
                common["point_id"],
                common["metric_name"],
                common["risk_level"],
                note,
            ],
        )
    if form == "表E":
        return (
            ["初始值", "本次值", "上次值", "本次变化", "累计变化", "变化速率", "单位", "编号", "点号", "监测项目", "风险等级", "备注"],
            [
                common["baseline"],
                common["current"],
                common["previous"],
                common["single_change"],
                common["cumulative"],
                common["rate"],
                unit,
                blank,
                common["point_id"],
                common["metric_name"],
                common["risk_level"],
                note,
            ],
        )

    metric = str(item.get("metric_name") or item.get("metric_key") or "").lower()
    is_length = "长度" in metric or "length" in metric
    is_width = "宽度" in metric or "width" in metric
    return (
        ["监测时间", "长度", "宽度", "本次测试值", "单次变化", "累计变化", "变化速率", "单位", "点号", "形态", "风险等级", "备注"],
        [
            common["timestamp"],
            common["current"] if is_length else blank,
            common["current"] if is_width else blank,
            common["current"],
            common["single_change"],
            common["cumulative"],
            common["rate"],
            unit,
            common["point_id"],
            blank,
            common["risk_level"],
            note,
        ],
    )


def _build_cover_sheet(
    report: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    sheet = _new_sheet()
    project = report["sections"]["project"]
    summary = report["sections"]["summary"]

    _merge(sheet, 1, 1, 8, report["title"], style="title")
    _merge(
        sheet,
        2,
        1,
        8,
        "系统辅助生成草稿，仅供工程师复核，不构成正式预警、审核或签发。",
        style="note",
    )
    labels = ("工程名称", "报告日期", "监测单位", "安全等级")
    paths = ("project.name", "project.report_date", "project.monitoring_unit", "project.safety_level")
    for offset, (label, path) in enumerate(zip(labels, paths)):
        column = offset * 2 + 1
        _put(sheet, 4, column, label, style="header")
        _put_fact(sheet, payload, 4, column + 1, path)

    _put(sheet, 5, 1, "开挖阶段", style="header")
    _put(sheet, 5, 2, project.get("excavation_stage"))
    _put(sheet, 5, 3, "支护类型", style="header")
    _put(sheet, 5, 4, project.get("support_type"))
    _put(sheet, 5, 5, "开挖深度(m)", style="header")
    _put(sheet, 5, 6, project.get("excavation_depth_m"))
    _put(sheet, 5, 7, "草稿状态", style="header")
    _put(sheet, 5, 8, report.get("status"))

    _merge(sheet, 7, 1, 8, "风险与数据质量汇总", style="section")
    summary_headers = (
        "整体风险等级",
        "条目数",
        "风险分布",
        "报警及以上",
        "待复核",
        "质量问题",
        "阻塞期次",
        "人工复核",
    )
    for column, label in enumerate(summary_headers, 1):
        _put(sheet, 8, column, label, style="header")
    _put_fact(sheet, payload, 9, 1, "summary.overall_risk_level", style="risk")
    _put_fact(sheet, payload, 9, 2, "summary.total")
    _put_fact(sheet, payload, 9, 3, "summary.by_risk_level")
    _put(sheet, 9, 4, len(payload.get("alerts") or []))
    _put(sheet, 9, 5, len(payload.get("review_queue") or []))
    _put_fact(sheet, payload, 9, 6, "data_quality.issue_count")
    _put_fact(sheet, payload, 9, 7, "data_quality.blocked_records")
    _put(sheet, 9, 8, "必须")

    row = 11
    for title, paragraphs in cover_blocks(report):
        _merge(sheet, row, 1, 8, title, style="section")
        row += 1
        for text in paragraphs:
            # Preserve every character while keeping long OCR clauses visible in Excel.
            for line in str(text).split("\n"):
                for offset in range(0, len(line), 240):
                    _merge(sheet, row, 1, 8, line[offset:offset + 240], style="body")
                    row += 1
        row += 1
    return sheet


def _build_form_sheets(
    report: dict[str, Any],
    payload: dict[str, Any],
) -> OrderedDict[str, dict[str, Any]]:
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    items = report["sections"]["monitoring_results"]["items"]
    for index, item in enumerate(items):
        form = item.get("appendix_form")
        if form in FORM_TITLES:
            grouped.setdefault(form, []).append((index, item))

    sheets: OrderedDict[str, dict[str, Any]] = OrderedDict()
    project = report["sections"]["project"]
    for form in FORM_TITLES:
        rows = grouped.get(form)
        if not rows:
            continue
        name = FORM_TITLES[form]
        template = APPENDIX_FORMS[form[-1]]
        headers = template["columns"]
        sheet = _new_sheet(header_row=6)
        for row, text in enumerate(template["header_lines"], 1):
            if row == 2:
                text = f"工程名称：{_display(project.get('name'))}　报表编号：＿＿＿＿（草稿）"
            if row == 5:
                text = f"本次监测日期：{_display(project.get('report_date'))}　上次监测时间：见冻结记录"
            _merge(sheet, row, 1, len(headers), text, style="title" if row == 1 else "body")
        for column, header in enumerate(headers, 1):
            _put(sheet, 6, column, header, style="header")
        selected_indices = {
            "表A": [0, 1, 3, 4, 5, 9],
            "表B": [0, 1, 2, 4, 5, 6, 9],
            "表C": [0, 1, 2, 3, 4, 6, 7, 10],
            "表D": [0, 1, 2, 3, 4, 6, 7, 10],
            "表E": [0, 1, 2, 3, 4, 5, 7, 8, 11],
            "表F": [1, 2, 3, 4, 5, 6, 8, 9, 11],
        }
        for row_number, (item_index, item) in enumerate(rows, 7):
            _headers, values = _form_row(form, item, payload, item_index)
            values = [values[index] for index in selected_indices[form]]
            if form == "表E":
                values[:3] = [("—", None)] * 3
                values[-1] = (str(values[-1][0]) + "；未提供高程基准，高程栏留空，原观测值见冻结明细。", None)
            for column, (value, fact_path) in enumerate(values, 1):
                _put(
                    sheet,
                    row_number,
                    column,
                    value,
                    style="body",
                    fact_path=fact_path,
                )
        footer_row = len(rows) + 8
        narrative = report["sections"].get("narrative") or {}
        form_analysis = next((item for item in narrative.get("appendix_analysis", [])
                              if item["form"] == form[-1]), None)
        work_condition = narrative.get("work_condition", {}).get("text") or report["sections"]["work_condition_analysis"]["work_condition"]
        analysis = form_analysis["analysis"]["text"] if form_analysis else "风险与弃权见逐测点备注；请工程师核对实测值与适用判据。"
        recommendation = form_analysis["recommendation"]["text"] if form_analysis else "对未知项补充资料后复核，对超限项核验现场情况；本表为草稿。"
        footer = [
            f"工况描述：{work_condition}",
            f"简要分析及判断性结论：{analysis}",
            f"复核建议：{recommendation}",
            f"工程负责人：＿＿＿＿　监测单位：{_display(project.get('monitoring_unit'))}",
            template["footer_lines"][-1],
        ]
        for text in footer:
            for line in text.split("\n"):
                for offset in range(0, len(line), 240):
                    _merge(sheet, footer_row, 1, len(headers), line[offset:offset + 240], style="note")
                    footer_row += 1
        sheet["data_end_row"] = len(rows) + 6
        sheets[name] = sheet
    return sheets


def _build_alert_sheet(
    report: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """超限测点清单 —— 对齐 GB 50497-2019 附录表式。"""
    headers = ["测点", "监测项目", "末次监测日期", "末次累计量", "单位", "报警值",
               "占报警值", "预警等级", "变化速率", "规范依据"]
    sheet = _new_sheet(header_row=1)
    for column, header in enumerate(headers, 1):
        _put(sheet, 1, column, header, style="header")
    alerts = payload.get("alerts") or []
    if not alerts:
        _merge(sheet, 2, 1, len(headers),
               "冻结载荷未列出报警及以上条目；未知项仍须查看封面三、待复核事项。",
               style="note")
        return sheet
    for row, alert in enumerate(alerts, 2):
        prefix = f"alerts.{row - 2}"
        checks = alert.get("checks") or []
        units = {str(check.get(key)).strip() for check in checks if isinstance(check, dict)
                 for key in ("unit", "value_unit", "limit_unit") if check.get(key) not in (None, "")}
        unit = next(iter(units)) if len(units) == 1 else "—"
        evidence = alert.get("evidence") if isinstance(alert.get("evidence"), dict) else {}
        cumulative = alert.get("cumulative")
        alarm_value = alert.get("limit_value") or alert.get("warning_value")
        # 占报警值百分比
        ratio_str = "—"
        if isinstance(cumulative, (int, float)) and isinstance(alarm_value, (int, float)) and alarm_value != 0:
            ratio_str = f"{round(cumulative / alarm_value * 100, 1)}%"
        values = [
            (alert.get("point_id"), f"{prefix}.point_id"),
            (alert.get("metric_name"), f"{prefix}.metric_name"),
            (alert.get("timestamp") or alert.get("date"), f"{prefix}.timestamp"),
            (cumulative, f"{prefix}.cumulative"),
            (unit, None),
            (alarm_value, f"{prefix}.limit_value" if alarm_value is not None else None),
            (ratio_str, None),
            (alert.get("risk_level"), f"{prefix}.risk_level"),
            (alert.get("rate"), f"{prefix}.rate"),
            (evidence.get("clause") or evidence.get("standard"), None),
        ]
        for column, (value, fact_path) in enumerate(values, 1):
            _put(sheet, row, column, value,
                 style="risk" if column == 8 else "body",
                 fact_path=fact_path)
    return sheet


def _build_review_sheet(
    report: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    headers = ["测点", "监测项目", "风险等级", "弃权码", "待复核原因", "来源标记"]
    sheet = _new_sheet(header_row=3)
    _merge(sheet, 1, 1, len(headers), "待复核事项与数据质量说明", style="title")
    for column, header in enumerate(headers, 1):
        _put(sheet, 3, column, header, style="header")
    reviews = payload.get("review_queue") or []
    row = 4
    for index, item in enumerate(reviews):
        prefix = f"review_queue.{index}"
        values = [
            (item.get("point_id"), f"{prefix}.point_id"),
            (item.get("metric_name"), f"{prefix}.metric_name"),
            (item.get("risk_level"), f"{prefix}.risk_level"),
            (item.get("abstain") or [], f"{prefix}.abstain"),
            (item.get("abstain_reasons") or [], f"{prefix}.abstain_reasons"),
            (item.get("source_flags") or [], f"{prefix}.source_flags"),
        ]
        for column, (value, fact_path) in enumerate(values, 1):
            _put(sheet, row, column, value, fact_path=fact_path)
        row += 1
    if not reviews:
        _merge(sheet, row, 1, len(headers), "冻结载荷没有引擎弃权条目。", style="note")
        row += 1
    _merge(
        sheet,
        row,
        1,
        len(headers),
        "巡视记录未提供；未生成附表G，不得据此判定巡视正常。",
        style="note",
    )
    row += 1
    for gap in report.get("review_gaps") or []:
        _merge(sheet, row, 1, len(headers), f"报告缺口：{gap}", style="note")
        row += 1
    quality = payload.get("data_quality") or {}
    _merge(
        sheet,
        row,
        1,
        len(headers),
        "数据质量："
        f"问题数={_display(quality.get('issue_count'))}；"
        f"阻塞期次={_display(quality.get('blocked_records'))}；"
        f"问题分布={_display(quality.get('by_code') or {})}",
        style="note",
    )
    return sheet


def _build_source_sheet(
    report: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    headers = ["测点", "监测项目", "量值语义", "来源标记", "源Sheet", "源列", "日内聚合统计",
               "初始观测值", "上次观测值", "本次观测值"]
    sheet = _new_sheet(header_row=5)
    _merge(sheet, 1, 1, len(headers), "来源与口径说明", style="title")
    _merge(
        sheet,
        2,
        1,
        len(headers),
        "来源标记和日内统计仅用于追溯；报告层未据此重算数值或改变风险等级。",
        style="note",
    )
    _merge(
        sheet,
        3,
        1,
        len(headers),
        "巡视记录未提供；附表G未生成。时间平移、重采样、插值或末值保持数据不得描述为原始同步实测。",
        style="note",
    )
    for column, header in enumerate(headers, 1):
        _put(sheet, 5, column, header, style="header")
    for row, item in enumerate(payload.get("items") or [], 6):
        index = row - 6
        prefix = f"items.{index}"
        metadata = item.get("source_metadata") if isinstance(item.get("source_metadata"), dict) else {}
        values = [
            (item.get("point_id"), f"{prefix}.point_id"),
            (item.get("metric_name"), f"{prefix}.metric_name"),
            (item.get("measurement_semantics"), f"{prefix}.measurement_semantics"),
            (item.get("source_flags") or [], f"{prefix}.source_flags"),
            (metadata.get("source_sheet"), None),
            (metadata.get("source_column"), None),
            (metadata.get("daily_aggregation") or {}, None),
            (item.get("baseline"), f"{prefix}.baseline"),
            (item.get("previous"), f"{prefix}.previous"),
            (item.get("current"), f"{prefix}.current"),
        ]
        for column, (value, fact_path) in enumerate(values, 1):
            _put(sheet, row, column, value, fact_path=fact_path)
    return sheet


def build_workbook_model(
    report: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    sheets: OrderedDict[str, dict[str, Any]] = OrderedDict()
    sheets["监测日报"] = _build_cover_sheet(report, payload)
    sheets.update(_build_form_sheets(report, payload))
    sheets["超限测点清单"] = _build_alert_sheet(report, payload)

    bindings: list[dict[str, str]] = []
    for sheet_name, sheet in sheets.items():
        for (row, column), cell in sheet["cells"].items():
            fact_path = cell.get("fact_path")
            if not fact_path:
                continue
            fact_value = _resolve_path(payload, fact_path)
            bindings.append(
                {
                    "artifact_kind": "workbook",
                    "location": f"{sheet_name}!{get_column_letter(column)}{row}",
                    "fact_path": fact_path,
                    "fact_value_hash": value_hash(fact_value),
                    "rendered_value_hash": value_hash(cell["value"]),
                }
            )
    return {"sheets": sheets, "bindings": bindings}


def _apply_style(cell: Any, style: str) -> None:
    cell.border = BORDER
    cell.alignment = Alignment(
        horizontal="center" if style in ("title", "header", "risk") else "left",
        vertical="center",
        wrap_text=True,
    )
    if style == "title":
        cell.font = Font(name="Microsoft YaHei", size=15, bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")
    elif style in ("header", "section"):
        cell.font = Font(name="Microsoft YaHei", size=10, bold=True)
        cell.fill = PatternFill("solid", fgColor="DDEBF7")
    elif style == "note":
        cell.font = Font(name="Microsoft YaHei", size=9, color="666666")
    else:
        cell.font = Font(name="Microsoft YaHei", size=10)


def _write_workbook(path: Path, model: dict[str, Any]) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name, spec in model["sheets"].items():
        worksheet = workbook.create_sheet(sheet_name)
        for row, start_column, end_row, end_column in spec["merges"]:
            worksheet.merge_cells(
                start_row=row,
                start_column=start_column,
                end_row=end_row,
                end_column=end_column,
            )
        max_column = 1
        for (row, column), cell_spec in spec["cells"].items():
            cell = worksheet.cell(row=row, column=column, value=cell_spec["value"])
            if isinstance(cell_spec["value"], str):
                cell.data_type = "s"
            elif isinstance(cell_spec["value"], float):
                cell.number_format = "0.######"
            _apply_style(cell, cell_spec["style"])
            if cell_spec["style"] == "risk":
                fill = RISK_FILLS.get(str(cell_spec["value"]))
                if fill:
                    cell.fill = PatternFill("solid", fgColor=fill)
            max_column = max(max_column, column)
        for row, start_column, end_row, end_column in spec["merges"]:
            for cells in worksheet.iter_rows(
                min_row=row,
                max_row=end_row,
                min_col=start_column,
                max_col=end_column,
            ):
                for cell in cells:
                    cell.border = BORDER
                    cell.alignment = Alignment(vertical="center", wrap_text=True)
            text = str(spec["cells"][(row, start_column)]["value"])
            worksheet.row_dimensions[row].height = min(
                400, max(24, 18 * (1 + len(text) // max(30, (end_column - start_column + 1) * 14)))
            )
        for column in range(1, max_column + 1):
            values = [
                str(cell_spec["value"])
                for (row, col), cell_spec in spec["cells"].items()
                if col == column and cell_spec["value"] not in (None, "")
            ]
            width = min(42, max(12, max((len(value) for value in values), default=10) + 2))
            worksheet.column_dimensions[get_column_letter(column)].width = width
        for (row, column), cell_spec in spec["cells"].items():
            if any(start_row == row for start_row, *_ in spec["merges"]):
                continue
            text = str(cell_spec["value"])
            width = worksheet.column_dimensions[get_column_letter(column)].width
            worksheet.row_dimensions[row].height = max(
                worksheet.row_dimensions[row].height or 24,
                min(140, 18 * (1 + len(text) // max(10, int(width / 2)))),
            )
        worksheet.sheet_view.showGridLines = False
        worksheet.freeze_panes = (
            f"A{spec['header_row'] + 1}" if spec.get("header_row") else "A4"
        )
        if spec.get("header_row"):
            worksheet.auto_filter.ref = (
                f"A{spec['header_row']}:"
                f"{get_column_letter(max_column)}{spec.get('data_end_row', worksheet.max_row)}"
            )
        worksheet.print_title_rows = (
            f"1:{spec['header_row']}" if spec.get("header_row") else "1:2"
        )
        worksheet.page_setup.orientation = "landscape"
        worksheet.page_setup.fitToWidth = 1
        worksheet.sheet_properties.pageSetUpPr.fitToPage = True
    workbook.properties.title = "ExcavaGuard 监测日报草稿"
    workbook.properties.creator = "ExcavaGuard"
    temporary = path.with_suffix(path.suffix + ".tmp")
    workbook.save(temporary)
    temporary.replace(path)


def render_appendices_markdown(model: dict[str, Any], report_date: Any) -> str:
    lines = [f"# 监测日报 · 附表及清单（{_markdown_cell(report_date)}）", ""]
    for sheet_name, spec in model["sheets"].items():
        if sheet_name == "监测日报":
            continue
        lines.extend([f"## {sheet_name}", ""])
        header_row = spec.get("header_row")
        if not header_row:
            continue
        max_column = max((column for _row, column in spec["cells"]), default=1)
        max_row = max((row for row, _column in spec["cells"]), default=header_row)
        headers = [
            spec["cells"].get((header_row, column), {"value": ""})["value"]
            for column in range(1, max_column + 1)
        ]
        for row in range(1, header_row):
            text = spec["cells"].get((row, 1), {}).get("value")
            if text:
                lines.extend([str(text), ""])
        lines.append("| " + " | ".join(_markdown_cell(value) for value in headers) + " |")
        lines.append("| " + " | ".join(["---"] * max_column) + " |")
        data_end = spec.get("data_end_row", max_row)
        for row in range(header_row + 1, data_end + 1):
            values = [
                spec["cells"].get((row, column), {"value": ""})["value"]
                for column in range(1, max_column + 1)
            ]
            if any(value not in (None, "") for value in values):
                lines.append("| " + " | ".join(_markdown_cell(value) for value in values) + " |")
        lines.append("")
        for row in range(data_end + 1, max_row + 1):
            text = spec["cells"].get((row, 1), {}).get("value")
            if text:
                lines.extend([str(text), ""])
    return "\n".join(lines).rstrip() + "\n"


def _safe_report_date(report: dict[str, Any]) -> str:
    raw = str(report["sections"]["project"].get("report_date") or "date-pending")
    return raw if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) else "date-pending"


def _artifact_names(report: dict[str, Any]) -> dict[str, str]:
    stem = f"监测日报_{_safe_report_date(report)}_草稿"
    return {
        "workbook": f"{stem}.xlsx",
        "cover_markdown": f"{stem}_封面.md",
        "appendices_markdown": f"{stem}_附表及清单.md",
    }


def _validate_output_dir(output_dir: str, artifact_id: str) -> Path:
    parsed_id = str(UUID(artifact_id))
    if parsed_id != artifact_id:
        raise ValueError("artifact_id 必须是标准小写 UUID。")
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    root = ARTIFACT_ROOT.resolve()
    target = Path(output_dir).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("报告产物目录必须位于 var/report-artifacts 下。") from exc
    if target.parent != root or target.name != artifact_id:
        raise ValueError("报告产物目录必须精确对应 draft artifact_id。")
    target.mkdir(parents=False, exist_ok=False)
    return target


def _write_text(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _descriptor(kind: str, path: Path, sheets: list[str]) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "kind": kind,
        "file_name": path.name,
        "relative_path": path.relative_to(REPO_ROOT).as_posix(),
        "media_type": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if kind == "workbook"
            else "text/markdown; charset=utf-8"
        ),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "sheets": sheets,
    }


def export_report_artifacts(
    report: dict[str, Any],
    payload: dict[str, Any],
    *,
    output_dir: str,
    artifact_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
    target = _validate_output_dir(output_dir, artifact_id)
    names = _artifact_names(report)
    model = build_workbook_model(report, payload)
    workbook_path = target / names["workbook"]
    cover_path = target / names["cover_markdown"]
    appendices_path = target / names["appendices_markdown"]

    _write_workbook(workbook_path, model)
    cover_markdown = str(report.get("markdown") or "")
    if not cover_markdown.endswith("\n"):
        cover_markdown += "\n"
    _write_text(cover_path, cover_markdown)
    _write_text(
        appendices_path,
        render_appendices_markdown(
            model,
            report["sections"]["project"].get("report_date"),
        ),
    )
    sheets = list(model["sheets"])
    artifacts = [
        _descriptor("workbook", workbook_path, sheets),
        _descriptor("cover_markdown", cover_path, []),
        _descriptor("appendices_markdown", appendices_path, []),
    ]
    return artifacts, model["bindings"], {
        "artifact_directory": target.relative_to(REPO_ROOT).as_posix(),
        "artifact_files": [artifact["relative_path"] for artifact in artifacts],
        "workbook_sheets": sheets,
        "artifact_binding_count": len(model["bindings"]),
    }


def _audit_issue(
    code: str,
    path: str,
    message: str,
    *,
    expected: Any = None,
    actual: Any = None,
) -> dict[str, Any]:
    issue = {"code": code, "path": path, "message": message}
    if expected is not None:
        issue["expected"] = expected
    if actual is not None:
        issue["actual"] = actual
    return issue


def _cell_values_equal(expected: Any, actual: Any) -> bool:
    if (
        isinstance(expected, (int, float))
        and not isinstance(expected, bool)
        and isinstance(actual, (int, float))
        and not isinstance(actual, bool)
    ):
        return math.isclose(
            float(expected),
            float(actual),
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    return canonical_json(expected) == canonical_json(actual)


def _artifact_file(
    artifact: dict[str, Any],
) -> tuple[Path | None, dict[str, Any] | None]:
    relative = artifact.get("relative_path")
    if not isinstance(relative, str):
        return None, _audit_issue(
            "ARTIFACT_PATH_INVALID",
            "artifacts",
            "产物相对路径缺失。",
        )
    root = ARTIFACT_ROOT.resolve()
    raw_candidate = REPO_ROOT / relative
    candidate = raw_candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None, _audit_issue(
            "ARTIFACT_PATH_INVALID",
            f"artifacts.{artifact.get('kind')}",
            "产物路径越出 var/report-artifacts。",
            actual=relative,
        )
    if raw_candidate.is_symlink() or not candidate.is_file():
        return None, _audit_issue(
            "ARTIFACT_FILE_MISSING",
            f"artifacts.{artifact.get('kind')}",
            "日报产物不存在或不是普通文件。",
            actual=relative,
        )
    return candidate, None


def audit_report_artifacts(
    report: dict[str, Any],
    payload: dict[str, Any],
    artifacts: Any,
    artifact_bindings: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not isinstance(artifacts, list) or not isinstance(artifact_bindings, list):
        return [
            _audit_issue(
                "ARTIFACT_MANIFEST_INVALID",
                "artifacts",
                "三件套清单或单元格绑定不是数组。",
            )
        ], {"checked_artifact_count": 0, "checked_artifact_binding_count": 0}

    by_kind = {
        artifact.get("kind"): artifact
        for artifact in artifacts
        if isinstance(artifact, dict) and isinstance(artifact.get("kind"), str)
    }
    expected_kinds = {"workbook", "cover_markdown", "appendices_markdown"}
    if set(by_kind) != expected_kinds or len(artifacts) != 3:
        issues.append(
            _audit_issue(
                "ARTIFACT_SET_MISMATCH",
                "artifacts",
                "日报草稿必须且只能包含固定三件套。",
                expected=sorted(expected_kinds),
                actual=sorted(by_kind),
            )
        )

    expected_names = _artifact_names(report)
    files: dict[str, Path] = {}
    for kind in expected_kinds:
        artifact = by_kind.get(kind)
        if not artifact:
            continue
        if artifact.get("file_name") != expected_names[kind]:
            issues.append(
                _audit_issue(
                    "ARTIFACT_NAME_MISMATCH",
                    f"artifacts.{kind}.file_name",
                    "产物文件名与报告日期不一致。",
                    expected=expected_names[kind],
                    actual=artifact.get("file_name"),
                )
            )
        path, path_issue = _artifact_file(artifact)
        if path_issue:
            issues.append(path_issue)
            continue
        if path is None:
            continue
        files[kind] = path
        content = path.read_bytes()
        actual_hash = hashlib.sha256(content).hexdigest()
        if artifact.get("sha256") != actual_hash:
            issues.append(
                _audit_issue(
                    "ARTIFACT_HASH_MISMATCH",
                    f"artifacts.{kind}.sha256",
                    "产物文件哈希与草稿清单不一致。",
                    expected=artifact.get("sha256"),
                    actual=actual_hash,
                )
            )
        if artifact.get("size_bytes") != len(content):
            issues.append(
                _audit_issue(
                    "ARTIFACT_SIZE_MISMATCH",
                    f"artifacts.{kind}.size_bytes",
                    "产物文件字节数与草稿清单不一致。",
                    expected=artifact.get("size_bytes"),
                    actual=len(content),
                )
            )

    model = build_workbook_model(report, payload)
    expected_bindings = model["bindings"]
    if canonical_json(artifact_bindings) != canonical_json(expected_bindings):
        issues.append(
            _audit_issue(
                "ARTIFACT_BINDING_SET_MISMATCH",
                "artifact_bindings",
                "Excel 单元格事实绑定集合不一致。",
                expected=value_hash(expected_bindings),
                actual=value_hash(artifact_bindings),
            )
        )

    workbook_path = files.get("workbook")
    if workbook_path:
        try:
            workbook = load_workbook(workbook_path, data_only=False, read_only=False)
        except Exception as exc:  # noqa: BLE001
            issues.append(
                _audit_issue(
                    "WORKBOOK_UNREADABLE",
                    "artifacts.workbook",
                    f"日报 Excel 无法读取：{exc}",
                )
            )
        else:
            expected_sheets = list(model["sheets"])
            if workbook.sheetnames != expected_sheets:
                issues.append(
                    _audit_issue(
                        "WORKBOOK_SHEET_MISMATCH",
                        "artifacts.workbook.sheets",
                        "Excel 工作表集合或顺序不一致。",
                        expected=expected_sheets,
                        actual=workbook.sheetnames,
                    )
                )
            for sheet_name, spec in model["sheets"].items():
                if sheet_name not in workbook.sheetnames:
                    continue
                worksheet = workbook[sheet_name]
                expected_cells = {
                    (row, column): cell["value"]
                    for (row, column), cell in spec["cells"].items()
                }
                actual_cells = {
                    (cell.row, cell.column): cell.value
                    for row in worksheet.iter_rows()
                    for cell in row
                    if cell.value not in (None, "")
                }
                for location in sorted(set(expected_cells) | set(actual_cells)):
                    expected_value = expected_cells.get(location)
                    actual_value = actual_cells.get(location)
                    if not _cell_values_equal(expected_value, actual_value):
                        coordinate = f"{get_column_letter(location[1])}{location[0]}"
                        issues.append(
                            _audit_issue(
                                "WORKBOOK_CELL_MISMATCH",
                                f"artifacts.workbook.{sheet_name}!{coordinate}",
                                "Excel 单元格与冻结事实的确定性渲染值不一致。",
                                expected=expected_value,
                                actual=actual_value,
                            )
                        )
            workbook.close()

    cover_path = files.get("cover_markdown")
    if cover_path:
        actual_cover = cover_path.read_text(encoding="utf-8")
        expected_cover = str(report.get("markdown") or "")
        if not expected_cover.endswith("\n"):
            expected_cover += "\n"
        if actual_cover != expected_cover:
            issues.append(
                _audit_issue(
                    "MARKDOWN_CONTENT_MISMATCH",
                    "artifacts.cover_markdown",
                    "封面 Markdown 与结构化草稿不一致。",
                    expected=value_hash(expected_cover),
                    actual=value_hash(actual_cover),
                )
            )

    appendices_path = files.get("appendices_markdown")
    if appendices_path:
        actual_appendices = appendices_path.read_text(encoding="utf-8")
        expected_appendices = render_appendices_markdown(
            model,
            report["sections"]["project"].get("report_date"),
        )
        if actual_appendices != expected_appendices:
            issues.append(
                _audit_issue(
                    "MARKDOWN_CONTENT_MISMATCH",
                    "artifacts.appendices_markdown",
                    "附表及清单 Markdown 与 Excel 模型不一致。",
                    expected=value_hash(expected_appendices),
                    actual=value_hash(actual_appendices),
                )
            )

    for kind, path in files.items():
        if kind == "workbook":
            continue
        text = path.read_text(encoding="utf-8")
        unsupported_patrol = any(
            "巡视正常" in line
            and not any(negation in line for negation in ("不得", "不能", "不可", "并非", "不代表"))
            for line in text.splitlines()
        )
        if unsupported_patrol:
            issues.append(
                _audit_issue(
                    "UNSUPPORTED_PATROL_CONCLUSION",
                    f"artifacts.{kind}",
                    "未提供巡视记录时不得写入“巡视正常”。",
                )
            )

    return issues, {
        "checked_artifact_count": len(files),
        "checked_artifact_binding_count": len(artifact_bindings),
        "expected_workbook_sheets": list(model["sheets"]),
    }
