"""
校验日报生成模块输入契约
========================

把确定性计算层的输出载荷与 `contracts/daily_report_input.schema.json` 对照校验，
供日报生成 Agent 在消费前做前置检查，也供本层回归测试调用。

用法
----
    python tools/validate_daily_report_input.py <载荷.json>
    python tools/validate_daily_report_input.py --self-test      # 现场跑一遍流水线再校验

退出码：0 = 通过；1 = 校验失败。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SCHEMA_PATH = BASE / "contracts" / "daily_report_input.schema.json"

sys.path.insert(0, str(BASE / "pipeline"))
sys.path.insert(0, str(BASE / "pipeline" / "stage1_data_preparation"))
sys.path.insert(0, str(BASE / "pipeline" / "stage2_deterministic_calc"))
sys.path.insert(0, str(BASE / "pipeline" / "stage3_standard_comparison"))


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate(payload: dict) -> list[str]:
    """返回违规描述列表；空列表表示通过。"""
    try:
        import jsonschema
    except ModuleNotFoundError:  # 降级为结构性检查，不阻断使用
        return _validate_without_lib(payload)
    validator = jsonschema.Draft202012Validator(load_schema())
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


def _validate_without_lib(payload: dict) -> list[str]:
    """未安装 jsonschema 时的最小校验：顶层必填键 + 明细必填键 + 关键枚举。"""
    schema = load_schema()
    problems: list[str] = []
    for k in schema.get("required", []):
        if k not in payload:
            problems.append(f"<root>: 缺少必填键 {k}")
    if payload.get("schema") != schema.get("$id"):
        problems.append(f"schema: 期望 {schema.get('$id')}，实际 {payload.get('schema')}")
    item_req = schema["$defs"]["item"]["required"]
    for i, it in enumerate(payload.get("items", [])):
        for k in item_req:
            if k not in it:
                problems.append(f"items/{i}: 缺少必填键 {k}")
        if it.get("data_origin") not in ("real", "simulated"):
            problems.append(f"items/{i}/data_origin: 非法取值 {it.get('data_origin')}")
        if it.get("risk_level") not in ("正常", "关注", "预警", "报警", "危险报警", "未知"):
            problems.append(f"items/{i}/risk_level: 非法取值 {it.get('risk_level')}")
    return problems


def _build_payload() -> dict:
    """现场跑一条最小流水线，产出真实载荷。"""
    from orchestrator import build_daily_report_input, run_pipeline
    from risk_identifier import ProjectContext

    recs = []
    for d, v in enumerate([0, 5, 12, 22, 35, 52, 60], start=1):
        recs.append(
            {
                "point_id": "WTHD-01",
                "metric_key": "wall_top_horizontal_displacement",
                "timestamp": f"2026-08-0{d}",
                "value": v,
                "baseline_value": 0,
                "previous_value": 0 if d == 1 else [0, 5, 12, 22, 35, 52][d - 2],
                "interval_days": 1,
                "unit": "mm",
            }
        )
    ctx = ProjectContext(safety_level="一级", support_type="地下连续墙", excavation_depth_m=20.0)
    result = run_pipeline(recs, ctx)
    return build_daily_report_input(result, report_date="2026-08-07")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="校验日报生成模块输入契约")
    ap.add_argument("payload", nargs="?", help="载荷 JSON 文件路径")
    ap.add_argument("--self-test", action="store_true", help="现场跑流水线并校验其输出")
    args = ap.parse_args(argv)

    if args.self_test:
        payload = _build_payload()
        label = "自测载荷"
    elif args.payload:
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        label = args.payload
    else:
        ap.error("请给出载荷文件路径，或使用 --self-test")

    problems = validate(payload)
    if problems:
        print(f"[FAIL] {label} 不符合契约，共 {len(problems)} 处：")
        for p in problems[:40]:
            print("   -", p)
        return 1

    print(f"[PASS] {label} 符合契约 {payload.get('schema')}")
    print(f"       条目 {len(payload.get('items', []))} 条"
          f"（报警 {len(payload.get('alerts', []))}、待复核 {len(payload.get('review_queue', []))}）"
          f"；生效阈值来源 {payload.get('context', {}).get('effective_standard_origin')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
