"""Adapt the frozen engine payload into an auditable report draft.

This module only copies and formats upstream facts. It must not calculate
monitoring values, change risk levels, or resolve thresholds.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parents[2]
DEEP_REPORT_SCRIPTS = SKILLS_ROOT / "deep-pit-monitoring-report" / "scripts"
sys.path.insert(0, str(DEEP_REPORT_SCRIPTS))

from render_report import DEFAULT_FORM_MAP  # noqa: E402

TEMPLATE_VERSION = "deep-pit-monitoring-report/service-v4"
ITEM_FACT_FIELDS = (
    "point_id",
    "point_name",
    "point_type",
    "metric_key",
    "metric_name",
    "timestamp",
    "data_origin",
    "measurement_semantics",
    "source_flags",
    "source_metadata",
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


def _narrative(payload: Any, engine: dict[str, Any], forms: list[str]) -> tuple[dict, dict]:
    """Validate and deterministically resolve model text; no model-authored numbers."""
    if not isinstance(payload, dict) or payload.get("schema") != "excavaguard.report_narrative/v1":
        return {}, {}
    raw = payload.get("narrative")
    if not isinstance(raw, dict) or set(raw) != {
        "work_condition", "analysis", "recommendations", "limitations", "appendix_analysis"
    }:
        raise ValueError("INVALID_NARRATIVE：模型正文结构不合法。")
    facts = {}

    def resolve(path):
        parts = path.split(".")
        allowed = ("project", "summary", "context", "data_quality", "standard_override_warnings", "period")
        if parts[0] not in allowed and not (
            len(parts) >= 3 and parts[0] == "items" and parts[1].isdigit()
            and parts[2] in {
                "point_id", "metric_name", "timestamp", "measurement_semantics",
                "current", "cumulative", "single_change",
                "rate", "slope", "risk_level", "abstain", "abstain_reasons",
                "source_flags", "rule_id", "checks", "evidence",
                "utilization", "problem_category", "needs_review"
            }
        ):
            raise ValueError("UNGROUNDED_FACT：不允许的事实路径。")
        value = engine
        try:
            for part in parts:
                value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError("UNGROUNDED_FACT：事实路径不存在。") from exc
        if isinstance(value, list) and all(item is None or isinstance(item, (str, int, float, bool)) for item in value):
            value = "、".join(_display(item) for item in value if item is not None)
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError("UNGROUNDED_FACT：正文只能引用标量事实。")
        facts[path] = deepcopy(value)
        return _display(value)

    def paragraph(item):
        if not isinstance(item, dict) or set(item) != {"text", "evidence_ids"}:
            raise ValueError("INVALID_NARRATIVE：段落结构不合法。")
        text = item["text"]
        ids = item["evidence_ids"]
        if (
            not isinstance(text, str) or not text.strip() or len(text) > 1800
            or not isinstance(ids, list) or len(ids) > 12
            or any(not isinstance(eid, str) or not 1 <= len(eid) <= 200 for eid in ids)
        ):
            raise ValueError("INVALID_NARRATIVE：段落内容不合法。")
        stripped = re.sub(r"\{\{fact:([^{}]+)\}\}", "", text)
        if re.search(r"[0-9{}]", stripped) or any(word in stripped for word in (
            "已正式签发", "已自动发布预警", "原因已经确认", "无需人工复核"
        )):
            raise ValueError("UNGROUNDED_FACT：未绑定的数字或越界责任措辞。")
        resolved = re.sub(r"\{\{fact:([^{}]+)\}\}", lambda match: resolve(match[1]), text)
        return {"text": resolved, "evidence_ids": ids}

    result = {"work_condition": paragraph(raw["work_condition"])}
    for field in ("analysis", "recommendations", "limitations"):
        if not isinstance(raw[field], list) or not 1 <= len(raw[field]) <= 8:
            raise ValueError("INVALID_NARRATIVE：正文段落数量不合法。")
        result[field] = [paragraph(item) for item in raw[field]]
    appendices = raw["appendix_analysis"]
    if (
        not isinstance(appendices, list)
        or any(not isinstance(item, dict) or set(item) != {"form", "analysis", "recommendation"}
               for item in appendices)
        or sorted(item.get("form", "") for item in appendices) != forms
    ):
        raise ValueError("APPENDIX_ANALYSIS_MISMATCH：表式分析不完整。")
    result["appendix_analysis"] = [
        {"form": item["form"], "analysis": paragraph(item["analysis"]),
         "recommendation": paragraph(item["recommendation"])}
        for item in appendices
    ]
    return result, facts


FORM_NAMES = {"A": "水平位移", "B": "深层水平位移", "C": "围护墙内力等", "D": "支撑轴力等", "E": "地下水位等", "F": "裂缝"}
RISK_ORDER = ["危险报警", "报警", "预警", "关注", "正常", "未知"]


def _form_analysis(items: list[dict[str, Any]]) -> list[str]:
    """按附表统计风险分布，对齐 gold standard 的分项分析格式。"""
    grouped: dict[str, dict[str, int]] = {}
    for item in items:
        form = item.get("appendix_form")
        if not form or form[-1] not in FORM_NAMES:
            continue
        key = form[-1]
        level = str(item.get("risk_level") or "未知")
        grouped.setdefault(key, {}).setdefault(level, 0)
        grouped[key][level] += 1
    result = []
    for form_key in sorted(grouped):
        name = FORM_NAMES.get(form_key, form_key)
        dist = grouped[form_key]
        parts = [f"{level} {dist.get(level, 0)} 点" for level in RISK_ORDER if dist.get(level, 0) > 0]
        result.append(f"· {name}：{'、'.join(parts)}。")
    return result


def _standard_basis_summary(items: list[dict[str, Any]]) -> str:
    bases: list[str] = []
    for item in items:
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        effective = item.get("effective_standard") if isinstance(item.get("effective_standard"), dict) else {}
        standard = (
            evidence.get("standard")
            or effective.get("source_label")
            or effective.get("source_id")
        )
        clause = evidence.get("clause")
        parts = [
            str(value).strip()
            for value in (standard, clause)
            if value not in (None, "") and str(value).strip()
        ]
        if len(parts) == 2 and parts[1] in parts[0]:
            parts.pop()
        basis = " ".join(parts)
        if basis and basis not in bases:
            bases.append(basis)
    if not bases:
        return "规范依据：未匹配到可唯一展示的适用规范，相关条目已进入待复核。"
    shown = "、".join(bases[:6])
    suffix = f"等 {len(bases)} 项" if len(bases) > 6 else ""
    return f"规范依据：{shown}{suffix}；具体来源与适用条件见第四节及附表备注。"


def _review_items(report: dict[str, Any]) -> list[str]:
    """提取逐测点待复核摘要，不依赖独立 sheet。"""
    items = report["sections"]["monitoring_results"]["items"]
    review_items = [item for item in items if item.get("risk_level") == "未知" or item.get("needs_review") or item.get("abstain")]
    if not review_items:
        return ["无引擎弃权条目。"]
    result = []
    for item in review_items[:40]:
        reasons = item.get("abstain_reasons") or item.get("abstain") or []
        reason_str = "；".join(str(r) for r in reasons[:3]) if reasons else "原因未记录"
        result.append(
            f"{_display(item.get('point_id'))}｜{_display(item.get('metric_name'))}｜"
            f"风险={_display(item.get('risk_level'))}｜{reason_str}"
        )
    if len(review_items) > 40:
        result.append(f"… 另有 {len(review_items) - 40} 条，详见冻结载荷。")
    return result


def cover_blocks(report: dict[str, Any]) -> list[tuple[str, list[str]]]:
    sections = report["sections"]
    summary = sections["summary"]
    narrative = sections.get("narrative") or {}
    items = sections["monitoring_results"]["items"]

    def lines(field):
        return [item["text"] + (
            "\n引用证据：" + "、".join(item["evidence_ids"]) if item["evidence_ids"] else ""
        ) for item in narrative.get(field, [])]

    # --- 第一节：工况描述 ---
    condition_text = narrative.get("work_condition", {}).get("text") or sections["work_condition_analysis"]["work_condition"]
    condition_lines = [condition_text]
    condition_lines.append(_standard_basis_summary(items))
    project = sections["project"]
    period = sections.get("period")
    if period:
        condition_lines += [f"报告区间：{period['start_date']} 至 {period['end_date']}（含首尾日，{period['timezone']}）。",
                            "附表展示每通道周期最严重原观测，保留其实际日期，不代表期末值。"]
    condition_lines.append(
        f"工程名称：{_display(project.get('name'))}｜监测单位：{_display(project.get('monitoring_unit'))}｜"
        f"安全等级：{_display(project.get('safety_level'))}｜"
        f"开挖深度：{_display(project.get('excavation_depth_m'))}m"
    )

    # --- 第二节：简要分析及判断性结论 ---
    by_level = summary.get("by_risk_level") or {}
    overall = _display(summary.get("overall_risk_level"))
    analysis = [
        f"本期综合判定：{overall}。{'周期代表通道' if period else '当日判定条目'}共 {_display(summary.get('total'))} 条。",
        "风险分布：" + "；".join(f"{key}={value}" for key, value in by_level.items()),
        "分析范围：" + ("正文来自冻结模型分析，独立审计结果见运行记录。" if narrative else "确定性模板，未调用报告 LLM。"),
        "",
        "按附表分项统计：",
    ] + _form_analysis(items) + [""] + lines("analysis")
    if narrative:
        analysis += ["复核建议："] + lines("recommendations")
    else:
        analysis += ["请工程师对报警及以上项核验实测值、判据和现场工况；未知项应先补齐判定资料。"]
    if period:
        analysis += [f"区间日历天数：{period['calendar_days']}；有观测日期：{period['observed_days']}；"
                     f"明细观测：{period['observation_count']}；预警及以上点日：{period['warning_point_days']}。",
                     "缺测日期：" + ("、".join(period['missing_dates']) or "无整日缺测；逐通道缺口见周期统计。"),
                     f"未知观测：{period['unknown_observation_count']}；未知与缺测不能解释为安全。",
                     "每日变化、各通道覆盖及多日预警详见周期统计和逐日明细。"]
    abs_codes = summary.get("abstain") or {}
    if abs_codes:
        analysis.append("弃权统计：" + "；".join(f"{code}: {count} 条" for code, count in abs_codes.items()))

    # --- 第三节：待复核事项 ---
    abstain_items = _review_items(report)
    reviews = []
    if abstain_items and abstain_items != ["无引擎弃权条目。"]:
        reviews = ["以下测点需人工复核："] + abstain_items + [""]
    reviews += list(report["review_gaps"]) + lines("limitations")
    reviews.append("巡视记录未提供；未生成附表G，不得据此判定巡视正常。")
    if sections["standard_override_warnings"]:
        reviews += ["用户阈值宽松提示：以下差异必须由工程师逐项复核。"] + [
            canonical_json(item) for item in sections["standard_override_warnings"]
        ]
    reviews += [
        f"数据质量问题：{_display(sections['data_quality'].get('issue_count'))} 项；"
        f"阻塞期次：{_display(sections['data_quality'].get('blocked_records'))}。"
    ]

    # --- 第四节：规范核对依据（RAG知识库检索）---
    evidence = []
    standard_evidence = sections["standard_evidence"]
    ev_items = standard_evidence.get("items") or []
    # 按 metadata.clause 聚合展示
    for item in ev_items:
        metadata = item.get("metadata") or {}
        source = f"{metadata.get('standard_name', '')} {metadata.get('standard_version', '')} {metadata.get('clause', '')}".strip()
        evidence.append(
            f"《{source}》（Provider: {item.get('provider', '未提供')}）\n"
            f"来源：{metadata.get('source_location', '')}\n"
            f"原文：\n{item.get('text', '')}"
        )
    gaps = standard_evidence.get("gaps") or []
    if gaps:
        evidence += ["检索缺口："] + [str(g) for g in gaps]
    if not evidence:
        evidence = ["未附加本次 RAG 规范条文；不得补造规范性解释。"]
    extended = standard_evidence.get("extended_review")
    if extended:
        evidence += ["多日预警追加规范核查：" + str(extended.get("status")), str(extended.get("notice", ""))]
        for check in extended.get("checks", []):
            evidence += [f"{check.get('group')}：新增候选证据ID " + ("、".join(check.get("additional_evidence_ids", [])) or "未发现额外命中，仍需人工核查。")]
    evidence += ["判定口径：累计量占比 正常<70% 报警值；需关注(黄) 70%~100%；报警(红) ≥100%。"]
    evidence += ["数值与风险判据来自冻结确定性规范库；上述 RAG 为本次检索的条文候选，适用性由工程师复核。"]

    # --- 第五节：签署 ---
    signing = [
        "监测人：＿＿＿＿　计算人：＿＿＿＿　校核人：＿＿＿＿",
        "审核人：＿＿＿＿　项目负责人：＿＿＿＿",
        "（均为人工填写）",
        sections["disclaimer"],
    ]
    return [
        ("一、工况描述", condition_lines),
        ("二、简要分析及判断性结论", analysis),
        ("三、待复核事项", reviews),
        ("四、规范核对依据（RAG知识库检索）", evidence),
        ("五、签署", signing),
    ]


def _appendix_form(metric_name: str) -> str | None:
    for form in DEFAULT_FORM_MAP.get("order", []):
        if any(
            keyword and keyword in metric_name
            for keyword in DEFAULT_FORM_MAP.get("rules", {}).get(form, [])
        ):
            return form
    return None


def _adapt_item(item: dict[str, Any]) -> dict[str, Any]:
    copied = {field: deepcopy(item.get(field)) for field in ITEM_FACT_FIELDS}
    copied["unit"] = _unit_from_checks(item.get("checks"))
    copied["appendix_form"] = _appendix_form(str(item.get("metric_name") or ""))
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
    forms = sorted({item["appendix_form"][-1] for item in items if item["appendix_form"]})
    narrative, narrative_facts = _narrative(analysis_payload, daily_report_input, forms)
    evidence_ids = {item["id"] for item in evidence}
    if narrative:
        paragraphs = [narrative["work_condition"]] + sum(
            [narrative[field] for field in ("analysis", "recommendations", "limitations")], []
        ) + [part for item in narrative["appendix_analysis"] for part in (item["analysis"], item["recommendation"])]
        if any(eid not in evidence_ids for part in paragraphs for eid in part["evidence_ids"]):
            raise ValueError("UNGROUNDED_CITATION：引用不存在的证据。")
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
    unmapped_forms = sum(1 for item in items if item.get("appendix_form") is None)
    if unmapped_forms:
        review_gaps.append(
            f"{unmapped_forms} 条明细无法无歧义映射到附表 A～F，"
            "未写入附表并保留在待复核及来源说明中。"
        )
    source_flags = sorted(
        {
            str(flag)
            for item in items
            for flag in (item.get("source_flags") or [])
            if str(flag).strip()
        }
    )
    if source_flags:
        review_gaps.append(
            "本期数据含来源或预处理限制，详见来源说明："
            + "、".join(source_flags)
            + "。"
        )

    period = deepcopy(daily_report_input.get("period"))
    report_label = period["label"] if period else "监测日报"
    if period:
        review_gaps.append(daily_report_input.get("note", ""))
        if period["missing_dates"]:
            review_gaps.append("报告区间存在整日缺测，不得推定缺测日期正常。")
    report = {
        "schema": "excavaguard.report_payload/v1",
        "template_version": template_version,
        "status": "draft",
        "title": f"{project.get('name') or '待填写工程'}{report_label}（草稿）",
        "report_label": report_label,
        "sections": {
            "project": project,
            "summary": summary,
            **({"period": period} if period else {}),
            "monitoring_results": {"items": items},
            "alerts": {"items": deepcopy(daily_report_input.get("alerts") or [])},
            "review_queue": {
                "items": deepcopy(daily_report_input.get("review_queue") or [])
            },
            "data_quality": deepcopy(daily_report_input.get("data_quality") or {}),
            "work_condition_analysis": analysis,
            "standard_evidence": {
                "items": evidence,
                "gaps": deepcopy(evidence_payload.get("gaps") or []) if isinstance(evidence_payload, dict) else [],
                **({"extended_review": deepcopy(evidence_payload["extended_review"])} if isinstance(evidence_payload, dict) and evidence_payload.get("extended_review") else {}),
            },
            "narrative": narrative,
            "narrative_facts": [{"path": path, "value": value} for path, value in narrative_facts.items()],
            "standard_override_warnings": deepcopy(
                daily_report_input.get("standard_override_warnings") or []
            ),
            "disclaimer": daily_report_input.get("disclaimer") or "",
        },
        "review_gaps": review_gaps,
        "review_required": True,
    }
    lines = [f"# {report['title']}", "", "> 系统辅助生成草稿，仅供工程师复核。", "",
             f"工程名称：{_display(project.get('name'))}　报告日期：{_display(project.get('report_date'))}",
             f"监测单位：{_display(project.get('monitoring_unit'))}　安全等级：{_display(project.get('safety_level'))}", ""]
    for title, paragraphs in cover_blocks(report):
        lines += [f"## {title}", ""]
        for text in paragraphs:
            lines += [text, ""]
    report["markdown"] = "\n".join(lines)

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
    if period:
        bindings.append(_binding("fact-period", "sections.period", "period", period))
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

    for index, (path, value) in enumerate(narrative_facts.items()):
        # Text substitution is independently rebuilt; scalar bindings remain machine-auditable.
        bindings.append(_binding(
            f"narrative-fact-{index}", f"sections.narrative_facts.{index}.value", path, value
        ))

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
