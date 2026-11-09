"""场景画像与隧道适配回归
========================

覆盖三件事：
1. **等价性**：`jikeng` 画像的取值必须与改造前的内置默认逐项一致，
   且同一批数据「不传 scenario」与「显式传 jikeng」判定结果完全相同 —— 存量行为不被改变。
2. **骨架安全性**：`tunnel` 画像（status=skeleton，判据库为空）下，任何测项都必须弃权，
   绝不允许出现"正常"结论，也不允许产出报警。
3. **新增能力**：通用条件维度、比例参照长度（非 %H）、差值型派生、速度量纲、别名扩展。

运行：`python -B scenarios/tests/test_scenarios.py`（工作目录不限）
"""

from __future__ import annotations

import json
import sys
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
from ingest import build_metric_aliases, normalize_value_unit  # noqa: E402
from orchestrator import build_daily_report_input, run_pipeline  # noqa: E402
from risk_identifier import ProjectContext  # noqa: E402
from derived_pairs import derive_pair_records  # noqa: E402

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


# --- 1. 画像等价性 --------------------------------------------------------

print("\n=== 场景画像 · 与内置默认的等价性 ===")
jk = sp.load_profile("jikeng")
check("jikeng 画像可加载", jk.get("id") == "jikeng", str(jk.get("id")))
check("jikeng 状态为 active", jk.get("status") == "active", str(jk.get("status")))
check(
    "条件维度与内置一致",
    sp.condition_dimensions(jk) == sp.BUILTIN_CONDITION_DIMENSIONS,
    str(sp.condition_dimensions(jk)),
)
check(
    "具体度维度与内置一致",
    sp.specificity_dimensions(jk) == sp.BUILTIN_SPECIFICITY_DIMENSIONS,
    str(sp.specificity_dimensions(jk)),
)
check(
    "默认条件与内置一致",
    sp.default_conditions(jk) == sp.BUILTIN_DEFAULT_CONDITIONS,
    str(sp.default_conditions(jk)),
)
check(
    "参照长度 key 与内置一致",
    sp.reference_length_key(jk) == sp.BUILTIN_REFERENCE_KEY,
    str(sp.reference_length_key(jk)),
)
check(
    "参照长度名称为“基坑设计深度 H”",
    sp.reference_length_label("excavation_depth_m", jk) == "基坑设计深度 H",
    sp.reference_length_label("excavation_depth_m", jk),
)
check(
    "默认规范库目录与内置一致",
    sp.standards_dir(jk) == ENGINE / "standards" / "default",
    str(sp.standards_dir(jk)),
)
check(
    "规范来源显示名与内置一致",
    sp.origin_labels(jk)["default"] == sp.BUILTIN_DEFAULT_LABEL,
    sp.origin_labels(jk)["default"],
)
check(
    "日报模板版本与内置一致",
    sp.template_version(jk) == sp.BUILTIN_TEMPLATE_VERSION,
    sp.template_version(jk),
)
check("jikeng 无待接入项", sp.pending_inputs(jk) == [], str(sp.pending_inputs(jk)))
check("jikeng 视为就绪", sp.is_ready(jk) is True)

# --- 2. 判定等价性（核心回归） -------------------------------------------

print("\n=== 判定等价性 · 不传 scenario 与显式 jikeng 必须一致 ===")
JK_RECORDS = [
    {"point_id": "WTHD-01", "timestamp": "2026-08-01", "metric": "墙顶水平位移", "value": 0.0, "unit": "mm"},
    {"point_id": "WTHD-01", "timestamp": "2026-08-02", "metric": "墙顶水平位移", "value": 12.0, "unit": "mm"},
    {"point_id": "WTHD-01", "timestamp": "2026-08-03", "metric": "墙顶水平位移", "value": 26.0, "unit": "mm"},
    {"point_id": "SW-01", "timestamp": "2026-08-03", "metric": "地下水位", "value": 1500.0, "unit": "mm"},
]


def _judgements(result) -> list[tuple]:
    return [
        (j["point_id"], j["metric_key"], j["risk_level"], tuple(j["abstain"]))
        for j in result.stage3["judgments"]
    ]


