"""
三阶段流程回归测试（仅标准库）。

运行：
    python -B pipeline/tests/test_pipeline_stages.py

覆盖：
    阶段一 · 数据准备   —— 归一化、单位换算、噪音/缺失识别、真实与模拟分开统计
    阶段二 · 确定性计算 —— 四项核心计算、弃权码
    阶段三 · 规范比对   —— 风险分级、生效规范来源、用户上传覆盖、未上传时不作特殊处理
    编排层              —— 端到端 + 健壮性验证 + 日报接口契约
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
sys.path.insert(0, str(PIPE / "stage1_data_preparation"))
sys.path.insert(0, str(PIPE / "stage2_deterministic_calc"))
sys.path.insert(0, str(PIPE / "stage3_standard_comparison"))
sys.path.insert(0, str(PIPE))

from ingest import normalize_records, origin_statistics          # noqa: E402
from ingest import (                                             # noqa: E402
    BASELINE_DERIVED,
    INTERVAL_DERIVED,
    PREVIOUS_DERIVED,
    build_metric_aliases,
    derive_temporal_fields,
    normalize_metric_name,
)
from file_reader import (                                        # noqa: E402
    read_monitoring_file,
    map_header,
    detect_delimiter,
)
from quality_scan import scan_records                            # noqa: E402
from calculator import compute, cumulative_value, rate_value     # noqa: E402
from standards_registry import (                                 # noqa: E402
    ORIGIN_DEFAULT,
    ORIGIN_USER,
    StandardsRegistry,
    clear_user_standards,
    upload_standard,
)
from risk_identifier import (                                   # noqa: E402
    ProjectContext,
    judge,
    resolve_limit,
    summarize,
)
from orchestrator import (                                       # noqa: E402
    DAILY_REPORT_SCHEMA,
    PipelineResult,
    build_daily_report_input,
    run_pipeline,
    run_robustness_check,
)

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail and not cond else ""))


# ---------------------------------------------------------------------------
# 测试数据（干净的真实结构样例）
# ---------------------------------------------------------------------------

def clean_records() -> list[dict]:
    """ZQS-01 墙顶水平位移，一级基坑、地下连续墙、H=20m。"""
    rows = []
    vals = [0.0, 4.0, 9.0, 16.0, 20.0, 26.0]
    for i, v in enumerate(vals):
        rows.append(
            {
                "point_id": "ZQS-01",
                "timestamp": f"2026-09-{10 + i:02d}",
                "metric_key": "wall_top_horizontal_displacement",
                "value": v,
                "unit": "mm",
                "baseline_value": 0.0,
                "previous_value": vals[i - 1] if i else None,
                "interval_days": 1.0 if i else None,
            }
        )
    return rows


CTX = ProjectContext(
    safety_level="一级",
    support_type="地下连续墙",
    excavation_depth_m=20.0,
)


# ===========================================================================
print("\n=== 阶段一 · 数据准备 ===")

recs = normalize_records(clean_records(), default_origin="real")
check("归一化条数正确", len(recs) == 6, f"实际 {len(recs)}")
check("真实数据全部标记为 real", origin_statistics(recs) == {"real": 6}, str(origin_statistics(recs)))

cm = normalize_records([{**clean_records()[1], "unit": "cm", "value": 1.6}])
check("单位换算 cm→mm 生效", cm[0].value == 16.0, f"实际 {cm[0].value}")

bad = normalize_records(
    [
        {**clean_records()[1], "value": "N/A"},
        {**clean_records()[1], "timestamp": "昨天"},
        {**clean_records()[1], "unit": "厘米"},
    ]
)
codes = {f for r in bad for f in r.flags}
check("非数值被标记", "NON_NUMERIC_VALUE" in codes, str(codes))
check("日期无法解析被标记", "UNPARSED_TIMESTAMP" in codes, str(codes))
check("单位无法识别被标记", "UNSUPPORTED_UNIT" in codes, str(codes))

q = scan_records(recs)
check("干净数据不产生高中危问题", q.by_severity.get("高", 0) == 0, str(q.by_severity))
check("真实/模拟分开统计", (q.real_records, q.simulated_records) == (6, 0))


# ===========================================================================
print("\n=== 阶段二 · 确定性计算 ===")

c = compute(
    metric_key="wall_top_horizontal_displacement",
    current=16.0,
    baseline=0.0,
    previous=9.0,
    interval_days=1.0,
    point_id="ZQS-01",
    timestamp="2026-09-13",
)
check("累计值 = 16.0", c.cumulative == 16.0, str(c.cumulative))
check("本次变化量 = 7.0", c.single_change == 7.0, str(c.single_change))
check("变化速率 = 7.0 mm/d", c.rate == 7.0, str(c.rate))
check("结果可计算（无弃权）", c.ok, str(c.abstain))

check("累计值公式对负数成立", cumulative_value(-5.0, 0.0) == (-5.0, None))
check("缺基准值则弃权", cumulative_value(5.0, None) == (None, "MISSING_BASELINE"))
check("间隔为 0 则速率弃权", rate_value(7.0, 0.0) == (None, "INVALID_INTERVAL"))

c2 = compute(metric_key="x", current=10.0, baseline=None, previous=None, interval_days=None)
check(
    "多缺项时给出多个弃权码",
    set(c2.abstain) == {"MISSING_BASELINE", "MISSING_PREVIOUS"},
    str(c2.abstain),
)
c2b = compute(metric_key="x", current=10.0, baseline=0.0, previous=9.0, interval_days=0.0)
check("间隔为 0 单独弃权", c2b.abstain == ["INVALID_INTERVAL"], str(c2b.abstain))

# y = 0,4,9,16 的最小二乘斜率 = 5.3 mm/d（加速趋势）
hist = [(0, 0.0), (1, 4.0), (2, 9.0), (3, 16.0)]
c3 = compute(metric_key="x", current=16.0, baseline=0.0, previous=9.0, interval_days=1.0, history=hist)
check("趋势斜率可计算", c3.slope is not None and abs(c3.slope - 5.3) < 1e-6, str(c3.slope))


# ===========================================================================
print("\n=== 阶段三 · 规范比对（默认规范库） ===")

reg = StandardsRegistry()
check("默认规范库已加载", len(reg.sources) >= 1, str(reg.source_report()))
check("默认未上传用户规范", reg.has_user_standards() is False)
check("规范库索引可用", (reg.index_summary() or {}).get("total") == 30, str(reg.index_summary()))

# 一级 / 地下连续墙：累计限值 min(20mm, 0.2%×20m=40mm) = 20mm；速率限值 2 mm/d
# 令 previous = current，使速率项为 0，单独校核累计值这一路判据
for cum, expect in [(6.0, "正常"), (12.0, "关注"), (16.0, "预警"), (20.0, "报警"), (26.0, "危险报警")]:
    calc = compute(
        metric_key="wall_top_horizontal_displacement",
        current=cum,
        baseline=0.0,
        previous=cum,
        interval_days=1.0,
        point_id="ZQS-01",
    )
    j = judge(calc, reg, CTX)
    check(f"累计 {cum}mm → {expect}", j.risk_level == expect, f"实际 {j.risk_level}, u={j.utilization}")

j = judge(
    compute("wall_top_horizontal_displacement", 16.0, 0.0, 15.0, 1.0, point_id="ZQS-01"),
    reg,
    CTX,
)
check("生效规范来源 = 默认规范库", j.effective_source["origin"] == ORIGIN_DEFAULT, str(j.effective_source))
check("生效规范来源展示文案正确", "默认规范库" in j.effective_source["origin_display"])
check("证据出自 GB 50497-2019", j.evidence.get("standard") == "GB 50497-2019", str(j.evidence))
check("条文出处为表8.0.4", j.evidence.get("clause") == "表8.0.4", str(j.evidence))

# 变化速率校核
jr = judge(compute("wall_top_horizontal_displacement", 5.0, 0.0, 3.0, 1.0, point_id="P1"), reg, CTX)
rate_check = next((x for x in jr.checks if x["check"] == "变化速率"), None)
check("速率校核项存在", rate_check is not None)
check("速率 3mm/d / 限值 2mm/d = 报警", rate_check and rate_check["verdict"] == "报警", str(rate_check))

# 底板浇筑后速率限值 ×0.7
ctx_slab = ProjectContext(safety_level="一级", support_type="地下连续墙", excavation_depth_m=20.0, post_slab=True)
js = judge(compute("wall_top_horizontal_displacement", 5.0, 0.0, 3.2, 1.0, point_id="P1"), reg, ctx_slab)
sc = next(x for x in js.checks if x["check"] == "变化速率")
check("底板浇筑后速率限值折减为 1.4mm/d", abs(sc["limit"] - 1.4) < 1e-6, str(sc))
check("折减后触发 POST_SLAB_RATE_REDUCED 标记", "POST_SLAB_RATE_REDUCED" in js.flags, str(js.flags))

# 连续 3 次超过限值 70%
ctx_h = ProjectContext(
    safety_level="一级",
    support_type="地下连续墙",
    excavation_depth_m=20.0,
    rate_history={"P2": [1.5, 1.6, 1.5]},
)
jh = judge(compute("wall_top_horizontal_displacement", 5.0, 0.0, 3.4, 1.0, point_id="P2"), reg, ctx_h)
hc = next(x for x in jh.checks if x["check"] == "变化速率")
check("连续3次超70%触发预警", hc.get("consecutive_over_70") is True, str(hc))

# 危险报警条件（GB 50497-2019 8.0.9 强制性条文）
ctx_d = ProjectContext(
    safety_level="一级",
    support_type="地下连续墙",
    excavation_depth_m=20.0,
    danger_signals={"DANGER-1": True},
)
jd = judge(compute("wall_top_horizontal_displacement", 1.0, 0.0, 0.5, 1.0, point_id="P3"), reg, ctx_d)
check("危险报警条件命中 → 危险报警", jd.risk_level == "危险报警", str(jd.risk_level))

# 支护受力异常：支撑轴力按设计值比例
ctx_f = ProjectContext(safety_level="一级", support_type="地下连续墙", design_values={"support_axial_force": 1000.0})
jf = judge(compute("support_axial_force", 700.0, baseline=600.0, previous=650.0, interval_days=1.0, point_id="ZL-01"), reg, ctx_f)
check("支撑轴力 700kN / (1000×0.6) → 预警及以上", jf.risk_level in ("预警", "报警", "危险报警"), str(jf.risk_level))
check("支撑轴力归属问题类别=支护受力异常", jf.problem_category == "支护受力异常", jf.problem_category)

jf2 = judge(compute("support_axial_force", 700.0, baseline=600.0, previous=650.0, interval_days=1.0, point_id="ZL-01"), reg, ProjectContext(safety_level="一级"))
check("缺设计值时弃权并给出原因", "MISSING_DESIGN_VALUE" in jf2.abstain, str(jf2.abstain))

# 渗漏水与地下水异常
jg = judge(compute("groundwater_level", -1500.0, baseline=0.0, previous=-1000.0, interval_days=1.0, point_id="SW-01"), reg, CTX)
check("地下水位归属问题类别=渗漏水与地下水异常", jg.problem_category == "渗漏水与地下水异常", jg.problem_category)

# 未知监测项弃权
ju = judge(compute("not_a_metric", 1.0, baseline=0.0, previous=0.5, interval_days=1.0), reg, CTX)
check("未知监测项弃权", "UNKNOWN_METRIC" in ju.abstain, str(ju.abstain))


# ===========================================================================
print("\n=== 阶段三 · 用户上传规范 ===")

tmp = Path(tempfile.mkdtemp(prefix="excavaguard_user_"))
try:
    payload = {
        "source_id": "USER-LOCAL-2026",
        "source_label": "某地方规程示例（用户上传）",
        "source_type": "local_code",
        "metrics": {
            "wall_top_horizontal_displacement": {
                "rules": [
                    {
                        "rule_id": "USER-WTHD-L1",
                        "safety_level": ["一级"],
                        "support_type": ["地下连续墙"],
                        "cumulative_mm": 15,
                        "rate_mm_per_day": 1,
                        "evidence": {"standard": "某地方规程示例", "clause": "第 5.2.1 条"},
                    }
                ]
            }
        },
    }
    up = upload_standard(payload, user_dir=tmp)
    check("用户上传成功", up.get("ok") is True, str(up))

    reg2 = StandardsRegistry(user_dir=tmp)
    check("识别到用户上传规范", reg2.has_user_standards() is True)
    ju2 = judge(compute("wall_top_horizontal_displacement", 16.0, baseline=0.0, previous=15.0, interval_days=1.0, point_id="ZQS-01"), reg2, CTX)
    check("用户规范覆盖后来源=用户上传规范", ju2.effective_source["origin"] == ORIGIN_USER, str(ju2.effective_source))
    check("用户规范展示文案正确", ju2.effective_source["origin_display"] == "用户上传规范")
    check("用户规范 source_label 正确", ju2.effective_source["source_label"] == "某地方规程示例（用户上传）")
    check("用户规范限值 15mm 生效 → 报警", ju2.risk_level == "报警", f"{ju2.risk_level} u={ju2.utilization}")

    # 未列出的字段继承默认规范库（覆盖不清空）
    check("覆盖字段被记录", "cumulative_mm" in ju2.effective_source["overridden_fields"], str(ju2.effective_source["overridden_fields"]))

    bad_up = upload_standard({"source_id": "", "metrics": {}}, user_dir=tmp)
    check("非法上传被拒绝", bad_up.get("ok") is False and len(bad_up["problems"]) > 0, str(bad_up))

    clear_user_standards(user_dir=tmp)
    reg3 = StandardsRegistry(user_dir=tmp)
    check("清空后回到默认规范库", reg3.has_user_standards() is False)
    jd2 = judge(compute("wall_top_horizontal_displacement", 16.0, baseline=0.0, previous=15.0, interval_days=1.0, point_id="ZQS-01"), reg3, CTX)
    check("未上传用户规范时静默使用默认库（无告警字段）", jd2.effective_source["origin"] == ORIGIN_DEFAULT)
    check("未上传时无 USER_STANDARD_MISSING 之类标记", not any("MISSING_USER" in f for f in jd2.flags), str(jd2.flags))
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
print("\n=== 新增能力 · 单位量纲 / 间隔 / 逐测点条件 / 浇筑后折减 / 不收敛 / 质量阻塞 ===")

from ingest import normalize_value_unit  # noqa: E402
from risk_identifier import (  # noqa: E402
    BLOCKING_ISSUE_CODES,
    _non_convergent,
)

check("kN 单位不再被误判", normalize_value_unit(700.0, "kN")[2] == [], str(normalize_value_unit(700.0, "kN")))
check("无量纲单位原样保留", normalize_value_unit(0.0024, "1")[2] == [], str(normalize_value_unit(0.0024, "1")))
check("cm 换算到 mm", normalize_value_unit(1.6, "cm")[0] == 16.0, str(normalize_value_unit(1.6, "cm")))
check("MPa 换算到 kPa", normalize_value_unit(1.5, "MPa")[0] == 1500.0, str(normalize_value_unit(1.5, "MPa")))
check("未知单位仍被标记", normalize_value_unit(1.0, "mm/s")[2] == ["UNSUPPORTED_UNIT"])
check("温度单位 ℃ 不报错且原样保留", normalize_value_unit(18.5, "℃") == (18.5, "℃", []),
      str(normalize_value_unit(18.5, "℃")))
check("温度单位 °C 不报错", normalize_value_unit(18.5, "°C")[2] == [], str(normalize_value_unit(18.5, "°C")))
check("温度值不做换算", normalize_value_unit(18.5, "℃")[0] == 18.5)

hr = normalize_records([{"point_id": "P", "timestamp": "2026-09-10", "metric_key": "x", "value": 1.0, "unit": "mm", "interval_hours": 12}])
check("interval_hours 转为天", hr[0].interval_days == 0.5, str(hr[0].interval_days))

ctx_crack = ProjectContext(
    safety_level="一级",
    support_type="地下连续墙",
    excavation_depth_m=20.0,
    point_overrides={"LF-01": {"crack_state": "既有裂缝"}, "LF-02": {"crack_state": "新增裂缝"}},
)
j_old = judge(compute("crack_width_building", 1.8, baseline=0.0, previous=1.7, interval_days=1.0, point_id="LF-01"), reg, ctx_crack)
j_new = judge(compute("crack_width_building", 0.5, baseline=0.0, previous=0.4, interval_days=1.0, point_id="LF-02"), reg, ctx_crack)
check("逐测点条件覆盖生效（既有裂缝限值 1.5）", j_old.checks and abs(j_old.checks[0]["limit"] - 1.5) < 1e-9, str(j_old.checks[:1]))
check("逐测点条件覆盖生效（新增裂缝限值 0.2）", j_new.checks and abs(j_new.checks[0]["limit"] - 0.2) < 1e-9, str(j_new.checks[:1]))

ctx_slab_date = ProjectContext(safety_level="一级", support_type="地下连续墙", excavation_depth_m=20.0, post_slab_from="2026-09-09")
j_pre = judge(compute("wall_top_horizontal_displacement", 3.0, 0.0, 1.6, 1.0, point_id="P", timestamp="2026-09-01"), reg, ctx_slab_date)
j_post = judge(compute("wall_top_horizontal_displacement", 3.0, 0.0, 1.6, 1.0, point_id="P", timestamp="2026-09-20"), reg, ctx_slab_date)
pre_limit = next(x for x in j_pre.checks if x["check"] == "变化速率")["limit"]
post_limit = next(x for x in j_post.checks if x["check"] == "变化速率")["limit"]
check("浇筑前速率限值 2.0", abs(pre_limit - 2.0) < 1e-9, str(pre_limit))
check("浇筑后速率限值 1.4", abs(post_limit - 1.4) < 1e-9, str(post_limit))

check("加速序列判为不收敛", _non_convergent(0.44, 0.22) is True)
check("收敛序列不判不收敛", _non_convergent(0.05, 0.30) is False)
j_nc = judge(
    compute("wall_top_horizontal_displacement", 13.0, 0.0, 12.56, 1.0, point_id="P", history=[(i, 13 * (i / 59) ** 2) for i in range(60)]),
    reg,
    ProjectContext(safety_level="一级", support_type="地下连续墙", excavation_depth_m=20.0),
)
check("不收敛触发 NON_CONVERGENT 标记", "NON_CONVERGENT" in j_nc.flags, str(j_nc.flags))
check("不收敛至少升级为预警", j_nc.risk_level in ("预警", "报警", "危险报警"), j_nc.risk_level)

# 空值与非数值必须区分：空值属缺测（中），非数值属格式错误（高、阻塞）
r_missing = normalize_records([{"point_id": "P", "timestamp": "2026-09-10", "metric_key": "x", "value": None, "unit": "mm"}])[0]
r_badstr = normalize_records([{"point_id": "P", "timestamp": "2026-09-10", "metric_key": "x", "value": "N/A", "unit": "mm"}])[0]
check("空值不标记为非数值", "NON_NUMERIC_VALUE" not in r_missing.flags, str(r_missing.flags))
check("非数值字符串被标记", "NON_NUMERIC_VALUE" in r_badstr.flags, str(r_badstr.flags))
q_missing = scan_records([r_missing])
check("空值识别为 MISSING_VALUE", q_missing.by_code.get("MISSING_VALUE") == 1, str(q_missing.by_code))
check("空值不产生 NON_NUMERIC_VALUE", "NON_NUMERIC_VALUE" not in q_missing.by_code, str(q_missing.by_code))

# 粗差 vs 真实台阶跳变：孤立尖峰才算粗差，台阶跳变属真实变形
def _mk(vals):
    return normalize_records(
        [
            {"point_id": "S", "timestamp": f"2026-09-{10 + i:02d}", "metric_key": "x", "value": v, "unit": "mm"}
            for i, v in enumerate(vals)
        ]
    )


q_spike = scan_records(_mk([5.0, 5.2, 95.0, 5.6, 5.8, 6.0]))
check("孤立尖峰被判为 OUTLIER", q_spike.by_code.get("OUTLIER", 0) >= 1, str(q_spike.by_code))
q_step = scan_records(_mk([5.0, 5.2, 7.6, 7.8, 8.0, 8.2]))
check("台阶跳变不判为粗差（真实突变不应被屏蔽）", "OUTLIER" not in q_step.by_code, str(q_step.by_code))
q_trend = scan_records(_mk([float(i * i) / 10 for i in range(12)]))
check("加速趋势尾部不判为粗差", "OUTLIER" not in q_trend.by_code, str(q_trend.by_code))

check("阻塞问题码含 OUTLIER", "OUTLIER" in BLOCKING_ISSUE_CODES)
check("阻塞问题码含 FLATLINE", "FLATLINE" in BLOCKING_ISSUE_CODES)
j_blk = judge(
    compute("wall_top_horizontal_displacement", 95.0, 0.0, 6.0, 1.0, point_id="ZQS-10", timestamp="2026-09-05"),
    reg,
    ProjectContext(safety_level="一级", support_type="地下连续墙", excavation_depth_m=20.0),
    blocked_issues=["OUTLIER"],
)
check("数据质量问题记录弃权", "DATA_QUALITY_BLOCKED" in j_blk.abstain, str(j_blk.abstain))
check("数据质量问题记录等级为未知", j_blk.risk_level == "未知", j_blk.risk_level)
check("数据质量问题记录归入数据质量异常", j_blk.problem_category == "数据质量异常", j_blk.problem_category)
check("粗差不再被误判为危险报警", j_blk.risk_level != "危险报警")


# ===========================================================================
print("\n=== 编排层 · 端到端 ===")

result = run_pipeline(clean_records(), CTX, expected_interval_days=1.0)
check("三阶段均产出", all([result.stage1, result.stage2, result.stage3]))
check("阶段一名称为数据准备", result.stage1["stage"].startswith("阶段一"), result.stage1["stage"])
check("阶段二名称为确定性计算", result.stage2["stage"].startswith("阶段二"), result.stage2["stage"])
check("阶段三名称为规范比对", result.stage3["stage"].startswith("阶段三"), result.stage3["stage"])
check("真实数据计数正确", result.summary["real_records"] == 6, str(result.summary["real_records"]))
check("模拟数据计数为 0", result.summary["simulated_records"] == 0)
check("生效规范来源=默认规范库", result.summary["effective_standard_origin"] == "default_library")
check("汇总含风险等级分布", "by_risk_level" in result.summary)
check("汇总含问题类别分布", "by_problem_category" in result.summary)

rep_in = build_daily_report_input(result)
check("日报接口输出 schema 正确", rep_in["schema"] == "excavaguard.daily_report_input/v1")
check("日报接口含逐条结论", len(rep_in["items"]) == 6, str(len(rep_in["items"])))
check("日报接口标注数据来源", rep_in["context"]["real_records"] == 6)


# ===========================================================================
print("\n=== 模拟数据 · 健壮性验证 ===")

rb = run_robustness_check(clean_records() * 10, "heavy", source_dataset="TEST-CLEAN", ctx=CTX)
check("健壮性验证不崩溃", "result" in rb)
check("注入后的数据全部标记为 simulated", rb["pipeline_summary"]["simulated_records"] > 0, str(rb["pipeline_summary"]))
check("真实数据计数归零（注入后全部为模拟）", rb["pipeline_summary"]["real_records"] == 0)
rows = rb["robustness"]["rows"]
detected_any = [r["detected_as"] for r in rows if r["detected"] > 0]
check("至少识别出 3 类注入噪音", len(detected_any) >= 3, str(detected_any))
missing_row = next(r for r in rows if r["detected_as"] == "MISSING_VALUE")
check("空值被识别", missing_row["detected"] > 0, str(missing_row))
nn_row = next(r for r in rows if r["detected_as"] == "NON_NUMERIC_VALUE")
check("格式不一致被识别", nn_row["detected"] > 0, str(nn_row))
check("结果标注了模拟用途说明", "健壮性" in rb["purpose"], rb["purpose"])


# ===========================================================================
print("\n=== 日报模块接口契约 ===")

# --- 契约文件本身 ---
SCHEMA_PATH = PIPE.parent / "contracts" / "daily_report_input.schema.json"
check("契约 schema 文件存在", SCHEMA_PATH.exists(), str(SCHEMA_PATH))
schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
check("契约 $id 与代码常量一致", schema["$id"] == DAILY_REPORT_SCHEMA, schema.get("$id"))
check("契约声明了明细必填字段", "item" in schema["$defs"] and len(schema["$defs"]["item"]["required"]) >= 20)

# --- 载荷结构 ---
CONTRACT_TOP = [
    "schema", "contract", "generated_from", "project", "context", "standards_sources",
    "data_quality", "summary", "alerts", "review_queue", "standard_override_warnings",
    "items", "disclaimer", "note",
]
check("载荷顶层键与契约一致", set(rep_in.keys()) == set(CONTRACT_TOP), str(sorted(set(rep_in.keys()) ^ set(CONTRACT_TOP))))
check("载荷契约自述含消费方", "日报" in rep_in["contract"]["consumer"], rep_in["contract"]["consumer"])
check("载荷声明不含日报正文", "日报正文" in rep_in["contract"]["excludes"], str(rep_in["contract"]["excludes"]))
check("载荷声明阈值生效阶段", rep_in["context"]["effective_standard_stage"] == "阶段三 · 规范比对")
check("载荷声明真实数据为主依据", rep_in["context"]["real_is_primary"] is True)

# --- 工程概况：注入生效、未提供补 null、不臆造 ---
p2 = build_daily_report_input(
    result,
    project={"name": "示例基坑工程", "excavation_depth_m": 12.0},
    points_meta={"ZQS-01": {"point_name": "墙顶水平位移 1 号点", "point_type": "墙顶位移"}},
    report_date="2026-08-07",
)
check("工程概况注入生效", p2["project"]["name"] == "示例基坑工程")
check("未提供字段补 null 而非臆造", p2["project"]["monitoring_unit"] is None)
check("报告日期注入生效", p2["project"]["report_date"] == "2026-08-07")
check("测点台账注入生效", any(it["point_name"] == "墙顶水平位移 1 号点" for it in p2["items"]))
check("未注入台账时测点名为 null", rep_in["items"][0]["point_name"] is None)

# --- 明细字段齐备与语义 ---
item_req = schema["$defs"]["item"]["required"]
missing = [k for k in item_req if k not in rep_in["items"][0]]
check("明细必填字段齐备", not missing, str(missing))
check("明细含中文监测项名称", rep_in["items"][0]["metric_name"] != rep_in["items"][0]["metric_key"],
      rep_in["items"][0]["metric_name"])
check("明细判定与自身计算对齐（未串行）",
      all(it["point_id"] == j["point_id"] for it, j in zip(rep_in["items"], result.stage3["judgments"])))
check("明细 needs_review 与 abstain 一致",
      all(it["needs_review"] == bool(it["abstain"]) for it in rep_in["items"]))

# --- 报警清单 / 复核队列 ---
check("报警清单只含报警及以上",
      all(it["risk_level"] in ("报警", "危险报警") for it in p2["alerts"]), str([it["risk_level"] for it in p2["alerts"]]))
check("报警清单是 items 的子集",
      all(it in p2["items"] for it in p2["alerts"]))
check("复核队列等于 needs_review 条目",
      len(p2["review_queue"]) == sum(1 for it in p2["items"] if it["needs_review"]))
check("汇总含整体风险等级", "overall_risk_level" in p2["summary"])

# --- 位置错位容错：stage2 结果顺序被打乱时不得串行 ---
disordered = PipelineResult(
    stage1=result.stage1,
    stage2={"results": list(reversed(result.stage2["results"]))},   # 故意倒序
    stage3=result.stage3,
    summary=result.summary,
)
shuffled = build_daily_report_input(disordered)
check("阶段二结果乱序时不发生串行",
      all(it["point_id"] == j["point_id"] for it, j in zip(shuffled["items"], result.stage3["judgments"])))
check("阶段二结果乱序时计算值仍对应正确测点",
      [it["cumulative"] for it in shuffled["items"]] == [it["cumulative"] for it in rep_in["items"]])

# --- 可序列化与整体契约校验 ---
check("载荷可 JSON 序列化", bool(json.dumps(p2, ensure_ascii=False, default=str)))
try:
    from validate_daily_report_input import validate as _contract_validate
except ModuleNotFoundError:
    sys.path.insert(0, str(PIPE.parent / "tools"))
    from validate_daily_report_input import validate as _contract_validate
viol = _contract_validate(p2)
check("载荷通过契约校验", not viol, "; ".join(viol[:5]))


# ===========================================================================
print("\n=== 用户数据文件契约 · 读取 / 别名 / 时序派生 ===")

import csv as _csv  # noqa: E402


def _write(tmp: Path, name: str, text: str, encoding: str = "utf-8-sig") -> Path:
    p = tmp / name
    p.write_text(text, encoding=encoding)
    return p


_tmpdir = Path(tempfile.mkdtemp(prefix="eg_contract_"))

# --- 编码探测 ---
_p_gbk = _tmpdir / "gbk.csv"
_p_gbk.write_bytes(
    "测点编号,观测日期,监测项目,本次观测值,单位,方向\n"
    "WTHD-01,2026-08-01,围护墙顶部水平位移,0.0,mm,正\n".encode("gbk")
)
_recs, _rep = read_monitoring_file(_p_gbk)
check("GBK 中文表头文件可读取", _rep["ok"] and len(_recs) == 1, str(_rep.get("errors")))
check("GBK 被正确探测（gb18030 兼容）", _rep["encoding"] in ("gbk", "gb18030"), _rep["encoding"])
check("中文表头被映射到规范字段", _rep["mapped_columns"].get(0) == "point_id", str(_rep["mapped_columns"]))

# --- 表头别名 ---
_idx, _f2i, _unmapped = map_header(["测点", "日期", "监测项", "数值", "单位", "备注"])
check("中文表头别名全部命中",
      set(_f2i) >= {"point_id", "timestamp", "metric", "value", "unit"}, str(_f2i))
check("未识别列被记录而非丢弃", "备注" in _unmapped or "note" in _f2i, str(_unmapped))
_idx2, _f2i2, _ = map_header(["point", "date", "metric_key", "value", "unit", "interval_hours"])
check("英文表头别名全部命中", set(_f2i2) >= {"point_id", "timestamp", "metric", "value", "unit"}, str(_f2i2))
check("分隔符可自动识别（制表符）", detect_delimiter("a\tb\tc") == "\t")

# --- 必填列缺失应拒收 ---
_p_bad = _write(_tmpdir, "missing.csv", "测点编号,日期,数值\nP1,2026-08-01,1.0\n")
_recs_bad, _rep_bad = read_monitoring_file(_p_bad)
check("缺必填列时拒收", _rep_bad["ok"] is False and not _recs_bad)
check("缺列清单准确", set(_rep_bad["missing_required"]) == {"metric", "unit"}, str(_rep_bad["missing_required"]))

# --- 可派生列缺失不影响读取 ---
_p_min = _write(_tmpdir, "minimal.csv",
                "point_id,timestamp,metric,value,unit\n"
                "P1,2026-08-01,wall_top_horizontal_displacement,0,mm\n")
_recs_min, _rep_min = read_monitoring_file(_p_min)
check("只有 5 个必填列也能读取", _rep_min["ok"] and len(_recs_min) == 1)
check("可派生列缺失被标注", _rep_min["derivable_columns_present"] == [], str(_rep_min["derivable_columns_present"]))

# --- 监测项名称归一与别名 ---
check("监测项名称归一去掉括号内容",
      normalize_metric_name("围护墙（边坡）顶部水平位移") == "围护墙顶部水平位移",
      normalize_metric_name("围护墙（边坡）顶部水平位移"))
_aliases = build_metric_aliases(StandardsRegistry().display_names())
check("规范库标准名可映射", _aliases.get("围护墙（边坡）顶部水平位移") == "wall_top_horizontal_displacement")
check("去掉括号的简写也可映射", _aliases.get("围护墙顶部水平位移") == "wall_top_horizontal_displacement")
check("常见俗称可映射（测斜）", _aliases.get("测斜") == "deep_horizontal_displacement")
check("metric_key 自身可映射", _aliases.get("support_axial_force") == "support_axial_force")

# --- 时序派生 ---
_raw_min = [
    {"point_id": "P1", "timestamp": f"2026-08-0{i}", "metric_key": "wall_top_horizontal_displacement",
     "value": v, "unit": "mm"}
    for i, v in enumerate([0.0, 5.0, 12.0, 22.0], start=1)
]
_norm_min = normalize_records(_raw_min)
_stats = derive_temporal_fields(_norm_min)
check("派生初始值 = 首期有效观测", _norm_min[0].baseline_value == 0.0, str(_norm_min[0].baseline_value))
check("同测点后续记录继承派生初始值", _norm_min[3].baseline_value == 0.0)
check("派生上次值 = 前一期有效观测", _norm_min[3].previous_value == 12.0, str(_norm_min[3].previous_value))
check("派生观测间隔 = 1 天", _norm_min[3].interval_days == 1.0, str(_norm_min[3].interval_days))
check("首期无上次值（保持 None）", _norm_min[0].previous_value is None)
check("首期无间隔（保持 None）", _norm_min[0].interval_days is None)
check("派生统计正确",
      _stats["baseline_derived"] == 4 and _stats["previous_derived"] == 3 and _stats["interval_derived"] == 3,
      str(_stats))
check("派生字段带 BASELINE_DERIVED 标记", BASELINE_DERIVED in _norm_min[0].flags, str(_norm_min[0].flags))
check("派生字段带 PREVIOUS/INTERVAL 标记",
      PREVIOUS_DERIVED in _norm_min[3].flags and INTERVAL_DERIVED in _norm_min[3].flags)

# --- 显式提供的值不被覆盖 ---
_norm_expl = normalize_records([
    {"point_id": "P2", "timestamp": "2026-08-01", "metric_key": "m", "value": 10.0, "unit": "mm",
     "baseline_value": 100.0},
    {"point_id": "P2", "timestamp": "2026-08-02", "metric_key": "m", "value": 12.0, "unit": "mm",
     "baseline_value": 100.0, "previous_value": 10.0, "interval_days": 1.0},
])
derive_temporal_fields(_norm_expl)
check("显式初始值不被派生覆盖", _norm_expl[0].baseline_value == 100.0, str(_norm_expl[0].baseline_value))
check("显式上次值不被派生覆盖", _norm_expl[1].previous_value == 10.0, str(_norm_expl[1].previous_value))
check("显式间隔不被派生覆盖", _norm_expl[1].interval_days == 1.0)

# --- 缺测期不参与派生（间隔按真实天数） ---
_norm_gap = normalize_records([
    {"point_id": "P3", "timestamp": "2026-08-01", "metric_key": "m", "value": 0.0, "unit": "mm"},
    {"point_id": "P3", "timestamp": "2026-08-02", "metric_key": "m", "value": None, "unit": "mm"},
    {"point_id": "P3", "timestamp": "2026-08-04", "metric_key": "m", "value": 6.0, "unit": "mm"},
])
derive_temporal_fields(_norm_gap)
check("空值不参与派生（上次值取前一有效观测）", _norm_gap[2].previous_value == 0.0, str(_norm_gap[2].previous_value))
check("跨缺测的间隔按真实天数（3 天）", _norm_gap[2].interval_days == 3.0, str(_norm_gap[2].interval_days))

# --- 端到端：用户视角的最小原始表 ---
_p_e2e = _tmpdir / "e2e_gbk.csv"
_p_e2e.write_bytes(
    ("测点编号,观测日期,监测项目,本次观测值,单位,方向\n" + "".join(
        f"WTHD-01,2026-08-0{i},{'围护墙顶部水平位移'},{v},mm,正\n"
        for i, v in enumerate([0.0, 5.0, 12.0, 22.0, 35.0, 52.0, 60.0], start=1)
    )).encode("gbk")
)
_recs_e2e, _rep_e2e = read_monitoring_file(_p_e2e)
_res_e2e = run_pipeline(_recs_e2e, CTX)
check("端到端：中文GBK原始表可进管线", _rep_e2e["ok"] and _res_e2e.stage2["calc_count"] == 7)
check("端到端：监测项被映射为 metric_key",
      _res_e2e.stage2["results"][-1]["metric_key"] == "wall_top_horizontal_displacement",
      _res_e2e.stage2["results"][-1]["metric_key"])
check("端到端：不再因缺基准值而全量弃权", _res_e2e.stage2["abstain_count"] == 1,
      f"弃权 {_res_e2e.stage2['abstain_count']}/7")
check("端到端：识别出危险报警", _res_e2e.summary["by_risk_level"].get("危险报警") == 6,
      str(_res_e2e.summary["by_risk_level"]))
check("端到端：结论带规范条文出处",
      _res_e2e.stage3["judgments"][-1]["evidence"].get("standard") == "GB 50497-2019",
      str(_res_e2e.stage3["judgments"][-1]["evidence"]))
check("端到端：派生标记透传到判定结果",
      BASELINE_DERIVED in _res_e2e.stage3["judgments"][-1]["flags"],
      str(_res_e2e.stage3["judgments"][-1]["flags"]))
check("端到端：阶段一输出派生统计", _res_e2e.stage1["derived_fields"]["baseline_derived"] == 7,
      str(_res_e2e.stage1.get("derived_fields")))

shutil.rmtree(_tmpdir, ignore_errors=True)


# ===========================================================================
print("\n=== 用户阈值宽松度校验 ===")

from limit_strictness import (                                   # noqa: E402
    INCOMPARABLE_FLAG,
    LOOSER_FLAG,
    compare_rule_strictness,
    find_default_rule,
    format_report,
    summarize,
)

_reg = StandardsRegistry()
_ctx20 = ProjectContext(safety_level="一级", support_type="地下连续墙", excavation_depth_m=20.0)
_ctx_noH = ProjectContext(safety_level="一级", support_type="地下连续墙")
_DEF_WTHD = {
    "rule_id": "WTHD-L1-PILE",
    "cumulative_mm": {"min": 20, "max": 30},
    "cumulative_pct_H": {"min": 0.2, "max": 0.3},
    "rate_mm_per_day": {"min": 2, "max": 3},
    "evidence": {"standard": "GB 50497-2019", "clause": "表8.0.4"},
}


def _cmp(user_rule, ctx=_ctx20, base=_DEF_WTHD):
    """模拟真实调用：取值来自「默认规则 + 用户覆盖」的合并结果，范围限用户给出的字段。"""
    merged = {**base, **user_rule}
    return compare_rule_strictness("wall_top_horizontal_displacement", user_rule, base,
                                   _reg, ctx, metric_name="围护墙（边坡）顶部水平位移",
                                   default_evidence=base["evidence"],
                                   effective_rule=merged, scope_fields=set(user_rule))


def _only(comps, direction):
    return [c for c in comps if c["direction"] == direction]


# --- 方向正确性：位移类放宽 → 告警；收紧 → 不告警 ---
_c_loose = _cmp({"cumulative_mm": {"min": 50, "max": 60}})
check("累计值放宽被识别", len(_only(_c_loose, "looser")) == 1, str(_c_loose))
check("放宽幅度按合并后有效限值计算（min(50,继承40)=40 vs 20 → +100%）",
      abs(_only(_c_loose, "looser")[0]["delta_pct"] - 100.0) < 0.01,
      str(_only(_c_loose, "looser")[0].get("delta_pct")))
check("放宽严重度分级为严重", _only(_c_loose, "looser")[0]["severity"] == "严重")
_c_tight = _cmp({"cumulative_mm": {"min": 10, "max": 15}})
check("累计值收紧不告警", not _only(_c_tight, "looser"), str(_c_tight))
check("收紧被标为 stricter", _only(_c_tight, "stricter"))
_c_equal = _cmp({"rate_mm_per_day": {"min": 2, "max": 3}})
check("完全相等不告警", not _only(_c_equal, "looser"), str(_c_equal))

# --- 有效限值口径：调宽绝对量但 %H 更严，有效限值可能未变 ---
_c_mixed = _cmp({"cumulative_mm": {"min": 50, "max": 60}, "cumulative_pct_H": {"min": 0.1, "max": 0.1}})
check("调宽绝对量但收紧 %H：有效限值 20 vs 20 → 不算放宽",
      not _only(_c_mixed, "looser"), str(_c_mixed))
check("有效限值比较标注了口径", "min(绝对量" in (_only(_c_mixed, "equal")[0]["default_basis"] if _only(_c_mixed, "equal") else ""),
      str(_only(_c_mixed, "equal")))

# --- ★ 反向字段：min_ratio_of_design（预应力下限，越大越严） ---
_def_anchor = {"rule_id": "AAF-L1", "min_ratio_of_design": {"min": 0.8, "max": 1.0},
               "evidence": {"standard": "GB 50497-2019", "clause": "表8.0.4"}}
_c_down = compare_rule_strictness("anchor_axial_force", {"min_ratio_of_design": {"min": 0.5, "max": 0.6}},
                                  _def_anchor, _reg, _ctx20, metric_name="锚杆轴力",
                                  default_evidence=_def_anchor["evidence"])
check("★预应力下限调小 = 更宽松 → 告警", len(_only(_c_down, "looser")) == 1, str(_c_down))
_c_up = compare_rule_strictness("anchor_axial_force", {"min_ratio_of_design": {"min": 0.9, "max": 1.0}},
                                _def_anchor, _reg, _ctx20, metric_name="锚杆轴力",
                                default_evidence=_def_anchor["evidence"])
check("★预应力下限调大 = 更严格 → 不告警", not _only(_c_up, "looser"), str(_c_up))

# --- 只比较用户覆盖的字段 ---
_c_partial = _cmp({"rate_mm_per_day": {"min": 5, "max": 6}})
check("只比较用户给出的字段", len(_c_partial) == 1, str(_c_partial))
check("未给出的字段不产生比较项", all(c["field"] == "rate_mm_per_day" for c in _c_partial), str(_c_partial))

# --- 缺 H 时不可比，而不是"未放宽" ---
_c_noh = _cmp({"cumulative_mm": {"min": 50, "max": 60}}, ctx=_ctx_noH)
check("缺 H 时累计值判为不可比", len(_only(_c_noh, "incomparable")) >= 1, str(_c_noh))
check("缺 H 时不产生 looser（不静默放过）", not _only(_c_noh, "looser"), str(_c_noh))
_c_noh_rate = _cmp({"rate_mm_per_day": {"min": 5, "max": 6}}, ctx=_ctx_noH)
check("速率类不依赖 H，缺 H 仍能判定", len(_only(_c_noh_rate, "looser")) == 1, str(_c_noh_rate))

# --- 无对应默认判据 → 不告警 ---
_dr, _how = find_default_rule(_reg, "soil_temperature", {"rule_id": "X"}, "X")
check("默认库无对应判据时返回 None", _dr is None, _how)
check("并给出原因", "新增判据" in _how or "没有" in _how, _how)

# --- 严重度分级 ---
check("放宽 3% → 轻微",
      _cmp({"rate_mm_per_day": {"min": 2.06, "max": 3}})[0].get("severity") == "轻微",
      str(_cmp({"rate_mm_per_day": {"min": 2.06, "max": 3}})[0].get("severity")))
check("放宽 10% → 中等",
      _cmp({"rate_mm_per_day": {"min": 2.2, "max": 3}})[0].get("severity") == "中等")
check("放宽 25% → 严重",
      _cmp({"rate_mm_per_day": {"min": 2.5, "max": 3}})[0].get("severity") == "严重")

# --- 报告文本含规范依据 ---
_txt = format_report(_only(_c_loose, "looser"))
check("反馈文本含规范名称", "GB 50497-2019" in _txt, _txt[:80])
check("反馈文本含条文号", "表8.0.4" in _txt)
check("反馈文本含用户值与默认值", "50.0" in _txt or "40.0" in _txt)
check("反馈文本含限值推导过程", "min(绝对量" in _txt)

# --- 集成：上传接口 ---
_up_tmp = Path(tempfile.mkdtemp(prefix="eg_strict_"))
_up_payload = {
    "source_id": "USER-CORP-STD-2026",
    "source_label": "XX企业基坑监测标准（用户上传）",
    "source_type": "user_uploaded",
    "metrics": {"wall_top_horizontal_displacement": {"rules": [{
        "rule_id": "WTHD-L1-PILE", "safety_level": ["一级"], "support_type": ["地下连续墙"],
        "cumulative_mm": {"min": 50, "max": 60}, "rate_mm_per_day": {"min": 5, "max": 6},
        "evidence": {"standard": "XX企业基坑监测标准", "clause": "5.2.1"}}]}},
}
_up = upload_standard(_up_payload, user_dir=_up_tmp, ctx=_ctx20)
check("上传成功且返回严格度结果", _up["ok"] and "strictness" in _up, str(_up)[:200])
check("上传结果检出 2 处放宽", _up["strictness"]["looser_count"] == 2, str(_up["strictness"]["looser_count"]))
check("上传结果带可展示报告", "更宽松" in _up.get("strictness_report", ""), _up.get("strictness_report", "")[:60])
check("放宽项带默认规范依据",
      all(c["default_evidence"].get("standard") == "GB 50497-2019" for c in _up["strictness"]["looser"]))

# --- 集成：判定结果带标记 ---
_user_reg = StandardsRegistry(user_dir=_up_tmp)
_min_raw = [{"point_id": "W1", "timestamp": f"2026-08-0{i}", "metric_key": "wall_top_horizontal_displacement",
             "value": v, "unit": "mm"} for i, v in enumerate([0.0, 5.0, 12.0, 22.0, 35.0, 52.0, 60.0], start=1)]
_r_def = run_pipeline(_min_raw, _ctx20)
_r_usr = run_pipeline(_min_raw, _ctx20, registry=_user_reg)
check("默认库下末条为危险报警", _r_def.stage3["judgments"][-1]["risk_level"] == "危险报警")
check("用户放宽阈值后判定结果带 LOOSER 标记",
      LOOSER_FLAG in _r_usr.stage3["judgments"][-1]["flags"],
      str(_r_usr.stage3["judgments"][-1]["flags"]))
check("标记只出现在用户规范生效时",
      LOOSER_FLAG not in _r_def.stage3["judgments"][-1]["flags"])
check("生效来源标注为用户上传", _r_usr.summary["effective_standard_origin"] == "user_uploaded")
check("looser_details 透传到 effective_source",
      len(_r_usr.stage3["judgments"][-1]["effective_source"]["looser_details"]) == 2)

# --- 集成：日报载荷 ---
_p_usr = build_daily_report_input(_r_usr, report_date="2026-08-07")
check("载荷含 standard_override_warnings", len(_p_usr["standard_override_warnings"]) >= 1,
      str(len(_p_usr["standard_override_warnings"])))
_w = _p_usr["standard_override_warnings"][0]
check("告警含监测项名称", bool(_w["metric_name"]), str(_w.get("metric_name")))
check("告警含差异明细", len(_w["differences"]) == 2, str(len(_w["differences"])))
check("差异含用户值/默认值/严重度",
      all(k in _w["differences"][0] for k in ("user_value", "default_value", "severity")),
      str(_w["differences"][0].keys()))
check("差异含默认规范条文依据",
      _w["differences"][0]["default_evidence"].get("standard") == "GB 50497-2019")
check("载荷仍通过契约校验", not _contract_validate(_p_usr), str(_contract_validate(_p_usr))[:200])
check("未放宽时载荷为空列表",
      build_daily_report_input(_r_def)["standard_override_warnings"] == [])
shutil.rmtree(_up_tmp, ignore_errors=True)


# ===========================================================================
print("\n" + "=" * 70)
print("缺 H 的累计值判定（安全边界：不得用绝对量替代 min(绝对量, %H)）")
print("=" * 70)

_reg_h = StandardsRegistry()
_ctx_h5 = ProjectContext(safety_level="一级", support_type="地下连续墙", excavation_depth_m=5.0)
_ctx_noh = ProjectContext(safety_level="一级", support_type="地下连续墙", excavation_depth_m=None)

_lim_h5 = resolve_limit(_reg_h, "wall_top_horizontal_displacement", _ctx_h5)
_lim_noh = resolve_limit(_reg_h, "wall_top_horizontal_displacement", _ctx_noh)

check("有 H：累计值限值取 min(绝对量 20, 0.2%×5m=10)", _lim_h5.cumulative_mm == 10.0,
      str(_lim_h5.cumulative_mm))
check("有 H：不带上界标记", _lim_h5.cumulative_upper_bound_only is False)
check("缺 H：绝对量仅作为上界", _lim_noh.cumulative_upper_bound_only is True, str(_lim_noh))
check("缺 H：打 MISSING_H 标记", "MISSING_H" in _lim_noh.flags, str(_lim_noh.flags))
check("缺 H：限值依据明说是上界", "上界" in (_lim_noh.cumulative_basis or ""))
check("缺 H：上界值等于绝对量 20 mm", _lim_noh.cumulative_mm == 20.0, str(_lim_noh.cumulative_mm))

# 慢速增长：累计 13.5 mm、速率 1.5 mm/d（低于速率限值 2 mm/d），
# 使"累计值"成为唯一能给出结论的校核项
_slow = [
    {"point_id": "W1", "timestamp": f"2026-08-{i:02d}",
     "metric_key": "wall_top_horizontal_displacement", "value": v, "unit": "mm"}
    for i, v in enumerate([0, 1.5, 3.0, 4.5, 6.0, 7.5, 9.0, 10.5, 12.0, 13.5], start=1)
]
_j_h5 = run_pipeline(_slow, _ctx_h5).stage3["judgments"][-1]
_j_noh = run_pipeline(_slow, _ctx_noh).stage3["judgments"][-1]

check("有 H：13.5 mm 超 10 mm → 危险报警", _j_h5["risk_level"] == "危险报警", _j_h5["risk_level"])
check("有 H：不产生 MISSING_H 弃权", "MISSING_H" not in _j_h5["abstain"], str(_j_h5["abstain"]))

_cum_noh = next(c for c in _j_noh["checks"] if c["check"].startswith("累计值"))
check("缺 H：累计值不给出等级结论", _cum_noh["verdict"] == "未知", str(_cum_noh["verdict"]))
check("缺 H：累计值标记为上界判定", _cum_noh.get("limit_is_upper_bound") is True, str(_cum_noh.keys()))
check("缺 H：记录 MISSING_H 弃权", "MISSING_H" in _j_noh["abstain"], str(_j_noh["abstain"]))
check("缺 H：打 H_MISSING_CUMULATIVE_ABSTAINED 标记",
      "H_MISSING_CUMULATIVE_ABSTAINED" in _j_noh["flags"], str(_j_noh["flags"]))
check("缺 H：不得因缺 H 而被判为正常", _j_noh["risk_level"] != "正常", _j_noh["risk_level"])

# 关键安全性质：实测值已超绝对量上界 → 真实限值更小 → 超限结论必然成立
_j_over = run_pipeline(
    [{"point_id": "W1", "timestamp": f"2026-08-{i:02d}",
      "metric_key": "wall_top_horizontal_displacement", "value": v, "unit": "mm"}
     for i, v in enumerate([0, 3, 6, 9, 12, 15, 18, 21, 24, 27], start=1)],
    _ctx_noh,
).stage3["judgments"][-1]
check("缺 H 但已超上界：仍给出超限结论", _j_over["risk_level"] == "危险报警", _j_over["risk_level"])
check("缺 H 但已超上界：不再弃权 MISSING_H", "MISSING_H" not in _j_over["abstain"], str(_j_over["abstain"]))

# 唯一校核弃权 + 其余校核判"正常" → 必须降级为未知，而不是放过
_flat = judge(
    compute("wall_top_horizontal_displacement", 13.5, baseline=0.0, previous=13.5,
            interval_days=1.0, point_id="W1", timestamp="2026-08-10"),
    _reg_h, _ctx_noh,
)
check("缺 H 且速率正常：整体降级为未知（不判正常）", _flat.risk_level == "未知", _flat.risk_level)
check("缺 H 降级时保留 MISSING_H 弃权", "MISSING_H" in _flat.abstain, str(_flat.abstain))

# 载荷侧：MISSING_H 必须进入人工复核队列
_p_noh = build_daily_report_input(run_pipeline(_slow, _ctx_noh), report_date="2026-08-10")
check("缺 H 项进入复核队列", len(_p_noh["review_queue"]) >= 1, str(len(_p_noh["review_queue"])))
check("复核项带 MISSING_H 弃权原因",
      any("MISSING_H" in (it.get("abstain") or []) for it in _p_noh["review_queue"]),
      str([it.get("abstain") for it in _p_noh["review_queue"]][:3]))
check("缺 H 载荷仍通过契约校验", not _contract_validate(_p_noh), str(_contract_validate(_p_noh))[:200])


# ===========================================================================
print("\n" + "=" * 70)
print(f"PASS: {len(PASS)}    FAIL: {len(FAIL)}")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print("全部通过")
