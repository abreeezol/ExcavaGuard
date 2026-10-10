"""
模拟数据场景覆盖率验证
======================

把 `data_simulated/` 中的模拟数据集送进三阶段流程，逐场景比对
「期望风险等级 / 期望数据质量码」与「实际判定结果」，输出覆盖率报告。

输入全部为**模拟/生成数据**（data_origin = simulated），与真实数据分开统计。
本脚本只读，不修改任何数据文件；报告写入 `derived/`。

运行：
    python -B tools/run_simulated_validation.py
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SIM = BASE / "data_simulated"
DERIVED = BASE / "derived"
PIPE = BASE / "pipeline"

for p in (
    str(PIPE / "stage1_data_preparation"),
    str(PIPE / "stage2_deterministic_calc"),
    str(PIPE / "stage3_standard_comparison"),
    str(PIPE),
):
    if p not in sys.path:
        sys.path.insert(0, p)

from risk_identifier import ProjectContext  # noqa: E402
from orchestrator import run_pipeline  # noqa: E402


def load_records(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def main() -> int:
    csv_path = SIM / "SIMULATED_基坑监测数据集_v1.csv"
    ctx_path = SIM / "SIMULATED_工程条件_v1.json"
    mf_path = SIM / "SIMULATED_场景清单_v1.json"
    for p in (csv_path, ctx_path, mf_path):
        if not p.exists():
            print(f"缺少文件：{p}\n请先运行 python -B tools/generate_simulated_dataset.py")
            return 1

    records = load_records(csv_path)
    cfg = json.loads(ctx_path.read_text(encoding="utf-8"))
    manifest = json.loads(mf_path.read_text(encoding="utf-8"))

    ctx = ProjectContext(
        safety_level=cfg["safety_level"],
        support_type=cfg["support_type"],
        excavation_depth_m=cfg["excavation_depth_m"],
        design_values=cfg["design_values"],
        point_overrides=cfg["point_overrides"],
        post_slab_from=cfg["post_slab_from"],
    )

    print("=" * 78)
    print("模拟数据场景覆盖率验证")
    print("=" * 78)
    print(f"数据集      : {csv_path.name}")
    print(f"数据性质    : {manifest['data_origin']}（模拟/生成数据，非真实工程数据）")
    print(f"溯源标识    : {manifest['source_dataset']}")
    print(f"记录 / 测点 : {len(records)} / {manifest['points']}，{manifest['days']} 天，{manifest['scenario_count']} 个场景")
    print()

    result = run_pipeline(records, ctx, expected_interval_days=1.0)
    s1, s2, s3 = result.stage1, result.stage2, result.stage3

    print("--- 阶段一 · 数据准备 ---")
    print(f"  归一化记录        : {s1['normalized_records']}")
    print(f"  数据来源分布      : {s1['data_origin_counts']}   ← 模拟数据单独计数")
    print(f"  数据质量问题      : {s1['quality_report']['issue_count']} 条")
    print(f"  其中被阻塞期次    : {s1['blocked_records']} 条（不参与风险判定，转人工复核）")
    print(f"  问题码分布        : {s1['quality_report']['by_code']}")

    print("\n--- 阶段二 · 确定性计算 ---")
    print(f"  计算结果          : {s2['calc_count']} 条")
    print(f"  其中弃权          : {s2['abstain_count']} 条")

    print("\n--- 阶段三 · 规范比对 ---")
    print(f"  生效规范来源      : {result.summary['effective_standard_origin']}")
    print(f"  风险等级分布      : {result.summary['by_risk_level']}")
    print(f"  问题类别分布      : {result.summary['by_problem_category']}")
    print(f"  弃权原因分布      : {result.summary['abstain']}")

    # --- 逐场景比对 -------------------------------------------------------
    levels_by_point: dict[str, set] = defaultdict(set)
    blocked_by_point: dict[str, int] = defaultdict(int)
    for j in s3["judgments"]:
        levels_by_point[j["point_id"]].add(j["risk_level"])
        if "DATA_QUALITY_BLOCKED" in j["abstain"]:
            blocked_by_point[j["point_id"]] += 1

    codes_by_point: dict[str, set] = defaultdict(set)
    for issue in s1["quality_report"]["issues"]:
        codes_by_point[issue["point_id"]].add(issue["code"])

    rows, fail = [], []
    for sc in manifest["scenarios"]:
        sc_ok = True
        details = []
        for pid in sc["points"]:
            exp_level = next(p["expected_level"] for p in manifest["point_details"] if p["point_id"] == pid)
            exp_blocked = next(p["expected_blocked"] for p in manifest["point_details"] if p["point_id"] == pid)
            exp_codes = next(p["expected_quality_codes"] for p in manifest["point_details"] if p["point_id"] == pid)

            got_levels = levels_by_point.get(pid, set())
            got_blocked = blocked_by_point.get(pid, 0) > 0
            got_codes = codes_by_point.get(pid, set())

            ok_level = exp_level in got_levels
            ok_blocked = got_blocked == exp_blocked
            ok_codes = all(c in got_codes for c in exp_codes)
            ok = ok_level and ok_blocked and ok_codes
            sc_ok = sc_ok and ok
            details.append(
                {
                    "point_id": pid,
                    "expected_level": exp_level,
                    "observed_levels": sorted(got_levels),
                    "expected_blocked": exp_blocked,
                    "observed_blocked": got_blocked,
                    "expected_codes": exp_codes,
                    "observed_codes": sorted(got_codes),
                    "ok": ok,
                }
            )

        rows.append(
            {
                "scenario_id": sc["scenario_id"],
                "scenario_name": sc["scenario_name"],
                "problem_category": sc["problem_category"],
                "expected_level": sc["expected_level"],
                "points": sc["points"],
                "pass": sc_ok,
                "details": details,
            }
        )
        if not sc_ok:
            fail.append(sc)

    print("\n" + "=" * 78)
    print("逐场景结果")
    print("=" * 78)
    print(f"{'场景':<6}{'名称':<22}{'期望等级':<10}{'测点':<6}{'结果'}")
    print("-" * 78)
    for r in rows:
        print(f"{r['scenario_id']:<6}{r['scenario_name']:<22}{r['expected_level']:<10}{len(r['points']):<6}{'通过' if r['pass'] else '未通过'}")

    if fail:
        print("\n" + "=" * 78)
        print("未通过明细")
        print("=" * 78)
        for r in rows:
            if r["pass"]:
                continue
            for d in r["details"]:
                if d["ok"]:
                    continue
                print(f"  [{r['scenario_id']}] {d['point_id']}")
                print(f"      期望等级 {d['expected_level']} / 实测等级集 {d['observed_levels']}")
                print(f"      期望阻塞 {d['expected_blocked']} / 实测阻塞 {d['observed_blocked']}")
                print(f"      期望质量码 {d['expected_codes']} / 实测质量码 {d['observed_codes']}")

    # --- 覆盖率统计 -------------------------------------------------------
    covered_levels = set()
    for r in rows:
        if r["pass"]:
            covered_levels.add(r["expected_level"])
    quality_scenarios = [r for r in rows if r["details"] and any(d["expected_codes"] for d in r["details"])]
    quality_ok = [r for r in quality_scenarios if r["pass"]]

    print("\n" + "=" * 78)
    print("覆盖率统计")
    print("=" * 78)
    print(f"  场景总数            : {len(rows)}")
    print(f"  通过                : {sum(1 for r in rows if r['pass'])}")
    print(f"  未通过              : {sum(1 for r in rows if not r['pass'])}")
    print(f"  场景通过率          : {sum(1 for r in rows if r['pass']) / len(rows):.1%}")
    print(f"  已覆盖风险等级      : {sorted(covered_levels)}")
    print(f"  数据质量类场景      : {len(quality_scenarios)}，通过 {len(quality_ok)}")
    print(f"  模拟记录数          : {result.summary['simulated_records']}")
    print(f"  真实记录数          : {result.summary['real_records']}  ← 本次未使用真实数据")

    DERIVED.mkdir(parents=True, exist_ok=True)
    out = DERIVED / "模拟数据_场景覆盖率验证_结果.json"
    out.write_text(
        json.dumps(
            {
                "dataset": csv_path.name,
                "data_origin": "simulated",
                "source_dataset": manifest["source_dataset"],
                "records": len(records),
                "points": manifest["points"],
                "scenarios_total": len(rows),
                "scenarios_passed": sum(1 for r in rows if r["pass"]),
                "pass_rate": sum(1 for r in rows if r["pass"]) / len(rows),
                "covered_levels": sorted(covered_levels),
                "pipeline_summary": result.summary,
                "scenarios": rows,
                "disclaimer": "全部为模拟/生成数据，与真实数据分开统计，不得用于真实工程判定。",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n结果已写入：{out}")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
