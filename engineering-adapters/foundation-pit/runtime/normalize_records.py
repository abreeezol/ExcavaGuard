#!/usr/bin/env python3
"""normalize-monitoring-data stdin/stdout adapter.

This adapter exposes the deterministic stage-one normalizer without duplicating
its rules. It accepts either inline records or a stored monitoring file.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

SKILL = "normalize-monitoring-data"
RESULT_SCHEMA = "excavaguard.skill_result/v1"


def _engine_dir() -> Path:
    configured = os.environ.get("EXCAVAGUARD_ENGINE_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "确定性计算层"


def _emit(body: dict) -> None:
    print(json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str))


def _fail(code: str, message: str, status: int = 2) -> int:
    _emit(
        {
            "schema": RESULT_SCHEMA,
            "skill": SKILL,
            "ok": False,
            "error": {"code": code, "message": message},
        }
    )
    return status


def main() -> int:
    started = time.perf_counter()
    try:
        request = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _fail("INVALID_INPUT", "请求体不是有效 JSON。")
    if not isinstance(request, dict):
        return _fail("INVALID_INPUT", "请求体必须是对象。")

    engine = _engine_dir()
    paths = (
        engine / "pipeline",
        engine / "pipeline" / "stage1_data_preparation",
        engine / "pipeline" / "stage3_standard_comparison",
    )
    if not all(path.is_dir() for path in paths):
        return _fail("ENGINE_NOT_FOUND", f"引擎目录不存在或不完整：{engine}", 3)
    for path in paths:
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    try:
        from file_reader import aggregate_daily_records, read_monitoring_file
        from ingest import build_metric_aliases, derive_temporal_fields, normalize_records
        from quality_scan import scan_records
        from standards_registry import StandardsRegistry

        records = request.get("records")
        read_report: dict | None = None
        aggregation_report: dict | None = None
        file_path = request.get("file_path")
        if not isinstance(records, list) or not records:
            if not isinstance(file_path, str) or not file_path.strip():
                return _fail("INVALID_INPUT", "records 必须是非空数组，或提供 file_path。")
            records, read_report = read_monitoring_file(file_path)
            if not read_report.get("ok"):
                return _fail(
                    "MISSING_FIELD",
                    "；".join(read_report.get("errors") or ["文件字段不符合契约。"]),
                )
        if not records or any(not isinstance(record, dict) for record in records):
            return _fail("INVALID_INPUT", "records 必须是非空对象数组。")

        source_records = len(records)
        daily_aggregate = request.get("daily_aggregate", False)
        if not isinstance(daily_aggregate, bool):
            return _fail("INVALID_INPUT", "daily_aggregate 必须是布尔值。")
        should_aggregate = daily_aggregate
        if read_report and read_report.get("layout") == "wide" and should_aggregate:
            records, aggregation_report = aggregate_daily_records(
                records,
                report_date=request.get("report_date"),
            )
            read_report["daily_aggregation"] = aggregation_report

        aliases = build_metric_aliases(StandardsRegistry().display_names())
        normalized = normalize_records(records, metric_aliases=aliases)
        derived = derive_temporal_fields(normalized)
        quality = scan_records(
            normalized,
            expected_interval_days=request.get("expected_interval_days"),
        ).to_dict()

        semantics = Counter(record.measurement_semantics for record in normalized)
        metrics = Counter(record.metric_key for record in normalized)
        source_flags = Counter(flag for record in normalized for flag in record.source_flags)
        process_flags = Counter(flag for record in normalized for flag in record.flags)
        serialized = [record.to_dict() for record in normalized]
        result = {
            "read_report": read_report,
            "daily_aggregation": aggregation_report,
            "derived": derived,
            "quality_report": quality,
            "summary": {
                "source_records": source_records,
                "normalized_records": len(normalized),
                "measurement_semantics": dict(semantics),
                "metrics": dict(metrics),
                "source_flags": dict(source_flags),
                "process_flags": dict(process_flags),
            },
            "records_preview": serialized[:3],
        }
        if request.get("include_records"):
            result["records"] = serialized

        _emit(
            {
                "schema": RESULT_SCHEMA,
                "skill": SKILL,
                "ok": True,
                "result": result,
                "trace": {
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    "source_records": source_records,
                    "records": len(normalized),
                    "engine_dir": str(engine),
                },
            }
        )
        return 0
    except FileNotFoundError:
        return _fail("FILE_NOT_FOUND", f"文件不存在：{request.get('file_path')}")
    except ValueError as exc:
        return _fail("DATA_QUALITY", str(exc))
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(traceback.format_exc())
        return _fail("ENGINE_ERROR", f"{type(exc).__name__}: {exc}", 3)


if __name__ == "__main__":
    raise SystemExit(main())
