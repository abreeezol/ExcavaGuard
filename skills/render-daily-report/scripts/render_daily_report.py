#!/usr/bin/env python3
"""stdin/stdout adapter for the render-daily-report service contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT / "确定性计算层" / "tools"))

from report_adapter import TEMPLATE_VERSION, build_report  # noqa: E402
from validate_daily_report_input import validate  # noqa: E402

RESULT_SCHEMA = "excavaguard.skill_result/v1"
SKILL = "render-daily-report"


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


def main() -> int:
    try:
        request = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return fail("INVALID_INPUT", "请求体不是有效 JSON。")

    if not isinstance(request, dict):
        return fail("INVALID_INPUT", "请求体必须是对象。")
    payload = request.get("daily_report_input")
    if not isinstance(payload, dict):
        return fail("INVALID_INPUT", "缺少 daily_report_input 对象。")

    problems = validate(payload)
    if problems:
        return fail(
            "VALIDATION_FAILED",
            "日报输入载荷不符合冻结契约：" + "；".join(problems[:5]),
        )

    template_version = request.get("template_version") or TEMPLATE_VERSION
    if not isinstance(template_version, str) or not template_version.strip():
        return fail("INVALID_INPUT", "template_version 必须是非空字符串。")

    report, bindings, citations, trace = build_report(
        payload,
        evidence_payload=request.get("standard_evidence"),
        analysis_payload=request.get("work_condition_analysis"),
        template_version=template_version.strip(),
    )
    emit(
        {
            "schema": RESULT_SCHEMA,
            "skill": SKILL,
            "ok": True,
            "result": {
                "report_payload": report,
                "fact_bindings": bindings,
                "citations": citations,
                "template_version": template_version.strip(),
                "review_required": True,
            },
            "trace": trace,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
