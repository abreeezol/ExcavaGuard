"""隧道判定能力回归：管理等级 / 收敛稳定 / 断面综合判定

覆盖 2026-11 新增的三项能力。阈值一律来自判据库，测试里用临时库构造，
不把任何工程数字写进代码 —— 真实判据见 `standards/tunnel/thresholds_tunnel_2013.json`。

运行：`python -B scenarios/tests/test_tunnel_judgement.py`
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2]
for sub in (
    "pipeline",
    "pipeline/stage1_data_preparation",
    "pipeline/stage2_deterministic_calc",
    "pipeline/stage3_standard_comparison",
    "scenarios",
):
    p = ENGINE / sub
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import scenario as sp  # noqa: E402
from convergence import (  # noqa: E402
    STATUS_INSUFFICIENT,
    STATUS_NO_CRITERION,
    STATUS_NOT_SATISFIED,
    STATUS_SATISFIED,
    evaluate_management_level,
    evaluate_stability,
)
from section_judge import SECTION_INCOMPLETE, build_section_map, judge_sections  # noqa: E402
from dataclasses import replace  # noqa: E402

PASS = FAIL = 0
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"[FAIL] {name}  {detail}")


CRIT = {
    "rate_mm_per_day": {"min": 0.1, "max": 0.2},
    "consecutive_periods": 3,
    "evidence": {"standard": "TEST", "clause": "T-1"},
}

print("\n=== 收敛稳定 / 可停测量化条件 ===")
r = evaluate_stability(None, [], current_rate=0.05)
check("无判据 → no_criterion", r["status"] == STATUS_NO_CRITERION, str(r["status"]))
check("无判据不输出阈值", r["threshold"] is None)

r = evaluate_stability(CRIT, [("2026-11-01", 0.02)], current_rate=0.04)
check("区间取严 → 阈值 0.1", r["threshold"] == 0.1, str(r["threshold"]))
check("期数不足 → insufficient", r["status"] == STATUS_INSUFFICIENT, str(r["status"]))
check("期数不足披露已观测速率", r["observed_rates"] == [0.02, 0.04], str(r["observed_rates"]))

hist = [("2026-11-01", 0.02), ("2026-11-02", 0.05), ("2026-11-03", 0.03)]
r = evaluate_stability(CRIT, hist, current_rate=0.03)
check("三期均低于阈值 → satisfied", r["status"] == STATUS_SATISFIED, str(r["status"]))
check("满足时给出最大速率", r.get("max_abs_rate") == 0.05, str(r.get("max_abs_rate")))

hist2 = [("2026-11-01", 0.02), ("2026-11-02", 0.30), ("2026-11-03", 0.03)]
r = evaluate_stability(CRIT, hist2, current_rate=0.03)
check("有一期超过阈值 → not_satisfied", r["status"] == STATUS_NOT_SATISFIED, str(r["status"]))

r = evaluate_stability(CRIT, [], current_rate=None)
check("无速率历史 → insufficient", r["status"] == STATUS_INSUFFICIENT, str(r["status"]))

# 只取"截至当前"的历史，不能把未来期次算进来
future = [("2026-10-30", 0.02), ("2026-10-31", 0.03), ("2026-11-02", 0.04),
          ("2026-12-31", 0.50)]
r = evaluate_stability(CRIT, future, timestamp="2026-11-02", current_rate=0.04)
check("未来期次不参与稳定性判断", r["status"] == STATUS_SATISFIED, str(r["observed_rates"]))
check("未来期次被裁掉（不含 0.5）", 0.5 not in r["observed_rates"], str(r["observed_rates"]))

print("\n=== 位移管理等级（规范分档口径） ===")
BANDS = [
    {"level": "I", "label": "一级", "ratio_upper": 0.333, "action": "正常施工", "evidence": {"standard": "TEST"}},
    {"level": "II", "label": "二级", "ratio_upper": 0.667, "action": "加强支护", "evidence": {"standard": "TEST"}},
    {"level": "III", "label": "三级", "ratio_upper": 1.0, "action": "报警", "evidence": {"standard": "TEST"}},
]
check("利用率 0.2 → I 级", (evaluate_management_level(BANDS, 0.2) or {}).get("code") == "I")
check("利用率 0.5 → II 级", (evaluate_management_level(BANDS, 0.5) or {}).get("code") == "II")
check("利用率 0.9 → III 级", (evaluate_management_level(BANDS, 0.9) or {}).get("code") == "III")
check("超全部档位标注 above_all_bands",
      (evaluate_management_level(BANDS, 1.5) or {}).get("above_all_bands") is True)
check("无利用率返回 None", evaluate_management_level(BANDS, None) is None)
check("无分档配置返回 None", evaluate_management_level(None, 0.5) is None)

print("\n=== 断面级综合判定 ===")
items = [
    {"point_id": "GD-01", "metric_key": "crown_settlement", "metric_name": "拱顶下沉",
     "risk_level": "正常", "utilization": 0.3},
    {"point_id": "JL-01", "metric_key": "clearance_convergence", "metric_name": "净空收敛",
     "risk_level": "预警", "utilization": 0.75},
    {"point_id": "GD-02", "metric_key": "crown_settlement", "metric_name": "拱顶下沉",
     "risk_level": "关注", "utilization": 0.55},
]
smap = {"GD-01": "DK1+200", "JL-01": "DK1+200", "GD-02": "DK1+300"}
res = judge_sections(items, smap, required_metrics=["crown_settlement", "clearance_convergence"])
by_id = {s["section_id"]: s for s in res["sections"]}
check("断面数为 2", res["summary"]["sections"] == 2, str(res["summary"]))
check("DK1+200 取最不利 = 预警", by_id["DK1+200"]["worst_level"] == "预警", by_id["DK1+200"]["worst_level"])
check("最不利项为净空收敛", by_id["DK1+200"]["worst_item"]["metric_key"] == "clearance_convergence")
check("同断面两测项齐全 → complete", by_id["DK1+200"]["completeness"] == "complete")
check("DK1+300 缺净空收敛 → incomplete",
      by_id["DK1+300"]["completeness"] == SECTION_INCOMPLETE, str(by_id["DK1+300"]))
check("缺必测项时最不利等级仍保留（关注）", by_id["DK1+300"]["worst_level"] == "关注")
check("缺测清单写明缺项", any("净空收敛" in x for x in by_id["DK1+300"]["incomplete_reasons"]),
      str(by_id["DK1+300"]["incomplete_reasons"]))
check("整体断面等级取最不利 = 预警", res["summary"]["overall_section_level"] == "预警")

# 缺测且能判的都正常 → 断面不得判正常
only_normal = [{"point_id": "GD-09", "metric_key": "crown_settlement", "metric_name": "拱顶下沉",
                "risk_level": "正常", "utilization": 0.2}]
res2 = judge_sections(only_normal, {"GD-09": "DK2+000"},
                      required_metrics=["crown_settlement", "clearance_convergence"])
sec = res2["sections"][0]
check("缺必测项且其余正常 → 断面降为未知", sec["worst_level"] == "未知", sec["worst_level"])
check("降级原因被记录", sec["needs_review"] is True)

# 存在未知条目（判据缺失）时，strict 下同样不得判正常
with_unknown = [
    {"point_id": "GD-11", "metric_key": "crown_settlement", "metric_name": "拱顶下沉",
     "risk_level": "正常", "utilization": 0.2},
    {"point_id": "GD-11", "metric_key": "clearance_convergence", "metric_name": "净空收敛",
     "risk_level": "未知", "utilization": None},
]
res3 = judge_sections(with_unknown, {"GD-11": "DK3+000"}, required_metrics=[])
check("有未知条目 → 断面不得判正常（strict）", res3["sections"][0]["worst_level"] == "未知",
      res3["sections"][0]["worst_level"])
res4 = judge_sections(with_unknown, {"GD-11": "DK3+000"}, required_metrics=[], strict=False)
check("非 strict 保留最不利（正常）", res4["sections"][0]["worst_level"] == "正常",
      res4["sections"][0]["worst_level"])

# 未归属测点单独披露，不猜断面
res5 = judge_sections(items, {"GD-01": "DK1+200"},
                      required_metrics=["crown_settlement", "clearance_convergence"])
check("未归属测点进入 unassigned", res5["summary"]["items_unassigned"] == 2,
      str(res5["summary"]["items_unassigned"]))
check("未归属测点不被塞进任何断面", all(s["section_id"] == "DK1+200" for s in res5["sections"]))

print("\n=== 测点→断面映射来源 ===")
meta = {"GD-01": {"section_id": "DK1+200"}, "JL-01": {"里程": "DK1+200"}, "X-1": {}}
smap2 = build_section_map(meta, explicit={"GD-02": "DK1+200"})
check("台账 section_id 生效", smap2.get("GD-01") == "DK1+200")
check("台账里程字段兼容", smap2.get("JL-01") == "DK1+200")
check("显式映射生效", smap2.get("GD-02") == "DK1+200")
check("无断面信息的测点不入表", "X-1" not in smap2, str(smap2))

# --- 端到端：判据库带 management_levels / stability_criterion 时进入判定与载荷 ---
print("\n=== 端到端：判据库附加口径进入判定与载荷 ===")
from orchestrator import build_daily_report_input, run_pipeline  # noqa: E402
from risk_identifier import ProjectContext  # noqa: E402
from standards_registry import StandardsRegistry  # noqa: E402

lib = {
    "schema_version": "1.0",
    "source_id": "TEST-TUNNEL",
    "source_label": "测试用隧道判据",
    "source_type": "test",
    "metrics": {
        "crown_settlement": {
            "display_name": "拱顶下沉",
            "unit": "mm",
            "management_levels": BANDS,
            "stability_criterion": CRIT,
            "rules": [{
                "rule_id": "T-CS", "safety_level": "any", "support_type": "any",
                "cumulative_mm": 100, "rate_mm_per_day": 5,
                "evidence": {"standard": "TEST", "clause": "T-CS"},
            }],
        },
        "clearance_convergence": {
            "display_name": "净空收敛",
            "unit": "mm",
            "stability_criterion": CRIT,
            "rules": [{
                "rule_id": "T-CC", "safety_level": "any", "support_type": "any",
                "cumulative_mm": 50, "rate_mm_per_day": 3,
                "evidence": {"standard": "TEST", "clause": "T-CC"},
            }],
        },
    },
}
with tempfile.TemporaryDirectory() as tmp:
    Path(tmp, "lib.json").write_text(json.dumps(lib, ensure_ascii=False), encoding="utf-8")
    reg = StandardsRegistry(default_dir=tmp, user_dir=tmp)
    records = [
        {"point_id": "GD-01", "timestamp": "2026-11-01", "metric": "拱顶下沉", "value": 0.0, "unit": "mm"},
        {"point_id": "GD-01", "timestamp": "2026-11-02", "metric": "拱顶下沉", "value": 0.4, "unit": "mm"},
        {"point_id": "GD-01", "timestamp": "2026-11-03", "metric": "拱顶下沉", "value": 0.8, "unit": "mm"},
        {"point_id": "JL-01", "timestamp": "2026-11-01", "metric": "净空收敛", "value": 0.0, "unit": "mm"},
        {"point_id": "JL-01", "timestamp": "2026-11-02", "metric": "净空收敛", "value": 0.2, "unit": "mm"},
        {"point_id": "JL-01", "timestamp": "2026-11-03", "metric": "净空收敛", "value": 0.4, "unit": "mm"},
    ]
    ctx = ProjectContext(conditions={"construction_method": "矿山法"})
    res = run_pipeline(records, ctx, registry=reg, scenario=sp.load_profile("jikeng"))
    judg = {j["metric_key"]: j for j in res.stage3["judgments"]}
    check("拱顶下沉判定为正常（0.8/100，速率 0.4/5）", judg["crown_settlement"]["risk_level"] == "正常",
          str(judg["crown_settlement"]["risk_level"]))
    ml = judg["crown_settlement"].get("management_level")
    check("管理等级被计算（利用率 0.08 → I 级）", (ml or {}).get("code") == "I", str(ml))
    check("稳定性结论被计算", (judg["crown_settlement"].get("stability") or {}).get("status") is not None,
          str(judg["crown_settlement"].get("stability")))
    check("检查项里出现管理等级",
          any(c.get("check", "").startswith("位移管理等级") for c in judg["crown_settlement"]["checks"]))
    check("检查项里出现收敛稳定性",
          any(c.get("check", "").startswith("收敛稳定") for c in judg["crown_settlement"]["checks"]))

    # 断面信息需由画像开启；用临时画像验证聚合链路
    prof = json.loads(json.dumps(sp.load_profile("tunnel")))
    prof["section_judgment"] = {"enabled": True, "strict": True,
                                "required_metrics": ["crown_settlement", "clearance_convergence"]}
    res2 = run_pipeline(records, ctx, registry=reg, scenario=prof)
    payload = build_daily_report_input(
        res2,
        points_meta={"GD-01": {"section_id": "DK1+200"}, "JL-01": {"section_id": "DK1+200"}},
        report_date="2026-11-03", item_date="2026-11-03",
    )
    check("载荷出现 sections", isinstance(payload.get("sections"), dict), str(type(payload.get("sections"))))
    sec = payload["sections"]["sections"][0]
    check("断面聚合到 DK1+200", sec["section_id"] == "DK1+200", str(sec["section_id"]))
    check("断面含两个测项", sec["item_count"] == 2, str(sec["item_count"]))
    check("断面等级为最不利（正常）", sec["worst_level"] == "正常", sec["worst_level"])

# --- 真实判据库：断面综合判定 + 收敛稳定/可停测 ---
print("\n=== 真实判据库端到端（GB 50911-2013 / JTG\T 3660-2020）===")
prof_t = sp.load_profile("tunnel")
reg_t = sp.load_registry(prof_t)

# 1) 同断面：拱顶正常 + 收敛超限 → 断面取最不利
sec_records = [
    {"point_id": "GD-01", "timestamp": "2026-11-01", "metric": "拱顶下沉", "value": 0.0, "unit": "mm"},
    {"point_id": "GD-01", "timestamp": "2026-11-02", "metric": "拱顶下沉", "value": 1.0, "unit": "mm"},
    {"point_id": "GD-01", "timestamp": "2026-11-03", "metric": "拱顶下沉", "value": 2.0, "unit": "mm"},
    {"point_id": "JL-01", "timestamp": "2026-11-01", "metric": "净空收敛", "value": 0.0, "unit": "mm"},
    {"point_id": "JL-01", "timestamp": "2026-11-02", "metric": "净空收敛", "value": 1.0, "unit": "mm"},
    {"point_id": "JL-01", "timestamp": "2026-11-03", "metric": "净空收敛", "value": 2.0, "unit": "mm"},
]
sec_ctx = ProjectContext(conditions={"construction_method": "矿山法", "section_location": "区间"})
sec_res = run_pipeline(sec_records, sec_ctx, scenario=prof_t)
sec_payload = build_daily_report_input(
    sec_res,
    points_meta={"GD-01": {"section_id": "DK1+200"}, "JL-01": {"section_id": "DK1+200"}},
    report_date="2026-11-03", item_date="2026-11-03",
)
secs = sec_payload["sections"]
check("断面聚合产生 1 个断面", secs["summary"]["sections"] == 1, str(secs["summary"]))
sec_one = secs["sections"][0]
check("断面含 2 个测点", sec_one["item_count"] == 2, str(sec_one["item_count"]))
check("同断面拱顶+收敛齐全 → complete", sec_one["completeness"] == "complete", sec_one["completeness"])
check("断面等级 = 两个测项最不利",
      sec_one["worst_level"] == max([i["risk_level"] for i in sec_payload["items"]],
                                    key=lambda v: {"未知": -1, "正常": 0, "关注": 1, "预警": 2, "报警": 3, "危险报警": 4}.get(v, -1)),
      str(sec_one["worst_level"]))

# 2) 只有拱顶、没有收敛 → 缺必测项，断面不得判正常
only_crown = [r for r in sec_records if r["point_id"] == "GD-01"]
oc_res = run_pipeline(only_crown, sec_ctx, scenario=prof_t)
oc_payload = build_daily_report_input(oc_res, points_meta={"GD-01": {"section_id": "DK1+300"}},
                                      report_date="2026-11-03", item_date="2026-11-03")
oc_sec = oc_payload["sections"]["sections"][0]
check("缺净空收敛 → incomplete", oc_sec["completeness"] == "incomplete", oc_sec["completeness"])
check("缺必测项时断面不得判为正常", oc_sec["worst_level"] != "正常", oc_sec["worst_level"])
check("缺项原因写明净空收敛",
      any("净空收敛" in x for x in oc_sec["incomplete_reasons"]), str(oc_sec["incomplete_reasons"]))

# 3) 收敛稳定 / 可停测：连续 3 期速率 < 0.2mm/d → 满足
stable_records = [
    {"point_id": "GD-05", "timestamp": "2026-11-01", "metric": "拱顶下沉", "value": 100.0, "unit": "mm"},
    {"point_id": "GD-05", "timestamp": "2026-11-02", "metric": "拱顶下沉", "value": 100.10, "unit": "mm"},
    {"point_id": "GD-05", "timestamp": "2026-11-03", "metric": "拱顶下沉", "value": 100.16, "unit": "mm"},
    {"point_id": "GD-05", "timestamp": "2026-11-04", "metric": "拱顶下沉", "value": 100.20, "unit": "mm"},
]
st_res = run_pipeline(stable_records, sec_ctx, scenario=prof_t)
st_j = st_res.stage3["judgments"][-1]
stab = st_j.get("stability") or {}
check("稳定性判据被计算", stab.get("status") is not None, str(stab))
check("连续 3 期速率 < 0.2mm/d → 满足停测量化条件",
      stab.get("status") == "satisfied", str(stab))
check("稳定性阈值来自规范 0.2mm/d", stab.get("threshold") == 0.2, str(stab.get("threshold")))
check("速率分级给出“基本稳定”",
      (stab.get("rate_state") or {}).get("state") == "基本稳定", str(stab.get("rate_state")))
check("稳定性依据为 18.6.3-2",
      (stab.get("evidence") or {}).get("clause") == "18.6.3-2", str(stab.get("evidence")))

# 4) 速率明显大于 1.0mm/d → 急剧变形
fast_records = [
    {"point_id": "GD-06", "timestamp": "2026-11-01", "metric": "拱顶下沉", "value": 0.0, "unit": "mm"},
    {"point_id": "GD-06", "timestamp": "2026-11-02", "metric": "拱顶下沉", "value": 2.0, "unit": "mm"},
    {"point_id": "GD-06", "timestamp": "2026-11-03", "metric": "拱顶下沉", "value": 5.0, "unit": "mm"},
    {"point_id": "GD-06", "timestamp": "2026-11-04", "metric": "拱顶下沉", "value": 9.0, "unit": "mm"},
]
f_res = run_pipeline(fast_records, sec_ctx, scenario=prof_t)
f_stab = (f_res.stage3["judgments"][-1].get("stability") or {})
check("速率 2~4mm/d 连续 3 期 → 未满足稳定判据", f_stab.get("status") == "not_satisfied", str(f_stab))
check("速率 4mm/d → 急剧变形",
      (f_stab.get("rate_state") or {}).get("state") == "急剧变形", str(f_stab.get("rate_state")))

# 5) 位移管理等级：缺 U0 时不猜，明确披露
mg = (st_res.stage3["judgments"][-1].get("management_level"))
check("缺设计极限位移时不给出管理等级", mg is None, str(mg))
check("缺 U0 打 MGMT_LEVEL_NOT_EVALUATED 标记",
      "MGMT_LEVEL_NOT_EVALUATED" in st_res.stage3["judgments"][-1]["flags"],
      str(st_res.stage3["judgments"][-1]["flags"]))
u0_res = run_pipeline(stable_records, replace(sec_ctx, design_values={"极限位移": 60.0}), scenario=prof_t)
u0_ml = u0_res.stage3["judgments"][-1].get("management_level") or {}
check("给出 U0=60mm 后按表18.6.3 分档", u0_ml.get("code") == "I", str(u0_ml))
check("管理等级标明基准为设计极限位移", u0_ml.get("base") == "design_value", str(u0_ml.get("base")))

# 6) 无判据测项仍不得判正常
gw_res = run_pipeline(
    [{"point_id": "SW-01", "timestamp": "2026-11-01", "metric": "地下水位", "value": 0.0, "unit": "mm"},
     {"point_id": "SW-01", "timestamp": "2026-11-02", "metric": "地下水位", "value": 50.0, "unit": "mm"}],
    sec_ctx, scenario=prof_t,
)
gw_j = gw_res.stage3["judgments"][-1]
check("地下水位无判据 → 未知", gw_j["risk_level"] == "未知", str(gw_j["risk_level"]))
check("地下水位弃权原因为无适用判据", "NO_APPLICABLE_RULE" in gw_j["abstain"], str(gw_j["abstain"]))


print("\n" + "=" * 70)
print(f"PASS: {PASS}    FAIL: {FAIL}")
if FAIL:
    print("失败项：")
    for name in FAILED:
        print(f"  - {name}")
    raise SystemExit(1)
print("全部通过")