base = run_pipeline(JK_RECORDS, ProjectContext(excavation_depth_m=20.0))
explicit = run_pipeline(JK_RECORDS, ProjectContext(excavation_depth_m=20.0), scenario=jk)
check("两条路径判定条数一致", len(_judgements(base)) == len(_judgements(explicit)))
check("两条路径判定结果逐项一致", _judgements(base) == _judgements(explicit), str(_judgements(explicit)))
check("基坑仍能给出确定结论（非全弃权）", any(r != "未知" for *_x, r, _a in _judgements(base)))
check(
    "基坑规范来源显示名未变",
    base.stage3["judgments"][0]["effective_source"]["origin_display"]
    == "默认规范库（基坑智守项目相关规范）",
    str(base.stage3["judgments"][0]["effective_source"]),
)

# --- 3. 隧道判据库（已按规范条文接入） --------------------------------

print("\n=== 隧道判据库 · 接入现实与安全边界 ===")
tn = sp.load_profile("tunnel")
check("tunnel 画像可加载", tn.get("id") == "tunnel", str(tn.get("id")))
check("tunnel 状态为 active", tn.get("status") == "active", str(tn.get("status")))
check("tunnel 视为就绪", sp.is_ready(tn) is True)
check("tunnel 声明了待提供的运行时参数", len(sp.pending_inputs(tn)) >= 5, str(len(sp.pending_inputs(tn))))
check(
    "tunnel 规范来源与基坑不同名",
    sp.origin_labels(tn)["default"] != sp.BUILTIN_DEFAULT_LABEL,
    sp.origin_labels(tn)["default"],
)
check(
    "tunnel 默认规范库指向 standards/tunnel",
    sp.standards_dir(tn) == ENGINE / "standards" / "tunnel",
    str(sp.standards_dir(tn)),
)
check(
    "tunnel 条件维度含工法与区域类型",
    {"construction_method", "section_location"} <= set(sp.condition_dimensions(tn)),
    str(sp.condition_dimensions(tn)),
)

tn_reg = sp.load_registry(tn)
tn_metrics = tn_reg.metric_keys()
rule_total = sum(len((tn_reg.get_metric(k) or {}).get("rules") or {}) for k in tn_metrics)
check("隧道判据库已载入", len(tn_metrics) >= 25, str(len(tn_metrics)))
check("隧道判据规则数达到 40 条以上", rule_total >= 40, str(rule_total))

# 每条规则都必须带规范名称与条文/表号 —— 无出处不得入判据库
bad_evidence = []
for k in tn_metrics:
    node = tn_reg.get_metric(k) or {}
    for rid, rule in (node.get("rules") or {}).items():
        ev = rule.get("evidence") or {}
        if not ev.get("standard") or not ev.get("clause"):
            bad_evidence.append(f"{k}/{rid}")
check("所有判据都带规范名称与条文号", bad_evidence == [], str(bad_evidence[:5]))

# 抽查两条关键判据的取值口径
cs = tn_reg.get_metric("crown_settlement") or {}
cs_rule = (cs.get("rules") or {}).get("CS-MINE-SECTION") or {}
check("拱顶下沉区间取严为 10mm", cs_rule.get("cumulative_mm") == {"min": 10, "max": 20}, str(cs_rule.get("cumulative_mm")))
check("拱顶下沉速率 3mm/d", cs_rule.get("rate_mm_per_day") == 3, str(cs_rule.get("rate_mm_per_day")))
check("拱顶下沉依据为表9.2.3-1", cs_rule.get("evidence", {}).get("clause") == "表9.2.3-1",
      str(cs_rule.get("evidence")))

cc = tn_reg.get_metric("clearance_convergence") or {}
cc_shield = (cc.get("rules") or {}).get("CC-SHIELD") or {}
check("盾构净空收敛为 0.2%D 比例判据",
      cc_shield.get("cumulative_pct_ref") == {"ref": "diameter_m", "pct": 0.2},
      str(cc_shield.get("cumulative_pct_ref")))

