#!/usr/bin/env python3
"""
evaluate-thresholds · 引擎桥接脚本（stdin/stdout JSON）
======================================================

供 Web 入口（Node/Next.js）以子进程方式调用确定性计算引擎。
**只做协议转换，不含任何判定逻辑** —— 判定全部由 `确定性计算层/pipeline/` 完成。

协议
----
stdin （JSON）：

    {
      "records":  [ {...}, ... ],              # 与 file_path 二选一：监测记录（原始表可直接传）
      "context":  {                            # 必填：工程条件
        "safety_level": "一级",
        "support_type": "地下连续墙",
        "excavation_depth_m": 20.0,
        "design_values": {"support_axial_force": 1000.0},
        "post_slab_from": "2026-09-10",
        "point_overrides": {"LF-01": {"crack_state": "既有裂缝"}}
      },
      "options": {                             # 可选
        "file_path": null,                     # 与 records 二选一：由引擎侧读取文件（含编码探测）
        "expected_interval_days": 1.0,
        "value_range": [null, null],
        "report_date": "2026-08-07",
        "project": {"name": "××基坑工程"},
        "points_meta": {"WTHD-01": {"point_name": "墙顶水平位移 1 号点"}},
        "standards_dir": null,                 # 指定用户规范目录时传入
        "with_payload": true                   # 是否返回日报载荷（默认 true）
      }
    }

`records` 与 `options.file_path` 必须提供其一。提供 `file_path` 时，
由本脚本调用 `file_reader.read_monitoring_file()` 读取（自动探测编码与分隔符），
读取报告写入 `trace.read_report`；**必填列缺失时以 `MISSING_FIELD` 退出码 2 拒绝**。

stdout（JSON）：

    {
      "schema": "excavaguard.skill_result/v1",
      "skill": "evaluate-thresholds",
      "ok": true,
      "result": { ... excavaguard.daily_report_input/v1 ... },
      "trace": { "elapsed_ms": 12, "records": 7, "engine_dir": "..." }
    }

出错时（仍为 JSON，进程退出码非 0）：

    {"schema": "...", "skill": "...", "ok": false,
     "error": {"code": "INVALID_INPUT", "message": "..."}}

错误码：`INVALID_INPUT` / `MISSING_FIELD` / `DATA_QUALITY` / `FILE_NOT_FOUND` /
`FILE_UNREADABLE` / `ENGINE_NOT_FOUND` / `ENGINE_ERROR`。

退出码：0 成功；2 输入或文件问题；3 引擎异常。

环境变量
--------
EXCAVAGUARD_ENGINE_DIR  引擎根目录（含 pipeline/）。默认按相对路径推断。
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

SKILL = "evaluate-thresholds"
RESULT_SCHEMA = "excavaguard.skill_result/v1"


def _engine_dir() -> Path:
    env = os.environ.get("EXCAVAGUARD_ENGINE_DIR")
    if env:
        return Path(env)
    # 本文件位于 <repo>/skills/evaluate-thresholds/scripts/
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "确定性计算层"


def _fail(code: str, message: str, status: int) -> int:
    print(json.dumps(
        {"schema": RESULT_SCHEMA, "skill": SKILL, "ok": False,
         "error": {"code": code, "message": message}},
        ensure_ascii=False,
    ))
    return status


def main() -> int:
    t0 = time.perf_counter()

    raw = sys.stdin.read()
    if not raw.strip():
        return _fail("INVALID_INPUT", "stdin 为空，需要 JSON 请求体。", 2)
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _fail("INVALID_INPUT", f"请求体不是有效 JSON：{exc}", 2)
    if not isinstance(req, dict):
        return _fail("INVALID_INPUT", "请求体必须是 JSON 对象。", 2)

    opts = req.get("options") or {}
    engine = _engine_dir()
    if not (engine / "pipeline").is_dir():
        return _fail("ENGINE_NOT_FOUND", f"引擎目录不存在或不完整：{engine}", 3)

    for p in (
        engine / "pipeline",
        engine / "pipeline" / "stage1_data_preparation",
        engine / "pipeline" / "stage2_deterministic_calc",
        engine / "pipeline" / "stage3_standard_comparison",
    ):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))

    # --- 记录来源：内联 records 或由引擎读取文件 ---
    records = req.get("records")
    read_report: dict | None = None
    file_path = opts.get("file_path")
    if not isinstance(records, list) or not records:
        if not file_path:
            return _fail("INVALID_INPUT", "records 必须是非空数组，或提供 options.file_path。", 2)
        try:
            from file_reader import read_monitoring_file

            records, read_report = read_monitoring_file(file_path)
        except FileNotFoundError:
            return _fail("FILE_NOT_FOUND", f"监测数据文件不存在：{file_path}", 2)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(traceback.format_exc())
            return _fail("FILE_UNREADABLE", f"读取监测数据文件失败：{exc}", 2)
        if not read_report.get("ok", False):
            return _fail(
                "MISSING_FIELD",
                "；".join(read_report.get("errors") or ["文件缺少必填列。"]),
                2,
            )
        if not records:
            return _fail("DATA_QUALITY", "文件没有可用的数据行。", 2)

    ctx_raw = req.get("context")
    if not isinstance(ctx_raw, dict):
        return _fail("INVALID_INPUT", "context 必须是对象（工程条件）。", 2)
    if ctx_raw.get("excavation_depth_m") in (None, ""):
        # 不阻断，但明确告知：%H 类限值无法换算（见 06_..._目标实现度评估.md P1-2）
        sys.stderr.write(
            "WARN: 未提供 excavation_depth_m，%H 类限值无法换算，"
            "累计值判定将只用绝对量限值（可能偏松）。\n"
        )

    try:
        from orchestrator import build_daily_report_input, run_pipeline
        from risk_identifier import ProjectContext
        from standards_registry import StandardsRegistry

        ctx = ProjectContext(
            safety_level=ctx_raw.get("safety_level") or "一级",
            support_type=ctx_raw.get("support_type") or "any",
            excavation_depth_m=ctx_raw.get("excavation_depth_m"),
            pipeline_type=ctx_raw.get("pipeline_type"),
            road_type=ctx_raw.get("road_type"),
            crack_state=ctx_raw.get("crack_state"),
            design_values=ctx_raw.get("design_values") or {},
            danger_signals=ctx_raw.get("danger_signals") or {},
            point_overrides=ctx_raw.get("point_overrides") or {},
            post_slab_from=ctx_raw.get("post_slab_from"),
        )

        standards_dir = opts.get("standards_dir")
        registry = StandardsRegistry(user_dir=standards_dir) if standards_dir else None

        value_range = opts.get("value_range")
        vr = tuple(value_range) if isinstance(value_range, list) and len(value_range) == 2 else None

        result = run_pipeline(
            records,
            ctx,
            expected_interval_days=opts.get("expected_interval_days"),
            value_range=vr,
            registry=registry,
        )

        payload = build_daily_report_input(
            result,
            project=opts.get("project"),
            points_meta=opts.get("points_meta"),
            report_date=opts.get("report_date"),
        )

        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        print(json.dumps(
            {
                "schema": RESULT_SCHEMA,
                "skill": SKILL,
                "ok": True,
                "result": payload,
                "summary": result.summary,
                "trace": {
                    "elapsed_ms": elapsed,
                    "records": len(records),
                    "engine_dir": str(engine),
                    "python": sys.version.split()[0],
                    "read_report": read_report,
                },
            },
            ensure_ascii=False,
            default=str,
        ))
        return 0

    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(traceback.format_exc())
        return _fail("ENGINE_ERROR", f"{type(exc).__name__}: {exc}", 3)


if __name__ == "__main__":
    raise SystemExit(main())
