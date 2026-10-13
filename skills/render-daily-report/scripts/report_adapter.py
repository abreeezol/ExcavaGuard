"""Adapt the frozen engine payload into an auditable report draft.

This module only copies and formats upstream facts. It must not calculate
monitoring values, change risk levels, or resolve thresholds.
"""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parents[2]
DEEP_REPORT_SCRIPTS = SKILLS_ROOT / "deep-pit-monitoring-report" / "scripts"
sys.path.insert(0, str(DEEP_REPORT_SCRIPTS))

from render_report import DEFAULT_FORM_MAP, pick_form  # noqa: E402

TEMPLATE_VERSION = "deep-pit-monitoring-report/service-v1"
ITEM_FACT_FIELDS = (
    "point_id",
    "point_name",
    "point_type",
    "metric_key",
    "metric_name",
    "timestamp",
    "data_origin",
    "baseline",
    "previous",
    "current",
    "interval_days",
    "cumulative",
    "single_change",
    "rate",
    "slope",
    "problem_category",
    "risk_level",
    "utilization",
    "checks",
    "effective_standard",
    "rule_id",
    "evidence",
    "abstain",
    "abstain_reasons",
    "flags",
    "needs_review",
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def value_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _display(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _cell(value: Any) -> str:
    return _display(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _unit_from_checks(checks: Any) -> str | None:
    units: list[str] = []
    if isinstance(checks, list):
        for check in checks:
            if not isinstance(check, dict):
                continue
            for key in ("unit", "value_unit", "limit_unit"):
                value = check.get(key)
                if isinstance(value, str) and value.strip() and value.strip() not in units:
                    units.append(value.strip())
    return units[0] if len(units) == 1 else None


def _extract_evidence(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict) and isinstance(payload.get("evidence"), list):
        candidates = payload["evidence"]
    else:
        return []
    return [
        deepcopy(item)
        for item in candidates
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
    ]


def _extract_analysis(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "insufficient",
            "work_condition": "信息不足，建议人工复核。",
            "limitations": ["未提供结构化工况分析。"],
        }
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    work_condition = (
        result.get("work_condition")
        or result.get("work_condition_analysis")
        or result.get("工况描述")
    )
    limitations = result.get("limitations") or result.get("局限性") or []
    if not isinstance(limitations, list):
        limitations = [str(limitations)]
    return {
        "status": result.get("status") or ("ready" if work_condition else "insufficient"),
        "work_condition": work_condition or "信息不足，建议人工复核。",
        "limitations": [str(item) for item in limitations],
    }


def _adapt_item(item: dict[str, Any]) -> dict[str, Any]:
    copied = {field: deepcopy(item.get(field)) for field in ITEM_FACT_FIELDS}
    copied["unit"] = _unit_from_checks(item.get("checks"))
    copied["appendix_form"] = pick_form(
        str(item.get("metric_name") or ""),
        DEFAULT_FORM_MAP,
    )
    return copied


def _binding(
    binding_id: str,
    report_path: str,
    fact_path: str,
    value: Any,
) -> dict[str, str]:
    return {
        "binding_id": binding_id,
        "report_path": report_path,
        "fact_path": fact_path,
        "fact_value_hash": value_hash(value),
    }


def _markdown(report: dict[str, Any]) -> str:
    sections = report["sections"]
    project = sections["project"]
    summary = sections["summary"]
    lines = [
        f"# {_cell(project.get('name'))}监测日报（草稿）",
        "",
        "> 本报告由系统辅助生成，仅供工程师复核，不构成正式预警、审核或签发。",
        "",
        "## 工程概况",
        "",
        "| 工程名称 | 报告日期 | 监测单位 | 安全等级 | 开挖阶段 |",
        "| --- | --- | --- | --- | --- |",
        "| %s | %s | %s | %s | %s |"
        % (
            _cell(project.get("name")),
            _cell(project.get("report_date")),
            _cell(project.get("monitoring_unit")),
            _cell(project.get("safety_level")),
            _cell(project.get("excavation_stage")),
        ),
        "",
        "## 结论概述",
        "",
        f"- 整体风险等级：{_cell(summary.get('overall_risk_level'))}",
        f"- 判定条目数：{_cell(summary.get('total'))}",
        f"- 风险分布：{_cell(canonical_json(summary.get('by_risk_level') or {}))}",
        "",
        "## 逐测点成果",
        "",
        "| 附表 | 测点 | 监测项 | 时间 | 本次值 | 本次变化 | 累计变化 | 变化速率 | 单位 | 风险等级 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in sections["monitoring_results"]["items"]:
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
            % (
                _cell(item.get("appendix_form")),
                _cell(item.get("point_id")),
                _cell(item.get("metric_name")),
                _cell(item.get("timestamp")),
                _cell(item.get("current")),
                _cell(item.get("single_change")),
                _cell(item.get("cumulative")),
                _cell(item.get("rate")),
                _cell(item.get("unit")),
                _cell(item.get("risk_level")),
            )
        )

    lines += ["", "## 报警清单", ""]
    alerts = sections["alerts"]["items"]
    if alerts:
        lines += [
            "| 测点 | 监测项 | 风险等级 | 规则 ID |",
            "| --- | --- | --- | --- |",
        ]
        for item in alerts:
            lines.append(
                "| %s | %s | %s | %s |"
                % (
                    _cell(item.get("point_id")),
                    _cell(item.get("metric_name")),
                    _cell(item.get("risk_level")),
                    _cell(item.get("rule_id")),
                )
            )
    else:
        lines.append("- 本期无“报警”或“危险报警”条目。")

    lines += ["", "## 待复核事项", ""]
    reviews = sections["review_queue"]["items"]
    if reviews:
        for item in reviews:
            reasons = item.get("abstain_reasons") or item.get("abstain") or ["信息不足"]
            lines.append(
                "- %s / %s：%s"
                % (
                    _cell(item.get("point_id")),
                    _cell(item.get("metric_name")),
                    _cell("；".join(str(reason) for reason in reasons)),
                )
            )
    else:
        lines.append("- 无引擎弃权条目。")
    for gap in report["review_gaps"]:
        lines.append(f"- {_cell(gap)}")

    lines += [
        "",
        "## 数据质量说明",
        "",
        f"- 问题数：{_cell(sections['data_quality'].get('issue_count'))}",
        f"- 被阻塞期次数：{_cell(sections['data_quality'].get('blocked_records'))}",
        f"- 问题分布：{_cell(canonical_json(sections['data_quality'].get('by_code') or {}))}",
        "",
        "## 工况分析",
        "",
        _cell(sections["work_condition_analysis"].get("work_condition")),
        "",
        "## 规范证据",
        "",
    ]
    evidence = sections["standard_evidence"]["items"]
    if evidence:
        for item in evidence:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            lines.append(
                "- [%s] %s %s：%s"
                % (
                    _cell(item.get("id")),
                    _cell(metadata.get("standard_version") or metadata.get("standard_name")),
                    _cell(metadata.get("clause")),
                    _cell(item.get("text")),
                )
            )
    else:
        lines.append("- 未附加在线规范证据；不得据此补造规范性解释。")

    warnings = sections["standard_override_warnings"]
    if warnings:
        lines += ["", "## 用户规范宽松提示", ""]
        lines.append(
            f"- 检出 {len(warnings)} 项用户阈值宽松差异，须由工程师逐项复核。"
        )

    lines += [
        "",
        "## 签署",
        "",
        "编制：＿＿＿＿　　审核：＿＿＿＿　　签发：＿＿＿＿（均须人工填写）",
        "",
        "## 使用边界",
        "",
        _cell(sections["disclaimer"]),
        "",
    ]
    return "\n".join(lines)


def build_report(
    daily_report_input: dict[str, Any],
    evidence_payload: Any = None,
    analysis_payload: Any = None,
    template_version: str = TEMPLATE_VERSION,
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    items = [_adapt_item(item) for item in daily_report_input.get("items", [])]
    evidence = _extract_evidence(evidence_payload)
    analysis = _extract_analysis(analysis_payload)
    project = deepcopy(daily_report_input.get("project") or {})
    summary = deepcopy(daily_report_input.get("summary") or {})
    review_gaps: list[str] = []

    for field, label in (
        ("name", "工程名称"),
        ("report_date", "报告日期"),
        ("monitoring_unit", "监测单位"),
    ):
        if project.get(field) in (None, ""):
            review_gaps.append(f"{label}缺失，模板中保留待填写。")
    missing_units = sum(1 for item in items if item.get("unit") is None)
    if missing_units:
        review_gaps.append(
            f"{missing_units} 条明细未在冻结载荷中提供可唯一识别的单位，已显示为“—”。"
        )

    report = {
        "schema": "excavaguard.report_payload/v1",
        "template_version": template_version,
        "status": "draft",
        "title": f"{project.get('name') or '待填写工程'}监测日报（草稿）",
        "sections": {
            "project": project,
            "summary": summary,
            "monitoring_results": {"items": items},
            "alerts": {"items": deepcopy(daily_report_input.get("alerts") or [])},
            "review_queue": {
                "items": deepcopy(daily_report_input.get("review_queue") or [])
            },
            "data_quality": deepcopy(daily_report_input.get("data_quality") or {}),
            "work_condition_analysis": analysis,
            "standard_evidence": {"items": evidence},
            "standard_override_warnings": deepcopy(
                daily_report_input.get("standard_override_warnings") or []
            ),
            "disclaimer": daily_report_input.get("disclaimer") or "",
        },
        "review_gaps": review_gaps,
        "review_required": True,
    }
    report["markdown"] = _markdown(report)

    bindings = [
        _binding("fact-project", "sections.project", "project", project),
        _binding("fact-summary", "sections.summary", "summary", summary),
        _binding(
            "fact-alerts",
            "sections.alerts.items",
            "alerts",
            daily_report_input.get("alerts") or [],
        ),
        _binding(
            "fact-review-queue",
            "sections.review_queue.items",
            "review_queue",
            daily_report_input.get("review_queue") or [],
        ),
        _binding(
            "fact-data-quality",
            "sections.data_quality",
            "data_quality",
            daily_report_input.get("data_quality") or {},
        ),
        _binding(
            "fact-standard-warnings",
            "sections.standard_override_warnings",
            "standard_override_warnings",
            daily_report_input.get("standard_override_warnings") or [],
        ),
        _binding(
            "fact-disclaimer",
            "sections.disclaimer",
            "disclaimer",
            daily_report_input.get("disclaimer") or "",
        ),
    ]
    for index, source_item in enumerate(daily_report_input.get("items") or []):
        for field in ITEM_FACT_FIELDS:
            bindings.append(
                _binding(
                    f"fact-item-{index}-{field.replace('_', '-')}",
                    f"sections.monitoring_results.items.{index}.{field}",
                    f"items.{index}.{field}",
                    source_item.get(field),
                )
            )

    citations = [
        {
            "citation_id": f"citation-{index + 1}",
            "report_path": f"sections.standard_evidence.items.{index}",
            "evidence_id": item["id"],
        }
        for index, item in enumerate(evidence)
    ]
    trace = {
        "template_version": template_version,
        "item_count": len(items),
        "alert_count": len(daily_report_input.get("alerts") or []),
        "review_count": len(daily_report_input.get("review_queue") or []),
        "evidence_ids": [item["id"] for item in evidence],
        "review_gaps": review_gaps,
        "calculation_performed": False,
        "risk_reclassified": False,
    }
    return report, bindings, citations, trace