from risk_identifier import resolve_limit  # noqa: E402
tun_ctx = ProjectContext(conditions={"construction_method": "矿山法", "section_location": "区间"})
lim_cs = resolve_limit(tn_reg, "crown_settlement", tun_ctx)
check("矿山法区间拱顶下沉限值 = 10mm", lim_cs.cumulative_mm == 10.0, str(lim_cs.cumulative_mm))
check("限值依据可追溯到表9.2.3-1", lim_cs.evidence.get("clause") == "表9.2.3-1", str(lim_cs.evidence))

shield_ctx = ProjectContext(conditions={"construction_method": "盾构法", "section_location": "区间"},
                            reference_lengths={"diameter_m": 6.0})
lim_cc = resolve_limit(tn_reg, "clearance_convergence", shield_ctx)
check("盾构净空收敛 0.2%×6m = 12mm", abs(lim_cc.cumulative_mm - 12.0) < 1e-9, str(lim_cc.cumulative_mm))
check("比例限值记录参照长度 key", lim_cc.reference_length_key == "diameter_m", str(lim_cc.reference_length_key))
no_d = ProjectContext(conditions={"construction_method": "盾构法", "section_location": "区间"})
lim_cc2 = resolve_limit(tn_reg, "clearance_convergence", no_d)
check("缺开挖直径时只给上界", lim_cc2.cumulative_upper_bound_only is True)
check("缺开挖直径弃权码为 MISSING_REF_LENGTH",
      lim_cc2.missing_reference_code == "MISSING_REF_LENGTH", str(lim_cc2.missing_reference_code))

# 管线：未给管型时必须弃权，不得在燃气/雨污水/供水之间随机命中
lim_pipe = resolve_limit(tn_reg, "pipeline_settlement", ProjectContext())
check("未提供管型时管线判据不适用", lim_pipe.rule_id is None and "NO_APPLICABLE_RULE" in lim_pipe.flags,
      str(lim_pipe.flags))
lim_pipe_gas = resolve_limit(tn_reg, "pipeline_settlement",
                             ProjectContext(conditions={"pipeline_type": "燃气管道"}))
check("给出管型后命中燃气管道判据", lim_pipe_gas.rule_id == "PS-GAS", str(lim_pipe_gas.rule_id))
check("燃气管道取严为 10mm", lim_pipe_gas.cumulative_mm == 10.0, str(lim_pipe_gas.cumulative_mm))

# 无判据测项必须弃权（不得因为"没超限"判正常）
lim_gw = resolve_limit(tn_reg, "groundwater_level", ProjectContext())
check("地下水位无判据 → 不适用", "NO_APPLICABLE_RULE" in lim_gw.flags, str(lim_gw.flags))

# 危险报警条件必须来自规范条文
dangers = tn_reg.danger_conditions or []
check("危险报警条件不少于 6 条", len(dangers) >= 6, str(len(dangers)))
check("危险报警条件均带条文号",
      all((d.get("evidence") or {}).get("clause") for d in dangers),
      str([d.get("code") for d in dangers if not (d.get("evidence") or {}).get("clause")]))

TUNNEL_RECORDS = [
    {"point_id": "GD-01", "timestamp": "2026-11-01", "metric": "拱顶下沉", "value": 0.0, "unit": "mm"},
    {"point_id": "GD-01", "timestamp": "2026-11-02", "metric": "拱顶下沉", "value": 3.1, "unit": "mm"},
    {"point_id": "GD-01", "timestamp": "2026-11-03", "metric": "拱顶下沉", "value": 6.4, "unit": "mm"},
    {"point_id": "BL-01", "timestamp": "2026-11-03", "metric": "爆破振动速度", "value": 1.8, "unit": "cm/s"},
]
tctx = ProjectContext(
    conditions={"construction_method": "矿山法", "rock_class": "IV", "section_location": "区间"},
    reference_lengths={"buried_depth_m": 32.0, "span_m": 6.2},
)
tres = run_pipeline(TUNNEL_RECORDS, tctx, scenario=tn)
tjud = tres.stage3["judgments"]
check("隧道记录全部完成归一化", tres.summary["records"] == 4, str(tres.summary["records"]))
check("隧道判定条数正确", len(tjud) == 4, str(len(tjud)))
crown_items = [j for j in tjud if j["metric_key"] == "crown_settlement"]
crown_cum = [c for c in crown_items[-1]["checks"] if c.get("check") == "累计值"][0]
check("拱顶下沉累计值 6.4/10 判为关注", crown_cum["verdict"] == "关注", str(crown_cum))
crown_rate = [c for c in crown_items[-1]["checks"] if c.get("check") == "变化速率"][0]
check("拱顶下沉速率 3.3/3 判为超限", crown_rate["verdict"] in ("报警", "危险报警"), str(crown_rate))
check("条目等级取各检查项最不利", crown_items[-1]["risk_level"] in ("报警", "危险报警"),
      str(crown_items[-1]["risk_level"]))
