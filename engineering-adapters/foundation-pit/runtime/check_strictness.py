#!/usr/bin/env python3
"""
evaluate-thresholds · 用户阈值宽松度校验（stdin/stdout JSON）
=============================================================

回答一个安全问题：**用户上传的阈值，是否比默认规范更宽松？**

宽松意味着原本应判「危险报警」的实测值可能被判成「预警」。
本脚本**只校验与反馈，不阻断、不修改**任何数值，也不写任何文件。

比较口径与判定完全一致（`limit_strictness.py`）：
- 只比较用户**实际给出**的字段，未提供的字段继承默认库（天然一致，不告警）；
- 累计值按 `min(绝对量, %H)` 的**有效值**比较，而不是按原始字段；
- 缺 H 且规则含 `%H` → `incomparable`（**不默认通过**）；
- `min_ratio_of_design` 是预应力**下限**，越大越严，方向与其余字段相反；
- 默认库无对应判据 → 归入 `unmatched`，不告警（属"用户新增判据"）。

协议
----
stdin （JSON）：

    {
      "payload": { ... 用户规范 JSON（见 standards_registry.UPLOAD_TEMPLATE）... },
      "context": { "safety_level": "一级", "support_type": "地下连续墙",
                   "excavation_depth_m": 20.0 }        # 可选，缺失则 %H 项判为不可比
    }

stdout（JSON）：

    {
      "schema": "excavaguard.skill_result/v1",
      "skill": "evaluate-thresholds",
      "ok": true,
      "problems": [],                       # 结构校验问题，非空时 ok=false
      "strictness": { ... summarize() 结果 ... },
      "report": "可直接展示给用户的文本报告",
      "trace": { "elapsed_ms": 4 }
    }

退出码：0 成功；2 输入或结构非法；3 未预期异常。

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
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "确定性计算层"


def _fail(code: str, message: str, status: int, extra: dict | None = None) -> int:
    body = {"schema": RESULT_SCHEMA, "skill": SKILL, "ok": False,
            "error": {"code": code, "message": message}}
    if extra:
        body.update(extra)
    print(json.dumps(body, ensure_ascii=False, default=str))
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

    payload = req.get("payload")
    if not isinstance(payload, dict):
        return _fail("INVALID_INPUT", "payload 必须是对象（用户规范 JSON）。", 2)

    ctx_raw = req.get("context") or {}
    if not isinstance(ctx_raw, dict):
        return _fail("INVALID_INPUT", "context 必须是对象。", 2)

    engine = _engine_dir()
    stage3 = engine / "pipeline" / "stage3_standard_comparison"
    if not stage3.is_dir():
        return _fail("ENGINE_NOT_FOUND", f"引擎目录不存在或不完整：{engine}", 3)
    if str(stage3) not in sys.path:
        sys.path.insert(0, str(stage3))

    try:
        from limit_strictness import format_report
        from risk_identifier import ProjectContext
        from standards_registry import StandardsRegistry, check_upload_strictness

        # 只加载默认规范库：上传的新文件此时尚未落盘，正好用于"与默认比对"
        registry = StandardsRegistry()

        problems = registry.validate_upload(payload)
        if problems:
            return _fail("INVALID_STANDARD", "；".join(problems), 2,
                         extra={"problems": problems})

        ctx = ProjectContext(
            safety_level=ctx_raw.get("safety_level") or "一级",
            support_type=ctx_raw.get("support_type") or "any",
            excavation_depth_m=ctx_raw.get("excavation_depth_m"),
        )

        strictness = check_upload_strictness(registry, payload, ctx)
        report = format_report(strictness["looser"]) if strictness["has_looser"] else ""

        print(json.dumps(
            {
                "schema": RESULT_SCHEMA,
                "skill": SKILL,
                "ok": True,
                "problems": [],
                "strictness": strictness,
                "report": report,
                "trace": {
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "engine_dir": str(engine),
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
