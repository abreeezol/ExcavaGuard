#!/usr/bin/env python3
"""Independent deterministic audit for a render-daily-report draft."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
RENDER_SCRIPTS = REPO_ROOT / "skills" / "render-daily-report" / "scripts"
sys.path.insert(0, str(RENDER_SCRIPTS))
sys.path.insert(0, str(REPO_ROOT / "确定性计算层" / "tools"))

from report_adapter import build_report, canonical_json, value_hash  # noqa: E402
from validate_daily_report_input import validate  # noqa: E402

RESULT_SCHEMA = "excavaguard.skill_result/v1"
SKILL = "validate-report"
REQUIRED_SECTIONS = (
    "project",
    "summary",
    "monitoring_results",
    "alerts",
    "review_queue",
    "data_quality",
    "work_condition_analysis",
    "standard_evidence",
    "standard_override_warnings",
    "disclaimer",
)
DEFAULT_PROHIBITED_PHRASES = (
    "已正式签发",
    "已自动发布预警",
    "原因已经确认",
    "无需人工复核",
)


def emit(body: dict) -> None:
    print(json.dumps(body, ensure_ascii=False, separators=(",", ":")))


def fail(code: str, message: str) -> int:
    emit(
        {
            "schema": RESULT_SCHEMA,
            "skill": SKILL,
            "ok": False,
            "error": {"code": code, "message": message},
        }
    )
    return 2


def resolve_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, list):
            if not part.isdigit():
                raise KeyError(path)
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(path)
    return current


def issue(
    code: str,
    path: str,
    message: str,
    *,
    responsibility: str = "report-delivery",
    expected: Any = None,
    actual: Any = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": code,
        "severity": "error",
        "blocking": True,
        "responsibility": responsibility,
        "path": path,
        "message": message,
    }
    if expected is not None:
        body["expected"] = expected
    if actual is not None:
        body["actual"] = actual
    return body


def main() -> int:
    try:
        request = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return fail("INVALID_INPUT", "请求体不是有效 JSON。")
    if not isinstance(request, dict):
        return fail("INVALID_INPUT", "请求体必须是对象。")

    payload = request.get("daily_report_input")
    report = request.get("report_payload")
    bindings = request.get("fact_bindings")
    artifacts = request.get("artifacts")
    artifact_bindings = request.get("artifact_bindings")
    citations = request.get("citations")
    if not isinstance(payload, dict) or not isinstance(report, dict):
        return fail("INVALID_INPUT", "缺少日报输入载荷或报告草稿。")
    if not isinstance(bindings, list) or not isinstance(citations, list):
        return fail("INVALID_INPUT", "事实绑定与引用必须是数组。")
    if not isinstance(artifacts, list) or not isinstance(artifact_bindings, list):
        return fail("INVALID_INPUT", "三件套清单与单元格绑定必须是数组。")

    issues: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    contract_problems = validate(payload)
    checks.append(
        {
            "name": "input-contract",
            "valid": not contract_problems,
            "details": "冻结日报载荷契约校验。",
        }
    )
    if contract_problems:
        issues.append(
            issue(
                "UPSTREAM_INPUT_INVALID",
                "engine_snapshot.payload",
                "引擎事实快照不符合冻结日报载荷契约。",
                responsibility="supervisor",
                actual=contract_problems[:10],
            )
        )

    template_version = request.get("template_version")
    if not isinstance(template_version, str) or not template_version.strip():
        return fail("INVALID_INPUT", "template_version 必须是非空字符串。")
    expected_report, expected_bindings, expected_citations, _ = build_report(
        payload,
        evidence_payload=request.get("standard_evidence"),
        analysis_payload=request.get("work_condition_analysis"),
        template_version=template_version.strip(),
    )

    sections = report.get("sections")
    missing_sections = (
        [name for name in REQUIRED_SECTIONS if not isinstance(sections, dict) or name not in sections]
    )
    checks.append(
        {
            "name": "required-sections",
            "valid": not missing_sections,
            "details": "日报必填章节检查。",
        }
    )
    if missing_sections:
        issues.append(
            issue(
                "MISSING_SECTION",
                "payload.sections",
                "日报草稿缺少必填章节。",
                expected=list(REQUIRED_SECTIONS),
                actual=missing_sections,
            )
        )

    report_matches = canonical_json(report) == canonical_json(expected_report)
    checks.append(
        {
            "name": "deterministic-render",
            "valid": report_matches,
            "details": "使用相同事实、证据和分析重新渲染后应逐字段一致。",
        }
    )
    if not report_matches:
        issues.append(
            issue(
                "REPORT_CONTENT_MISMATCH",
                "payload",
                "报告内容与当前上游快照的确定性渲染结果不一致。",
                expected=value_hash(expected_report),
                actual=value_hash(report),
            )
        )

    expected_binding_map = {
        binding["binding_id"]: binding for binding in expected_bindings
    }
    actual_binding_map = {
        binding.get("binding_id"): binding
        for binding in bindings
        if isinstance(binding, dict) and isinstance(binding.get("binding_id"), str)
    }
    bindings_valid = actual_binding_map == expected_binding_map
    for binding_id, binding in actual_binding_map.items():
        try:
            source_value = resolve_path(payload, binding["fact_path"])
            report_value = resolve_path(report, binding["report_path"])
        except (KeyError, IndexError, ValueError, TypeError):
            bindings_valid = False
            issues.append(
                issue(
                    "BINDING_PATH_INVALID",
                    f"fact_bindings.{binding_id}",
                    "事实绑定路径不存在或类型不匹配。",
                )
            )
            continue
        if value_hash(source_value) != binding.get("fact_value_hash"):
            bindings_valid = False
            issues.append(
                issue(
                    "FACT_HASH_MISMATCH",
                    f"fact_bindings.{binding_id}",
                    "事实绑定哈希与引擎事实不一致。",
                )
            )
        if canonical_json(source_value) != canonical_json(report_value):
            bindings_valid = False
            issues.append(
                issue(
                    "FACT_VALUE_MISMATCH",
                    binding["report_path"],
                    "报告字段与绑定的引擎事实不一致。",
                    expected=source_value,
                    actual=report_value,
                )
            )
    checks.append(
        {
            "name": "fact-bindings",
            "valid": bindings_valid,
            "details": "事实路径、值和 SHA-256 绑定检查。",
        }
    )
    if actual_binding_map.keys() != expected_binding_map.keys():
        issues.append(
            issue(
                "BINDING_SET_MISMATCH",
                "fact_bindings",
                "事实绑定集合不完整或包含未知绑定。",
                expected=sorted(expected_binding_map),
                actual=sorted(actual_binding_map),
            )
        )

    citation_matches = canonical_json(citations) == canonical_json(expected_citations)
    evidence_ids = {
        item.get("id")
        for item in expected_report["sections"]["standard_evidence"]["items"]
        if isinstance(item, dict)
    }
    for citation in citations:
        if not isinstance(citation, dict) or citation.get("evidence_id") not in evidence_ids:
            citation_matches = False
    checks.append(
        {
            "name": "citations",
            "valid": citation_matches,
            "details": "引用必须对应当前证据快照中的稳定 evidence ID。",
        }
    )
    if not citation_matches:
        issues.append(
            issue(
                "CITATION_MISMATCH",
                "citations",
                "报告引用与当前规范证据快照不一致。",
            )
        )

    prohibited = request.get("prohibited_phrases") or list(
        DEFAULT_PROHIBITED_PHRASES
    )
    if not isinstance(prohibited, list) or not all(
        isinstance(item, str) for item in prohibited
    ):
        return fail("INVALID_INPUT", "prohibited_phrases 必须是字符串数组。")
    markdown = report.get("markdown") if isinstance(report.get("markdown"), str) else ""
    found_phrases = [phrase for phrase in prohibited if phrase and phrase in markdown]
    checks.append(
        {
            "name": "responsibility-boundary",
            "valid": not found_phrases,
            "details": "自动签发、自动发布和确定性归因措辞检查。",
        }
    )
    for phrase in found_phrases:
        issues.append(
            issue(
                "PROHIBITED_PHRASE",
                "payload.markdown",
                f"草稿包含禁止措辞：{phrase}",
            )
        )

    review_required_valid = (
        report.get("status") == "draft"
        and report.get("review_required") is True
    )
    checks.append(
        {
            "name": "review-required",
            "valid": review_required_valid,
            "details": "报告必须标记为草稿并要求工程师复核。",
        }
    )
    if not review_required_valid:
        issues.append(
            issue(
                "RESPONSIBILITY_BOUNDARY_MISSING",
                "payload.review_required",
                "报告未明确标记为草稿或未要求工程师复核。",
            )
        )

    artifact_trace: dict[str, Any] = {}
    try:
        from report_artifacts import audit_report_artifacts

        raw_artifact_issues, artifact_trace = audit_report_artifacts(
            expected_report,
            payload,
            artifacts,
            artifact_bindings,
        )
    except ImportError as exc:
        raw_artifact_issues = [
            {
                "code": "ARTIFACT_AUDIT_UNAVAILABLE",
                "path": "artifacts",
                "message": f"日报三件套审计依赖不可用：{exc}",
            }
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raw_artifact_issues = [
            {
                "code": "ARTIFACT_AUDIT_FAILED",
                "path": "artifacts",
                "message": f"日报三件套审计异常：{exc}",
            }
        ]
    for artifact_issue in raw_artifact_issues:
        issues.append(
            issue(
                str(artifact_issue.get("code") or "ARTIFACT_AUDIT_FAILED"),
                str(artifact_issue.get("path") or "artifacts"),
                str(artifact_issue.get("message") or "日报三件套审计失败。"),
                expected=artifact_issue.get("expected"),
                actual=artifact_issue.get("actual"),
            )
        )
    artifact_codes = {
        str(artifact_issue.get("code")) for artifact_issue in raw_artifact_issues
    }
    checks.extend(
        [
            {
                "name": "exported-artifacts",
                "valid": not raw_artifact_issues,
                "details": "固定三件套、受控路径、文件哈希和字节数检查。",
            },
            {
                "name": "workbook-cell-bindings",
                "valid": not any(
                    code.startswith("WORKBOOK_")
                    or code == "ARTIFACT_BINDING_SET_MISMATCH"
                    for code in artifact_codes
                ),
                "details": "Excel 工作表、单元格值与冻结事实绑定检查。",
            },
            {
                "name": "markdown-correspondence",
                "valid": "MARKDOWN_CONTENT_MISMATCH" not in artifact_codes,
                "details": "封面及附表 Markdown 与结构化报告/Excel 模型对应检查。",
            },
        ]
    )

    unique_issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in issues:
        key = (item["code"], item["path"], item["message"])
        if key not in seen:
            seen.add(key)
            unique_issues.append(item)

    emit(
        {
            "schema": RESULT_SCHEMA,
            "skill": SKILL,
            "ok": True,
            "result": {
                "valid": not any(item["blocking"] for item in unique_issues),
                "checks": checks,
                "issues": unique_issues,
            },
            "trace": {
                "checked_binding_count": len(bindings),
                "checked_citation_count": len(citations),
                "issue_count": len(unique_issues),
                "source_report_hash": value_hash(report),
                "expected_report_hash": value_hash(expected_report),
                **artifact_trace,
            },
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