check("隧道场景标识进入汇总", tres.summary["scenario_id"] == "tunnel")
check("隧道场景已就绪进入汇总", tres.summary["scenario_ready"] is True)
check(
    "隧道别名映射生效",
    [j["metric_key"] for j in tjud[:3]] == ["crown_settlement"] * 3,
    str([j["metric_key"] for j in tjud]),
)
check(
    "爆破振动 cm/s 换算为 mm/s",
    tres.stage2["results"][-1]["inputs"]["current"] == 18.0,
    str(tres.stage2["results"][-1]["inputs"]),
)
blast = [j for j in tjud if j["metric_key"] == "blasting_vibration_velocity"][0]
check("爆破振动未给保护对象时弃权",
      "NO_APPLICABLE_RULE" in blast["abstain"], str(blast["abstain"]))

blast_ctx = ProjectContext(
    conditions={"construction_method": "矿山法", "protection_object": "交通隧道", "frequency_band": "f≤50Hz"},
)
blast_res = run_pipeline(
    [{"point_id": "BL-02", "timestamp": "2026-11-01", "metric": "爆破振动速度", "value": 0.0, "unit": "mm/s"},
     {"point_id": "BL-02", "timestamp": "2026-11-02", "metric": "爆破振动速度", "value": 130.0, "unit": "mm/s"}],
    blast_ctx, scenario=tn,
)
blast_j = blast_res.stage3["judgments"][-1]
check("爆破振动按交通隧道判据命中", blast_j["rule_id"] in ("BV-TUNNEL-ANYF", "BV-TUNNEL-LOWF"),
      str(blast_j["rule_id"]))
check("爆破振动 130mm/s 超过 100mm/s 判为超限",
      blast_j["risk_level"] in ("报警", "危险报警"), str(blast_j["risk_level"]))

# 危险报警信号（工程师现场判定）必须能把等级拉到危险报警
danger_ctx = ProjectContext(
    conditions={"construction_method": "矿山法", "section_location": "区间"},
    danger_signals={"TUN-DANGER-2": True},
)
dres = run_pipeline(TUNNEL_RECORDS, danger_ctx, scenario=tn)
djud = [j for j in dres.stage3["judgments"] if j["metric_key"] == "crown_settlement"][-1]
check("巡查警情信号触发危险报警", djud["risk_level"] == "危险报警", str(djud["risk_level"]))
check("危险报警检查项写明条件",
      any(c.get("check") == "危险报警条件" for c in djud["checks"]), str([c.get("check") for c in djud["checks"]]))

payload = build_daily_report_input(tres, report_date="2026-11-03", item_date="2026-11-03")
check("载荷带场景标识", payload["project"]["scenario_id"] == "tunnel")
check("载荷带场景状态", payload["project"]["scenario_status"] == "active")
check("载荷显示场景已就绪", payload["project"]["scenario_ready"] is True)
check("载荷带工程条件", payload["project"]["conditions"].get("construction_method") == "矿山法")
check("载荷含断面判定结果", isinstance(payload.get("sections"), dict), str(type(payload.get("sections"))))

# --- 4. 别名扩展不污染基坑 ------------------------------------------------

