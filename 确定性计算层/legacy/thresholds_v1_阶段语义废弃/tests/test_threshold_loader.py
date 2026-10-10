"""
阈值加载器 + 确定性计算 回归测试（仅标准库）。

运行：
    python -B thresholds/tests/test_threshold_loader.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
CONFIG = HERE.parent / "config"
sys.path.insert(0, str(SRC))

from threshold_loader import (  # noqa: E402
    STAGE_GENERIC_DEFAULT,
    STAGE_IMPORTED_STANDARD,
    STAGE_PROJECT_SPECIFIC,
    ThresholdConfig,
    ThresholdError,
)
from deterministic_calc import compute_metrics, judge  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail and not cond else ""))


# ---------------------------------------------------------------------------
print("\n=== 1. 阶段1：通用默认阈值加载 ===")
cfg = ThresholdConfig(config_dir=CONFIG)
rep = cfg.stage_report()
check("默认仅加载 1 个来源（阶段1）", len(rep) == 1, str(rep))
check("阶段1 stage=1", rep[0]["stage"] == STAGE_GENERIC_DEFAULT)
check("阶段1 来源为 GB50497-2019", rep[0]["source_id"] == "GB50497-2019", rep[0]["source_id"])
check("监测项数量 >= 18", len(cfg.metric_keys()) >= 18, str(len(cfg.metric_keys())))
check("默认区间策略为 conservative", cfg.range_resolution == "conservative", cfg.range_resolution)

# ---------------------------------------------------------------------------
print("\n=== 2. 解析：一级 + 地下连续墙 + H=20m ===")
t1 = cfg.resolve("wall_top_horizontal_displacement", "一级", "地下连续墙", excavation_depth_m=20.0)
d1 = t1.to_dict()
check("命中规则 WTHD-L1-PILE", t1.rule_id == "WTHD-L1-PILE", str(t1.rule_id))
check("累计取严=20mm", t1.cumulative_limit_mm == 20.0, str(t1.cumulative_limit_mm))
# %H: 0.2% * 20m * 1000 = 40mm；min(20, 40) = 20
check("累计基准为 min(absolute, pct_H)", t1.cumulative_basis == "min(absolute, pct_H)", str(t1.cumulative_basis))
check("速率取严=2mm/d", t1.rate_limit_mm_per_day == 2.0, str(t1.rate_limit_mm_per_day))
check("来源阶段=1", d1["threshold_source_stage"] == 1)
check("来源标签=GB 50497-2019", "GB 50497-2019" in d1["threshold_source_label"])
check("无覆盖字段", t1.overrides == [], str(t1.overrides))

print("\n=== 3. %H 起作用：H=5m（0.2%H=10mm < 20mm）===")
t2 = cfg.resolve("wall_top_horizontal_displacement", "一级", "地下连续墙", excavation_depth_m=5.0)
check("累计限值取 %H 的 10mm", t2.cumulative_limit_mm == 10.0, str(t2.cumulative_limit_mm))
check("累计基准仍为 min", t2.cumulative_basis == "min(absolute, pct_H)")

print("\n=== 4. H 未知时退化并标记 ===")
t3 = cfg.resolve("wall_top_horizontal_displacement", "一级", "地下连续墙", excavation_depth_m=None)
check("H 未知时用绝对值 20mm", t3.cumulative_limit_mm == 20.0, str(t3.cumulative_limit_mm))
check("标记 PCT_H_NOT_EVALUATED", "PCT_H_NOT_EVALUATED" in t3.flags, str(t3.flags))

print("\n=== 5. 不同安全等级/支护形式 ===")
t_l3 = cfg.resolve("wall_top_horizontal_displacement", "三级", "土钉墙", excavation_depth_m=20.0)
check("三级土钉墙累计=50mm", t_l3.cumulative_limit_mm == 50.0, str(t_l3.cumulative_limit_mm))
t_l2 = cfg.resolve("deep_horizontal_displacement", "二级", "钢板桩", excavation_depth_m=15.0)
check("二级钢板桩深层位移=60mm", t_l2.cumulative_limit_mm == 60.0, str(t_l2.cumulative_limit_mm))

print("\n=== 6. 比值类阈值（支撑轴力）===")
t_saf = cfg.resolve("support_axial_force", "一级", "地下连续墙", excavation_depth_m=20.0)
check("支撑轴力上限比=0.60", t_saf.max_ratio_of_design == 0.60, str(t_saf.max_ratio_of_design))
check("limit_mode=max_ratio", t_saf.limit_mode == "max_ratio")

print("\n=== 7. 无适用规则时弃权 ===")
t_none = cfg.resolve("column_internal_force", "一级", "地下连续墙", excavation_depth_m=20.0)
check("立柱内力无规则 -> NO_APPLICABLE_RULE", "NO_APPLICABLE_RULE" in t_none.flags, str(t_none.flags))

# ---------------------------------------------------------------------------
print("\n=== 8. 阶段2 / 阶段3 优先级覆盖 ===")
tmp = Path(tempfile.mkdtemp(prefix="thr_"))
imp = tmp / "project_thresholds"
shutil.copytree(CONFIG / "project_thresholds", imp)
# 让示例文件生效：去掉 .example
for f in imp.glob("*.example.json"):
    f.rename(imp / f.name.replace(".example.json", ".json"))

cfg3 = ThresholdConfig(config_dir=CONFIG, import_dirs=[imp])
rep3 = cfg3.stage_report()
check("加载 3 个来源（1/2/3）", len(rep3) == 3, str([r["stage"] for r in rep3]))
check("阶段递增排序", [r["stage"] for r in rep3] == [1, 2, 3], str([r["stage"] for r in rep3]))

t_prj = cfg3.resolve("wall_top_horizontal_displacement", "一级", "地下连续墙", excavation_depth_m=20.0)
d_prj = t_prj.to_dict()
check("阶段3 覆盖后累计=25mm", t_prj.cumulative_limit_mm == 25.0, str(t_prj.cumulative_limit_mm))
check("阶段3 覆盖后速率=2mm/d", t_prj.rate_limit_mm_per_day == 2.0, str(t_prj.rate_limit_mm_per_day))
check("生效阶段=3", d_prj["threshold_source_stage"] == STAGE_PROJECT_SPECIFIC, str(d_prj["threshold_source_stage"]))
check("生效阶段显示为第三阶段", "第三阶段" in d_prj["threshold_source_stage_display"])
check("生效来源为专项方案", "专项方案" in d_prj["threshold_source_label"])
check("记录了被覆盖字段", set(["cumulative_mm", "rate_mm_per_day"]).issubset(set(t_prj.overrides)), str(t_prj.overrides))

t_gwl = cfg3.resolve("groundwater_level", "一级", "地下连续墙", excavation_depth_m=20.0)
check("阶段2 覆盖水位速率=300", t_gwl.rate_limit_mm_per_day == 300.0, str(t_gwl.rate_limit_mm_per_day))
check("水位生效阶段=2", t_gwl.to_dict()["threshold_source_stage"] == STAGE_IMPORTED_STANDARD)

t_dhd = cfg3.resolve("deep_horizontal_displacement", "一级", "地下连续墙", excavation_depth_m=20.0)
check("阶段3 补充了深层位移速率=2", t_dhd.rate_limit_mm_per_day == 2.0, str(t_dhd.rate_limit_mm_per_day))
check("深层位移生效阶段=3", t_dhd.to_dict()["threshold_source_stage"] == STAGE_PROJECT_SPECIFIC)

# ---------------------------------------------------------------------------
print("\n=== 9. 确定性计算 ===")
calc = compute_metrics(
    "wall_top_horizontal_displacement",
    current=28.0,
    baseline=0.0,
    previous=25.0,
    interval_days=1.0,
    point_id="ZQT-01",
    timestamp="2026-10-09",
)
check("累计=28.0", calc.cumulative == 28.0, str(calc.cumulative))
check("本次变化量=3.0", calc.single_change == 3.0, str(calc.single_change))
check("速率=3.0", calc.rate == 3.0, str(calc.rate))
check("无弃权", calc.ok(), str(calc.abstain))

calc_missing = compute_metrics("wall_top_horizontal_displacement", current=28.0, previous=None)
check("缺上次值 -> MISSING_PREVIOUS", "MISSING_PREVIOUS" in calc_missing.abstain, str(calc_missing.abstain))

calc_no_int = compute_metrics("wall_top_horizontal_displacement", current=28.0, previous=25.0, interval_days=0)
check("间隔=0 -> INVALID_INTERVAL", "INVALID_INTERVAL" in calc_no_int.abstain, str(calc_no_int.abstain))

# ---------------------------------------------------------------------------
print("\n=== 10. 阈值校核与风险分级 ===")
j = judge(calc, t1)
check("超限=True（累计28>20）", j.exceeded, json.dumps(j.checks, ensure_ascii=False))
check("风险等级=报警", j.risk_level == "报警", j.risk_level)
check("判定携带阶段1来源", j.threshold_source_stage == 1)
check("判定携带来源标签", "GB 50497-2019" in (j.threshold_source_label or ""))
check("trace 含规则ID", j.trace.get("rule_id") == "WTHD-L1-PILE")

j2 = judge(calc, t_prj)
check("阶段3阈值(25mm)下 28mm 仍超限", j2.exceeded)
check("阶段3 判定来源阶段=3", j2.threshold_source_stage == 3)

calc_ok = compute_metrics("wall_top_horizontal_displacement", current=5.0, baseline=0.0, previous=4.5, interval_days=1.0)
j3 = judge(calc_ok, t1)
check("小幅变化 -> 正常", j3.risk_level == "正常", j3.risk_level)
check("未超限", not j3.exceeded)

calc_mid = compute_metrics("wall_top_horizontal_displacement", current=12.0, baseline=0.0, previous=11.0, interval_days=1.0)
j4 = judge(calc_mid, t1)
check("利用率 60% -> 关注", j4.risk_level == "关注", j4.risk_level)

calc_warn = compute_metrics("wall_top_horizontal_displacement", current=16.0, baseline=0.0, previous=15.0, interval_days=1.0)
j5 = judge(calc_warn, t1)
check("利用率 80% -> 预警", j5.risk_level == "预警", j5.risk_level)

# ---------------------------------------------------------------------------
print("\n=== 11. 导入文件校验 ===")
bad = {"stage": 9, "source_id": "", "metrics": {"x": {"rules": [{"safety_level": ["四级"]}]}}}
problems = cfg.validate_import(bad)
check("非法 stage 被识别", any("stage 必须为 2" in p for p in problems), str(problems))
check("缺 source_id 被识别", any("source_id" in p for p in problems))
check("非法安全等级被识别", any("safety_level 只允许" in p for p in problems))

good = {
    "schema_version": "1.0",
    "stage": 3,
    "source_id": "PRJ-X",
    "source_label": "某项目专项方案",
    "metrics": {
        "wall_top_horizontal_displacement": {
            "rules": [
                {
                    "rule_id": "R1",
                    "safety_level": ["一级"],
                    "cumulative_mm": 25,
                    "evidence": {"standard": "某项目专项方案", "clause": "5.3"},
                }
            ]
        }
    },
}
check("合法文件校验通过", cfg.validate_import(good) == [], str(cfg.validate_import(good)))

# ---------------------------------------------------------------------------
print("\n=== 12. 危险报警条件 ===")
check("内置 7 条 GB50497 危险报警条件", len(cfg.danger_alarm_conditions) >= 7, str(len(cfg.danger_alarm_conditions)))
check("阶段2/3 追加后 >= 8 条", len(cfg3.danger_alarm_conditions) >= 8, str(len(cfg3.danger_alarm_conditions)))
check("含 JGJ120 补充报警条件", len(cfg.mandatory_alarm_supplement) >= 7)

# ---------------------------------------------------------------------------
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{'=' * 60}")
print(f"PASS: {len(PASS)}   FAIL: {len(FAIL)}")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print("全部通过")
