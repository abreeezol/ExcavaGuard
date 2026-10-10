#!/usr/bin/env python3
"""
parse-monitoring-data · 文件解析检查（stdin/stdout JSON）
========================================================

供 Web 入口（Node/Next.js）以子进程方式调用，在**上传后立即**告诉用户：
文件是什么编码、用什么分隔符、哪些列被识别、哪些列没识别、是否缺必填列。

**只读取与映射，不计算、不推断、不改数值** —— 计算全部在 `确定性计算层/pipeline/`。

协议
----
stdin （JSON）：

    {
      "file_path": "/abs/path/to/upload.csv",   # 必填
      "include_records": false                  # 可选，默认 false（避免大文件回传）
    }

stdout（JSON）：

    {
      "schema": "excavaguard.skill_result/v1",
      "skill": "parse-monitoring-data",
      "ok": true,
      "result": { ... read_monitoring_file 的 report ... },
      "records_preview": [ ... 前 3 条 ... ],   # 仅 include_records=true
      "trace": { "elapsed_ms": 3, "records": 7 }
    }

出错时（仍为 JSON，进程退出码非 0）：

    {"schema": "...", "skill": "...", "ok": false,
     "error": {"code": "FILE_NOT_FOUND", "message": "..."}}

退出码：0 成功；2 文件问题；3 未预期异常。

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

SKILL = "parse-monitoring-data"
RESULT_SCHEMA = "excavaguard.skill_result/v1"


def _engine_dir() -> Path:
    env = os.environ.get("EXCAVAGUARD_ENGINE_DIR")
    if env:
        return Path(env)
    # 本文件位于 <repo>/skills/parse-monitoring-data/scripts/
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

    file_path = req.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        return _fail("INVALID_INPUT", "file_path 必须是非空字符串。", 2)

    engine = _engine_dir()
    stage1 = engine / "pipeline" / "stage1_data_preparation"
    if not stage1.is_dir():
        return _fail("ENGINE_NOT_FOUND", f"引擎目录不存在或不完整：{engine}", 3)
    if str(stage1) not in sys.path:
        sys.path.insert(0, str(stage1))

    try:
        from file_reader import read_monitoring_file

        records, report = read_monitoring_file(file_path)
        include = bool(req.get("include_records"))
        out = {
            "schema": RESULT_SCHEMA,
            "skill": SKILL,
            "ok": bool(report.get("ok")),
            "result": report,
            "trace": {
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
                "records": len(records),
                "engine_dir": str(engine),
            },
        }
        if include:
            out["records_preview"] = records[:3]
        if not report.get("ok"):
            out["error"] = {
                "code": "MISSING_FIELD",
                "message": "；".join(report.get("errors") or ["文件缺少必填列。"]),
            }
            print(json.dumps(out, ensure_ascii=False, default=str))
            return 2
        print(json.dumps(out, ensure_ascii=False, default=str))
        return 0

    except FileNotFoundError:
        return _fail("FILE_NOT_FOUND", f"文件不存在：{file_path}", 2)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(traceback.format_exc())
        return _fail("FILE_UNREADABLE", f"{type(exc).__name__}: {exc}", 3)


if __name__ == "__main__":
    raise SystemExit(main())