print("\n=== 别名扩展 ===")
jk_reg = sp.load_registry(jk)
tn_reg = sp.load_registry(tn)
jk_aliases = build_metric_aliases(jk_reg.display_names())
tn_aliases = build_metric_aliases(tn_reg.display_names(), sp.metric_alias_extras(tn))
check("基坑别名表不含隧道简称", "拱顶下沉" not in jk_aliases)
check("隧道别名表含拱顶下沉", tn_aliases.get("拱顶下沉") == "crown_settlement")
check("隧道别名表含净空收敛", tn_aliases.get("净空收敛") == "clearance_convergence")
check("隧道仍保留基坑通用别名", tn_aliases.get("地表沉降") == "surface_settlement")
check(
    "隧道别名只接受已存在的测项",
    build_metric_aliases(tn_reg.display_names(), {"虚构测项": "not_a_metric"}).get("虚构测项") is None,
)

# --- 5. 通用条件维度与比例参照长度 ---------------------------------------

print("\n=== 通用条件维度 / 比例参照长度 ===")
cond_ctx = ProjectContext(
    conditions={"construction_method": "盾构法", "rock_class": "V", "section_type": "单线"},
    reference_lengths={"buried_depth_m": 20.0},
)
check("conditions 读取生效", cond_ctx.condition_value("construction_method") == "盾构法")
check("未声明维度回落属性", cond_ctx.condition_value("safety_level") == "一级")
check("参照长度可读取", cond_ctx.ref_length("buried_depth_m") == 20.0)
check("Q1 参照长度缺失返回 None", cond_ctx.ref_length("span_m") is None)
check("H 缺省时 ref_length 不为 0", cond_ctx.ref_length("excavation_depth_m") is None)


class _CtxNoRef(ProjectContext):
    pass


# 用临时判据库验证 pct_ref 换算：0.2% × 埋深 20 m × 10 = 40 mm
from standards_registry import StandardsRegistry, ORIGIN_DEFAULT  # noqa: E402
from risk_identifier import resolve_limit  # noqa: E402
import tempfile  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    lib = {
        "schema_version": "1.0",
        "source_id": "TEST-PCTREF",
        "source_label": "比例参照长度测试库",
        "source_type": "test",
        "metrics": {
            "crown_settlement": {
                "display_name": "拱顶下沉",
                "unit": "mm",
                "rules": [
                    {
                        "rule_id": "T-1",
                        "safety_level": "any",
                        "support_type": "any",
                        "cumulative_mm": 100,
                        "cumulative_pct_ref": {"ref": "buried_depth_m", "pct": 0.2},
                        "rate_mm_per_day": 2,
                        "evidence": {"standard": "TEST", "clause": "T-1"},
                    }
                ],
            }
        },
    }
    Path(tmp, "lib.json").write_text(json.dumps(lib, ensure_ascii=False), encoding="utf-8")
    reg = StandardsRegistry(default_dir=tmp, user_dir=tmp)

    lim = resolve_limit(reg, "crown_settlement", cond_ctx)
    check("pct_ref 按埋深换算 limit=40mm", lim.cumulative_mm == 40.0, str(lim.cumulative_mm))
    check("pct_ref 取 min(绝对量, 比例)", "min" in (lim.cumulative_basis or ""), str(lim.cumulative_basis))
    check("记录参照长度 key", lim.reference_length_key == "buried_depth_m", str(lim.reference_length_key))

    no_ref = ProjectContext(conditions={"construction_method": "矿山法"})
    lim2 = resolve_limit(reg, "crown_settlement", no_ref)
    check("缺参照长度时仅作上界", lim2.cumulative_upper_bound_only is True)
    check("缺参照长度弃权码正确", lim2.missing_reference_code == "MISSING_REF_LENGTH", str(lim2.missing_reference_code))
    check("缺参照长度打标记", "MISSING_REF_LENGTH" in lim2.flags, str(lim2.flags))

# --- 6. 差值型派生（断面收敛） -------------------------------------------

print("\n=== 差值型派生 ===")
from ingest import normalize_records  # noqa: E402

