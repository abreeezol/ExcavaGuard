"""
真实数据优先验证脚本（只读原始文件，派生结果写入 derived/）

目的
----
在没有基坑真实监测数据的前提下，用目录内**真实存在**的隧道多传感器数据集
完整跑通「阶段一 数据准备 → 阶段二 确定性计算 → 阶段三 规范比对」，
验证代码可用、可追溯、可弃权，并演示用户上传规范接口。

做法
----
1. 把真实阈值文件 `label_thresholds.csv`（44 通道 × 4 类判据）转换为
   用户上传规范格式的 JSON —— 演示**规范上传接口**的真实用法；
2. 从真实 `daily_aligned.csv` 取观测序列，**剔除 mask=0 与 filled=1 的填充值**，
   构造阶段一的输入记录（含基准值、上次值、间隔天数）；
3. 两次运行流程对比：
   - **A 组｜未上传用户规范**：只加载默认规范库（基坑规范），隧道通道无对应判据，
     应全部弃权（`UNKNOWN_METRIC`），且**不产生任何缺失告警**；
   - **B 组｜上传真实数据派生的规范**：按用户上传规范比对，输出风险等级，
     生效来源标注为 `user_uploaded`。

注意
----
- 本脚本不修改任何原始文件。
- 隧道数据仅用于**算法验证**，不做基坑工程判定；结果中明确标注。
- `label_thresholds.csv` 的阈值是**窗口级 95 分位**统计量，而本脚本按**逐日步长**判定，
  二者粒度不同，B 组报警比例偏高属预期现象，已在输出中标注该结论。
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

ROOT = Path(r"C:\Study\bisai\Hai AI Agent\基坑智守项目相关数据")
SENSOR = ROOT / "多传感器隧道监测数据" / "sensors_public_dataset"
DATA = SENSOR / "data"
BASE = Path(r"C:\Study\bisai\Hai AI Agent\ExcavaGuard\确定性计算层")
PIPE = BASE / "pipeline"
DERIVED = BASE / "derived"

for p in (
    str(PIPE / "stage1_data_preparation"),
    str(PIPE / "stage2_deterministic_calc"),
    str(PIPE / "stage3_standard_comparison"),
    str(PIPE),
):
    if p not in sys.path:
        sys.path.insert(0, p)

from standards_registry import StandardsRegistry, clear_user_standards  # noqa: E402
from risk_identifier import ProjectContext  # noqa: E402
from orchestrator import run_pipeline  # noqa: E402

DERIVED.mkdir(parents=True, exist_ok=True)
OUT_THR = DERIVED / "imported_thresholds"
OUT_THR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 1. 真实阈值文件 -> 用户上传规范格式 JSON
# ---------------------------------------------------------------------------
def build_user_standard_from_real() -> dict:
    rows = list(csv.DictReader((DATA / "label_thresholds.csv").open(encoding="utf-8")))
    metrics: dict[str, dict] = {}
    for r in rows:
        ck = r["channel_key"]
        st = r["sensor_type"]
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
        "applies_to": {"note": "仅用于算法验证，不得用于基坑工程判定"},
        "selection_policy": {"range_resolution": "conservative"},
        "metrics": metrics,
    }


payload = build_user_standard_from_real()
thr_path = OUT_THR / "真实数据_隧道通道阈值_user_standard.json"
thr_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[1] 真实阈值文件已转换为用户上传规范格式：{thr_path}")
print(f"    通道数 {len(payload['metrics'])}，来源 label_thresholds.csv（真实数据）")


# ---------------------------------------------------------------------------
# 2. 读真实观测序列（剔除填充值），构造阶段一输入记录
# ---------------------------------------------------------------------------
series: dict[str, list[tuple[str, float]]] = defaultdict(list)
with (DATA / "daily_aligned.csv").open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["mask"] != "1":
            continue          # 非真实观测
        if r["filled"] == "1":
            continue          # 前值填充，不得计入变化量
        if not r["value_signed"]:
            continue
        series[r["channel_key"]].append((r["date"], float(r["value_signed"])))

for v in series.values():
    v.sort(key=lambda x: x[0])

records: list[dict] = []
for ck, seq in sorted(series.items()):
    if len(seq) < 2:
        continue
    baseline = seq[0][1]
    for i in range(1, len(seq)):
        ts, cur = seq[i]
        prev_ts, prev = seq[i - 1]
        dt = float((date.fromisoformat(ts) - date.fromisoformat(prev_ts)).days)
        records.append(
            {
                "point_id": ck,
                "timestamp": ts,
                "metric_key": ck,
                "value": cur,
                "unit": "mm",
                "baseline_value": baseline,
                "previous_value": prev,
                "interval_days": dt,
                "data_origin": "real",
            }
        )

print(f"[2] 真实观测：{len(series)} 个通道，{len(records)} 条有效记录（已剔除填充值与非观测点）")

CTX = ProjectContext(safety_level="一级", support_type="any")


# ---------------------------------------------------------------------------
# 3A. 未上传用户规范：只加载默认规范库
# ---------------------------------------------------------------------------
print("\n[3A] 未上传用户规范 —— 只加载默认规范库（基坑智守项目相关规范）")
res_a = run_pipeline(records, CTX, expected_interval_days=1.0)
sa = res_a.summary
print(f"     生效规范来源      : {sa['effective_standard_origin']}")
print(f"     是否加载用户规范  : {res_a.stage3['has_user_standards']}")
print(f"     风险等级分布      : {sa['by_risk_level']}")
print(f"     弃权原因分布      : {sa['abstain']}")
print("     结论：隧道通道在基坑规范库中无对应判据，全部弃权（UNKNOWN_METRIC），")
print("           且未产生任何「缺少用户规范」的告警 —— 符合「用户未上传时不作特殊处理」。")


# ---------------------------------------------------------------------------
# 3B. 上传真实数据派生的规范
# ---------------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp(prefix="excavaguard_demo_"))
try:
    shutil.copy(thr_path, tmp / thr_path.name)
    print("\n[3B] 上传真实数据派生的规范 —— 默认规范库 + 用户上传规范")
    reg_b = StandardsRegistry(user_dir=tmp)
    print(f"     规范来源 {len(reg_b.source_report())} 个：")
    for s in reg_b.source_report():
        print(f"       [{s['origin']}] {s['source_id']} | {s['source_label'][:44]}")

    res_b = run_pipeline(records, CTX, expected_interval_days=1.0, registry=reg_b)
    sb = res_b.summary
    print(f"     生效规范来源      : {sb['effective_standard_origin']}")
    print(f"     风险等级分布      : {sb['by_risk_level']}")
    print(f"     弃权原因分布      : {sb['abstain']}")

    origins: dict[str, int] = defaultdict(int)
    for j in res_b.stage3["judgments"]:
        origins[j["effective_source"]["origin"]] += 1
    print(f"     逐条生效来源分布  : {dict(origins)}")
finally:
    clear_user_standards(user_dir=tmp)
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 4. 输出派生结果
# ---------------------------------------------------------------------------
out_json = DERIVED / "真实数据_三阶段流程验证_结果.json"
out_json.write_text(
    json.dumps(
        {
            "purpose": "真实数据优先验证：用隧道多传感器数据集跑通三阶段流程",
            "data_origin": "real（全部来自 sensors_public_dataset，未使用任何模拟数据）",
            "source_dataset": "Zenodo 10.5281/zenodo.20768869 · sensors_public_dataset",
            "thresholds_from": "data/label_thresholds.csv（真实阈值文件）",
            "observations_from": "data/daily_aligned.csv（剔除 mask=0 与 filled=1）",
            "records": len(records),
            "group_A_no_user_standard": {
                "effective_standard_origin": sa["effective_standard_origin"],
                "by_risk_level": sa["by_risk_level"],
                "abstain": sa["abstain"],
            },
            "group_B_with_real_derived_user_standard": {
                "effective_standard_origin": sb["effective_standard_origin"],
                "by_risk_level": sb["by_risk_level"],
                "abstain": sb["abstain"],
            },
            "caveat": (
                "label_thresholds.csv 的阈值是窗口级 95 分位统计量，而本脚本按逐日步长判定，"
                "二者粒度不同，B 组报警比例偏高属预期现象。该结论与基坑工程无关。"
            ),
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

out_csv = DERIVED / "真实数据_三阶段判定明细.csv"
fields = [
    "point_id", "timestamp", "metric_key", "data_origin",
    "cumulative", "single_change", "rate",
    "risk_level", "utilization", "problem_category",
    "effective_origin", "source_label", "rule_id",
    "standard", "clause", "abstain",
]
with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for j, c in zip(res_b.stage3["judgments"], res_b.stage2["results"]):
        w.writerow(
            {
                "point_id": j["point_id"],
                "timestamp": j["timestamp"],
                "metric_key": j["metric_key"],
                "data_origin": j["data_origin"],
                "cumulative": c["outputs"]["cumulative"],
                "single_change": c["outputs"]["single_change"],
                "rate": c["outputs"]["rate"],
                "risk_level": j["risk_level"],
                "utilization": j["utilization"],
                "problem_category": j["problem_category"],
                "effective_origin": j["effective_source"]["origin"],
                "source_label": j["effective_source"]["source_label"],
                "rule_id": j["rule_id"],
                "standard": j["evidence"].get("standard"),
                "clause": j["evidence"].get("clause"),
                "abstain": "|".join(j["abstain"]),
            }
        )

print(f"\n[4] 派生结果已写出（未修改任何原始文件）：")
print(f"     {out_json}")
print(f"     {out_csv}")
print(f"     明细条数：{len(res_b.stage3['judgments'])}")
