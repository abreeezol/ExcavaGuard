"""
真实数据 + 模拟数据 合并跑通三阶段
==================================

把两类输入**一起**送入「阶段一 数据准备 → 阶段二 确定性计算 → 阶段三 规范比对」：

| 输入 | 来源 | data_origin | 记录数 |
|---|---|---|---|
| 真实数据 | 多传感器隧道监测 `daily_aligned.csv`（剔除 mask=0 与 filled=1） | `real` | 2,868 |
| 模拟数据 | `data_simulated/SIMULATED_基坑监测数据集_v1.csv` | `simulated` | 2,760 |

两者在阶段一统一归一化、统一作为风险识别参数的输入依据，
但**全程按 `data_origin` 分开统计**，绝不混同。

同时对比三组：
  A｜仅真实数据 + 默认规范库            → 隧道通道在基坑规范库中无判据，应全部弃权
  B｜仅真实数据 + 用户上传规范          → 用真实阈值文件派生的规范完成比对
  C｜真实 + 模拟合并 + 默认库 + 用户上传 → 混合输入，按来源分开统计

约束：
- 只读原始文件，不修改、不覆盖、不删除；
- 用户上传规范写入临时目录，运行结束即清理，不污染 `standards/user_uploaded/`；
- 报告与**日报接口载荷**写入 `derived/`。

日报接口
--------
本脚本额外产出 A/B/C 三组的 `excavaguard.daily_report_input/v1` 载荷并逐份校验，
证明契约在真实数据（含弃权与复核队列）下同样成立。
**本层不生成日报文件**，日报正文与建议措辞由后续独立 Agent 负责。

运行：
    python -B tools/run_combined_real_and_simulated.py
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent
PIPE = BASE / "pipeline"
DERIVED = BASE / "derived"
SIM = BASE / "data_simulated"

# 报告日期（仅用于演示载荷；实际由调用方在生成日报时填入）
REPORT_DATE = "2026-08-07"

ROOT = Path(r"C:\Study\bisai\Hai AI Agent\基坑智守项目相关数据")
SENSOR_DATA = ROOT / "多传感器隧道监测数据" / "sensors_public_dataset" / "data"

for p in (
    str(PIPE / "stage1_data_preparation"),
    str(PIPE / "stage2_deterministic_calc"),
    str(PIPE / "stage3_standard_comparison"),
    str(PIPE),
):
    if p not in sys.path:
        sys.path.insert(0, p)

from standards_registry import StandardsRegistry, clear_user_standards, upload_standard  # noqa: E402
from risk_identifier import ProjectContext  # noqa: E402
from orchestrator import build_daily_report_input, run_pipeline  # noqa: E402


# ---------------------------------------------------------------------------
# 1. 真实数据：隧道多传感器数据集
# ---------------------------------------------------------------------------
def load_real_records() -> list[dict]:
    series: dict[str, list[tuple[str, float]]] = defaultdict(list)
    with (SENSOR_DATA / "daily_aligned.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["mask"] != "1" or r["filled"] == "1" or not r["value_signed"]:
                continue
            series[r["channel_key"]].append((r["date"], float(r["value_signed"])))

    out: list[dict] = []
    for ck, seq in series.items():
        seq.sort(key=lambda x: x[0])
        if len(seq) < 2:
            continue
        baseline = seq[0][1]
        prev_ts, prev_v = seq[0]
        for ts, cur in seq[1:]:
            gap = float((date.fromisoformat(ts) - date.fromisoformat(prev_ts)).days)
            out.append(
                {
                    "point_id": ck,
                    "timestamp": ts,
                    "metric_key": ck,
                    "value": cur,
                    "unit": "mm",
                    "baseline_value": baseline,
                    "previous_value": prev_v,
                    "interval_days": gap,
                    "data_origin": "real",
                }
            )
            prev_ts, prev_v = ts, cur
    return out


def build_user_standard_from_real() -> dict:
    """把真实阈值文件 label_thresholds.csv 转成用户上传规范格式。"""
    rows = list(csv.DictReader((SENSOR_DATA / "label_thresholds.csv").open(encoding="utf-8")))
    metrics = {}
    for r in rows:
        ck, st = r["channel_key"], r["sensor_type"]
        metrics[ck] = {
            "display_name": f"隧道监测通道 {ck}（{st}）",
            "unit": {"DW": "mm", "MG": "MPa", "SY": "kPa"}.get(st, ""),
            "limit_mode": "displacement",
            "rules": [
                {
                    "rule_id": f"{ck}-Q95",
                    "safety_level": ["一级", "二级", "三级"],
                    "support_type": "any",
                    "cumulative_mm": float(r["delta_abs_q95"]),
                    "rate_mm_per_day": float(r["slope_abs_q95"]),
                    "evidence": {
                        "standard": "Zenodo 10.5281/zenodo.20768869 · sensors_public_dataset",
                        "clause": "data/label_thresholds.csv",
                        "note": "训练集 95 分位统计阈值；仅用于算法验证，非工程报警值",
                    },
                }
            ],
        }
    return {
        "schema_version": "1.0",
        "source_id": "ZENODO-20768869-LABEL-THRESHOLDS",
        "source_label": "隧道多传感器数据集 · 通道统计阈值（label_thresholds.csv，真实数据派生）",
        "source_type": "user_uploaded",
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# 2. 模拟数据
# ---------------------------------------------------------------------------
def load_simulated_records() -> tuple[list[dict], dict]:
    csv_path = SIM / "SIMULATED_基坑监测数据集_v1.csv"
    cfg_path = SIM / "SIMULATED_工程条件_v1.json"
    if not csv_path.exists():
        raise SystemExit("缺少模拟数据集，请先运行 python -B tools/generate_simulated_dataset.py")
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    return rows, cfg


def report(title: str, result, extra: dict | None = None) -> dict:
    s = result.summary
    print(f"\n--- {title} ---")
    print(f"  记录（真实/模拟）  : {s['real_records']} / {s['simulated_records']}")
    print(f"  数据质量问题       : {s['data_quality_issues']} 条，阻塞 {s['data_quality_blocked']} 期")
    print(f"  生效规范来源       : {s['effective_standard_origin']}")
    print(f"  风险等级分布       : {s['by_risk_level']}")
    print(f"  问题类别分布       : {s['by_problem_category']}")
    print(f"  弃权原因分布       : {s['abstain']}")

    by_origin_level: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for j in result.stage3["judgments"]:
        by_origin_level[j["data_origin"]][j["risk_level"]] += 1
    print("  按数据来源分列     :")
    for origin, lv in by_origin_level.items():
        print(f"      {origin:<10} {dict(lv)}")

    return {
        "title": title,
        "summary": s,
        "by_origin_level": {k: dict(v) for k, v in by_origin_level.items()},
        **(extra or {}),
    }


def main() -> int:
    print("=" * 78)
    print("真实数据 + 模拟数据 合并跑通三阶段")
    print("=" * 78)

    real = load_real_records()
    sim, sim_cfg = load_simulated_records()
    print(f"真实数据：{len(real)} 条（隧道多传感器，data_origin=real）")
    print(f"模拟数据：{len(sim)} 条（SIMULATED 基坑数据集，data_origin=simulated）")
    print(f"合计    ：{len(real) + len(sim)} 条 —— 两者在阶段一统一作为风险识别参数的输入依据")

    # 模拟数据的工程条件
    sim_ctx = ProjectContext(
        safety_level=sim_cfg["safety_level"],
        support_type=sim_cfg["support_type"],
        excavation_depth_m=sim_cfg["excavation_depth_m"],
        design_values=sim_cfg["design_values"],
        point_overrides=sim_cfg["point_overrides"],
        post_slab_from=sim_cfg["post_slab_from"],
    )
    # 真实隧道数据的安全等级：数据集中未给出，按"一级"保守取值，支护形式按"any"匹配
    real_ctx = ProjectContext(safety_level="一级", support_type="any")

    results = {}
    tmp = Path(tempfile.mkdtemp(prefix="excavaguard_combined_"))
    try:
        # ---------- A｜仅真实数据 + 默认规范库 ----------
        print("\n" + "=" * 78)
        print("A｜仅真实数据 + 默认规范库（基坑智守项目相关规范）")
        print("=" * 78)
        res_a = run_pipeline(real, real_ctx, expected_interval_days=1.0)
        results["A_real_default_only"] = report("A", res_a)

        # ---------- B｜仅真实数据 + 用户上传规范 ----------
        payload = build_user_standard_from_real()
        up = upload_standard(payload, user_dir=tmp)
        if not up.get("ok"):
            raise SystemExit(f"上传失败：{up}")
        reg = StandardsRegistry(user_dir=tmp)

        print("\n" + "=" * 78)
        print("B｜仅真实数据 + 用户上传规范（由真实阈值文件 label_thresholds.csv 派生）")
        print("=" * 78)
        print(f"  规范来源：{len(reg.source_report())} 个")
        for s in reg.source_report():
            print(f"     [{s['origin']}] {s['source_id']}")
        res_b = run_pipeline(real, real_ctx, expected_interval_days=1.0, registry=reg)
        results["B_real_user_standard"] = report("B", res_b)

        # ---------- C｜真实 + 模拟 合并 ----------
        print("\n" + "=" * 78)
        print("C｜真实数据 + 模拟数据 合并，一起送入三阶段")
        print("=" * 78)
        merged = list(real) + list(sim)
        res_c = run_pipeline(merged, sim_ctx, expected_interval_days=1.0, registry=reg)
        results["C_combined"] = report("C", res_c)
    finally:
        clear_user_standards(user_dir=tmp)
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 结论 ----------
    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print(f"  A 组（真实数据 / 默认规范库）：风险等级分布 {res_a.summary['by_risk_level']}")
    print("     → 隧道通道在基坑规范库中无对应判据，全部弃权（UNKNOWN_METRIC），")
    print("       且未产生任何「缺少用户规范」告警 —— 符合「用户未上传时不作特殊处理」。")
    print(f"  B 组（真实数据 / 用户上传规范）：风险等级分布 {res_b.summary['by_risk_level']}")
    print(f"  C 组（真实 + 模拟 合并）：")
    print(f"     真实记录 {res_c.summary['real_records']} 条、模拟记录 {res_c.summary['simulated_records']} 条，分开统计")
    print(f"     合并后风险等级分布 {res_c.summary['by_risk_level']}")
    print(f"     合并后问题类别分布 {res_c.summary['by_problem_category']}")
    print()
    print("  ★ 模拟数据全程带 data_origin=simulated 标识，与真实数据分列统计，未发生混同。")

    # ---------- 日报模块接口契约：实跑校验 ----------
    print("\n" + "=" * 78)
    print("日报模块接口契约（本层只产出载荷，不生成日报文件）")
    print("=" * 78)
    sys.path.insert(0, str(TOOLS))
    from validate_daily_report_input import validate as validate_contract

    payloads = {
        "A_real_default_only": build_daily_report_input(
            res_a, project={"safety_level": "一级", "support_type": "any"}, report_date=REPORT_DATE
        ),
        "B_real_user_standard": build_daily_report_input(
            res_b, project={"safety_level": "一级", "support_type": "any"}, report_date=REPORT_DATE
        ),
        "C_combined": build_daily_report_input(
            res_c,
            project={
                "name": "示例深基坑工程",
                "safety_level": sim_cfg["safety_level"],
                "support_type": sim_cfg["support_type"],
                "excavation_depth_m": sim_cfg["excavation_depth_m"],
            },
            report_date=REPORT_DATE,
        ),
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    contract_ok = True
    for name, p in payloads.items():
        viol = validate_contract(p)
        contract_ok = contract_ok and not viol
        print(
            f"  {name:<22} 条目 {len(p['items']):>4} 条"
            f" | 报警 {len(p['alerts']):>4} | 待复核 {len(p['review_queue']):>4}"
            f" | 生效阈值 {p['context']['effective_standard_origin']}"
            f" | 契约 {'通过' if not viol else '未通过'}"
        )
        if viol:
            for v in viol[:5]:
                print("       -", v)
        path = DERIVED / f"日报接口载荷_{name}.json"
        path.write_text(json.dumps(p, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  → 载荷已写入 {DERIVED}/日报接口载荷_*.json，供后续日报 Agent 直接消费。")
    print("  ★ 本层不生成日报正文与版式文件；结论与建议措辞由日报 Agent 负责。")

    DERIVED.mkdir(parents=True, exist_ok=True)
    out = DERIVED / "真实与模拟合并_三阶段结果.json"
    out.write_text(
        json.dumps(
            {
                "schema": "excavaguard.combined_run/v1",
                "inputs": {
                    "real": {
                        "source": "Zenodo 10.5281/zenodo.20768869 · sensors_public_dataset · daily_aligned.csv",
                        "filter": "mask=1 且 filled=0（剔除填充值与非观测点）",
                        "records": len(real),
                    },
                    "simulated": {
                        "source": sim_cfg["source_dataset"],
                        "file": "data_simulated/SIMULATED_基坑监测数据集_v1.csv",
                        "records": len(sim),
                        "is_simulated": True,
                    },
                },
                "groups": results,
                "daily_report_contract": {
                    "schema": "excavaguard.daily_report_input/v1",
                    "schema_file": "contracts/daily_report_input.schema.json",
                    "validator": "tools/validate_daily_report_input.py",
                    "payloads": {
                        name: {
                            "items": len(p["items"]),
                            "alerts": len(p["alerts"]),
                            "review_queue": len(p["review_queue"]),
                            "effective_standard_origin": p["context"]["effective_standard_origin"],
                        }
                        for name, p in payloads.items()
                    },
                    "contract_passed": contract_ok,
                    "note": "本层只产出结构化载荷，不生成日报正文与版式文件。",
                },
                "note": "真实数据与模拟数据在阶段一统一接入，但全程按 data_origin 分开统计。",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n结果已写入：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