raw = [
    {"point_id": "A", "timestamp": "2026-11-01", "metric": "raw", "value": 100.0, "unit": "mm"},
    {"point_id": "B", "timestamp": "2026-11-01", "metric": "raw", "value": 96.0, "unit": "mm"},
    {"point_id": "A", "timestamp": "2026-11-02", "metric": "raw", "value": 100.4, "unit": "mm"},
    {"point_id": "B", "timestamp": "2026-11-02", "metric": "raw", "value": 95.2, "unit": "mm"},
    {"point_id": "C", "timestamp": "2026-11-02", "metric": "raw", "value": 50.0, "unit": "kN"},
]
norm = normalize_records(raw, default_metric_key="raw")
derived, rep = derive_pair_records(norm, [{"point_a": "A", "point_b": "B", "section_id": "DK1+200"}], metric_key="clearance_convergence")
check("点对产出两条收敛记录", len(derived) == 2, str(len(derived)))
check("首期收敛值 = 100-96 = 4mm", derived[0].value == 4.0, str(derived[0].value))
check("次期收敛值 = 100.4-95.2 = 5.2mm", abs(derived[1].value - 5.2) < 1e-9, str(derived[1].value))
check("派生记录带 PAIR_DERIVED 标记", "PAIR_DERIVED" in derived[0].source_flags)
check("派生记录可追溯到两个源测点", derived[0].source_metadata["pair"]["point_a"] == "A")
check("派生报告统计产出数", rep.to_dict()["produced"] == 2, str(rep.to_dict()))

_derived_c, _rep_c = derive_pair_records(norm, [{"point_a": "A", "point_b": "C"}], metric_key="clearance_convergence")
check("量纲不一致的点对拒绝配对", _derived_c == [], str(len(_derived_c)))
check("量纲不一致写入告警", _rep_c.skipped_unit_mismatch == 1, str(_rep_c.to_dict()))

_derived_d, _rep_d = derive_pair_records(norm, [{"point_a": "A", "point_b": "ZZ"}], metric_key="clearance_convergence")
check("缺失测点不产出", _derived_d == [])
check("缺失测点写入告警", "ZZ" in _rep_d.skipped_missing_point, str(_rep_d.to_dict()))

# 派生记录接入完整管线后仍需弃权（判据未接入）
pair_res = run_pipeline(
    [{"point_id": "A", "timestamp": "2026-11-01", "metric": "raw", "value": 100.0, "unit": "mm"},
     {"point_id": "B", "timestamp": "2026-11-01", "metric": "raw", "value": 96.0, "unit": "mm"},
     {"point_id": "A", "timestamp": "2026-11-02", "metric": "raw", "value": 100.4, "unit": "mm"},
     {"point_id": "B", "timestamp": "2026-11-02", "metric": "raw", "value": 95.2, "unit": "mm"}],
    ProjectContext(conditions={"construction_method": "矿山法"}),
    scenario=tn,
    derived_pairs=[{"point_a": "A", "point_b": "B", "section_id": "DK1+200"}],
    derived_metric_key="clearance_convergence",
)
check(
    "派生记录进入阶段一统计",
    pair_res.stage1["derived_pairs"]["produced"] == 2,
    str(pair_res.stage1["derived_pairs"]),
)
check(
    "派生收敛项同样不得判为正常",
    all(j["risk_level"] != "正常" for j in pair_res.stage3["judgments"]),
    str([j["risk_level"] for j in pair_res.stage3["judgments"]]),
)

# --- 7. 画像契约校验 ------------------------------------------------------

print("\n=== 画像契约校验 ===")
try:
    sp._validate({"schema": "wrong"}, Path("bad.json"))
    check("非法 schema 被拒绝", False)
except sp.ScenarioError:
    check("非法 schema 被拒绝", True)

try:
    sp._validate({"schema": sp.SCENARIO_SCHEMA, "id": "other", "name": "x", "status": "active", "standards": {}}, Path("jikeng.json"))
    check("id 与文件名不一致被拒绝", False)
except sp.ScenarioError:
    check("id 与文件名不一致被拒绝", True)

try:
    sp.load_profile("not_exist")
    check("未知场景报错", False)
except sp.ScenarioError as exc:
    check("未知场景报错", "未找到场景画像" in str(exc), str(exc))

print("\n" + "=" * 70)
print(f"PASS: {PASS}    FAIL: {FAIL}")
if FAIL:
    print("失败项：")
    for name in FAILED:
        print(f"  - {name}")
    raise SystemExit(1)
print("全部通过")
