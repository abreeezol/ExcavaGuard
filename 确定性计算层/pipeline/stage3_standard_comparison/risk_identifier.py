"""
阶段三 · 规范比对 —— 风险识别与分级

职责
----
把阶段二产出的确定性计算结果，与规范库中的判据进行比对，识别风险并分级。

比对所用规范的来源
------------------
1. **默认规范库**（始终生效）
   取自目录 `C:\\Study\\bisai\\Hai AI Agent\\基坑智守项目相关规范`，
   该目录内的 30 本规范被视为覆盖大多数情况的通用规范，是本阶段的默认判据来源。
   条文级阈值文件：`standards/default/thresholds_gb50497_2019.json`
   规范库索引：`standards/default/规范库索引.json`

2. **用户上传规范**（可选）
   目录 `standards/user_uploaded/`。用户可放入地方规程或项目专项方案的阈值 JSON。
   **用户未上传时不作任何特殊处理**——不报错、不告警、不输出缺失提示。

每一次判定都会在结果中写明**本次实际生效的规范来源**：
`origin` = `default_library` / `user_uploaded`，并附 `source_id`、`source_label`、条文出处。

风险分级
--------
| 等级 | 触发条件（利用率 u = 实测值 / 限值） | 依据 |
|---|---|---|
| 正常 | u < 0.50 | 监测值处于限值充裕范围 |
| 关注 | 0.50 ≤ u < 0.70 | 接近管控区间，需持续关注 |
| 预警 | 0.70 ≤ u < 1.00，或连续 3 次速率 > 70% 速率限值 | GB 50497-2019 第 8.0.3 条 / 表 8.0.4 注 |
| 报警 | u ≥ 1.00 | GB 50497-2019 第 8.0.7 条：达到预警值应报警 |
| 危险报警 | 触发 GB 50497-2019 8.0.9 任一危险报警条件，或 u ≥ 1.20 | GB 50497-2019 第 8.0.9 条（强制性条文） |

弃权
----
输入不足时**弃权**，给出明确弃权码，绝不猜测。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from standards_registry import ORIGIN_DEFAULT, ORIGIN_USER, StandardsRegistry
from convergence import (
    STATUS_NO_CRITERION,
    evaluate_management_level,
    evaluate_rate_state,
    evaluate_stability,
)

# --- 风险等级 -------------------------------------------------------------

LEVEL_NORMAL = "正常"
LEVEL_ATTENTION = "关注"
LEVEL_WARNING = "预警"
LEVEL_ALARM = "报警"
LEVEL_DANGER = "危险报警"
LEVEL_UNKNOWN = "未知"

RISK_LEVELS = [LEVEL_NORMAL, LEVEL_ATTENTION, LEVEL_WARNING, LEVEL_ALARM, LEVEL_DANGER]
_LEVEL_RANK = {lv: i for i, lv in enumerate(RISK_LEVELS)}

BAND_ATTENTION = 0.50
BAND_WARNING = 0.70
BAND_DANGER = 1.20

ABSTAIN_REASONS = {
    "ABSTAIN_FROM_STAGE2": "阶段二已弃权，无可比对的确定性结果",
    "UNKNOWN_METRIC": "规范库中不存在该监测项的判据",
    "NO_APPLICABLE_RULE": "当前工程条件（安全等级/工法或支护形式等）组合下无适用判据",
    "NO_LIMIT": "该监测项在当前条件下未给出可比对的限值",
    "MISSING_DESIGN_VALUE": "该监测项需按设计值校核，但未提供设计值",
    "MISSING_H": "该监测项需按基坑设计深度 H 校核，但未提供 H",
    "MISSING_REF_LENGTH": "该监测项的比例限值需按参照长度（埋深/跨度/外径）换算，但未提供该参数",
    "SCENARIO_PENDING": "当前场景的判据库尚未接入或未复核，按安全原则不判定",
    "DATA_QUALITY_BLOCKED": "该期数据存在高严重度质量问题，按安全原则不参与风险判定，需现场复核",
}

# 高严重度数据质量问题：该期数据不得参与风险判定，一律弃权并转人工复核。
# 依据：AGENTS.md 工程安全边界「不自动修复未知单位、方向、测点映射或缺失字段」、
#       「关键校验失败时停止输出报告成品，只返回错误和待确认项」。
# 理由：粗差会把「正常」误判为「报警」，传感器漂移会把「报警」误判为「正常」，
#       两个方向的漏判都会危及安全，因此一律阻塞而不是"带病判定"。
BLOCKING_ISSUE_CODES = {
    "OUTLIER",
    "NON_NUMERIC_VALUE",
    "UNPARSED_TIMESTAMP",
    "UNSUPPORTED_UNIT",
    "UNKNOWN_MEASUREMENT_SEMANTICS",
    "SEMANTIC_BASELINE_CONFLICT",
    "FLATLINE",
}

# 不收敛判据：当前速率显著高于该序列的最小二乘平均速率，说明变形在加速而非收敛
# 依据：JGJ 120-2012 第 8.2.23 条第 2 款「支护结构位移速率增长且不收敛」
NON_CONVERGENT_RATIO = 1.2
NON_CONVERGENT_MIN_RATE = 0.05   # mm/d，低于此值不参与判断，避免数值噪声

# --- 问题类别映射 ---------------------------------------------------------

PROBLEM_CATEGORIES: dict[str, str] = {
    # 变形过大
    "wall_top_horizontal_displacement": "变形过大",
    "wall_top_vertical_displacement": "变形过大",
    "deep_horizontal_displacement": "变形过大",
    "column_vertical_displacement": "变形过大",
    "surface_settlement": "变形过大",
    "building_settlement": "变形过大",
    "building_inclination": "变形过大",
    "pipeline_settlement": "变形过大",
    "pipeline_horizontal_displacement": "变形过大",
    "soil_layered_vertical_displacement": "变形过大",
    "road_settlement": "变形过大",
    "basal_heave": "变形过大",
    "soil_temperature": "变形过大",
    # 渗漏水 / 地下水异常
    "groundwater_level": "渗漏水与地下水异常",
    "pore_pressure": "渗漏水与地下水异常",
    "seepage_flow": "渗漏水与地下水异常",
    # 支护受力异常
    "support_axial_force": "支护受力异常",
    "anchor_axial_force": "支护受力异常",
    "wall_internal_force": "支护受力异常",
    "column_internal_force": "支护受力异常",
    "earth_pressure": "支护受力异常",
    # 裂缝
    "crack_width_building": "裂缝发展",
    "crack_width_surface": "裂缝发展",
}

# 场景画像追加的问题类别（默认为空）。注册后优先于内置映射。
EXTRA_PROBLEM_CATEGORIES: dict[str, str] = {}


def problem_category(metric_key: str) -> str:
    return EXTRA_PROBLEM_CATEGORIES.get(metric_key) or PROBLEM_CATEGORIES.get(metric_key, "其他")


def register_problem_categories(mapping: dict[str, str] | None) -> None:
    """由场景画像追加问题类别（如隧道：支护受力异常 / 结构损伤与接缝张开 / 爆破影响）。

    只做**追加**：同名 key 以场景声明为准，未声明的仍走内置基坑映射。
    默认不注册任何内容，行为与改造前一致。
    """
    if not mapping:
        return
    for key, value in mapping.items():
        if isinstance(key, str) and isinstance(value, str) and key and value:
            EXTRA_PROBLEM_CATEGORIES[key] = value


# --- 工程上下文 -----------------------------------------------------------


@dataclass
class ProjectContext:
    """判定所需的工程条件。缺失字段按弃权处理，不做推断。

    场景化说明
    ----------
    参数名 `excavation_depth_m` 沿用基坑语义（%H 判据的参照长度）。
    非基坑场景（如隧道）通过 `conditions` 声明自己的条件维度
    （施工工法 / 断面形式 / 围岩级别…），通过 `reference_lengths` 提供比例限值所需的
    参照长度（埋深 / 跨度 / 外径）。两者都是**新增可选字段**，不改变原有判定。
    """

    safety_level: str = "一级"
    support_type: str = "地下连续墙"
    excavation_depth_m: float | None = None   # 基坑设计深度 H（m）
    pipeline_type: str | None = None
    road_type: str | None = None
    crack_state: str | None = None
    post_slab: bool = False                   # 底板是否已浇筑
    design_values: dict[str, float] = field(default_factory=dict)
    danger_signals: dict[str, bool] = field(default_factory=dict)  # {"DANGER-1": True, ...}
    # (point_id, metric_key) -> [(timestamp, rate), ...]（旧→新）；
    # 兼容旧调用方按 point_id 提供历史。
    rate_history: dict[Any, list] = field(default_factory=dict)
    # 逐测点条件覆盖：{point_id: {"crack_state": ..., "pipeline_type": ..., "road_type": ...}}
    point_overrides: dict[str, dict] = field(default_factory=dict)
    # 底板浇筑日期；记录时间 >= 该日期时，速率限值按 ×0.7 折减
    post_slab_from: str | None = None
    # --- 场景扩展（新增，默认不影响既有判定）---
    scenario_id: str | None = None
    # 通用条件维度：{"construction_method": "矿山法", "rock_class": "IV", ...}
    # 与判据库 rule 的同名字段按值匹配；同时兼容 point_overrides 逐测点覆盖。
    conditions: dict[str, Any] = field(default_factory=dict)
    # 比例限值参照长度：{"buried_depth_m": 32.5, "span_m": 6.2}（单位 m）
    reference_lengths: dict[str, float] = field(default_factory=dict)

    def for_point(self, point_id: str | None) -> "ProjectContext":
        """返回某测点的有效上下文（应用逐测点条件覆盖）。"""
        if not point_id or point_id not in self.point_overrides:
            return self
        import copy as _copy

        c = _copy.copy(self)
        c.__dict__.update({k: v for k, v in self.point_overrides[point_id].items() if hasattr(self, k)})
        return c

    def condition_value(self, key: str) -> Any:
        """取某条件维度的值：conditions 优先，其次同名属性（兼容旧字段）。"""
        if key in self.conditions:
            return self.conditions[key]
        return getattr(self, key, None)

    def ref_length(self, key: str | None) -> float | None:
        """取比例限值的参照长度（m）。

        - `excavation_depth_m`（默认）沿用基坑字段，保证既有 %H 判据不变；
        - 其他 key 从 `reference_lengths` 取，缺失返回 None（判定侧弃权，不猜测）。
        """
        if key in (None, "", "excavation_depth_m"):
            v = self.excavation_depth_m
            if v is None:
                v = self.reference_lengths.get("excavation_depth_m")
        else:
            v = self.reference_lengths.get(key)
        return float(v) if _num(v) and float(v) > 0 else None

    def is_post_slab(self, timestamp: str | None) -> bool:
        """按记录时间判断是否已进入底板浇筑后阶段。"""
        if self.post_slab_from and timestamp:
            return str(timestamp) >= str(self.post_slab_from)
        return bool(self.post_slab)

    def to_dict(self) -> dict:
        return {
            "safety_level": self.safety_level,
            "support_type": self.support_type,
            "excavation_depth_m": self.excavation_depth_m,
            "pipeline_type": self.pipeline_type,
            "road_type": self.road_type,
            "crack_state": self.crack_state,
            "post_slab": self.post_slab,
            "design_values": self.design_values,
            "danger_signals": self.danger_signals,
            "scenario_id": self.scenario_id,
            "conditions": self.conditions,
            "reference_lengths": self.reference_lengths,
        }


# --- 阈值解析 -------------------------------------------------------------


def _match(spec: Any, value: str | None) -> bool:
    if spec in (None, "any", [], ""):
        return True
    if value is None:
        return False
    if isinstance(spec, list):
        return value in spec
    return spec == value


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def _pick(spec: Any, mode: str) -> float | None:
    """把规范给出的区间值解析为确定值。

    conservative -> 取下限（偏安全，默认）
    lenient      -> 取上限
    midpoint     -> 取中值
    """
    if spec is None:
        return None
    if isinstance(spec, (int, float)):
        return float(spec)
    if isinstance(spec, dict):
        lo, hi = spec.get("min"), spec.get("max")
        if _num(lo) and _num(hi):
            if mode == "conservative":
                return float(min(lo, hi))
            if mode == "lenient":
                return float(max(lo, hi))
            return float((lo + hi) / 2)
        if _num(lo):
            return float(lo)
        if _num(hi):
            return float(hi)
    return None


@dataclass
class ResolvedLimit:
    """解析后的生效限值。"""

    metric_key: str
    rule_id: str | None
    cumulative_mm: float | None = None
    cumulative_basis: str | None = None
    # 缺 H 时，cumulative_mm 只是**上界**（真实限值 = min(绝对量, %H) ≤ 绝对量）。
    # 为 True 时判定侧必须弃权，除非实测值已超过该上界。
    cumulative_upper_bound_only: bool = False
    rate_mm_per_day: float | None = None
    max_ratio_of_design: float | None = None
    min_ratio_of_design: float | None = None
    cumulative_inclination: float | None = None
    rate_inclination_per_day: float | None = None
    requires_continuous_development: bool = False
    # 比例限值所用参照长度：key + 缺失时的弃权码（基坑为 MISSING_H，隧道等为 MISSING_REF_LENGTH）
    reference_length_key: str | None = None
    missing_reference_code: str | None = None
    evidence: dict = field(default_factory=dict)
    origin: str = ORIGIN_DEFAULT
    origin_display: str = ""
    source_id: str | None = None
    source_label: str | None = None
    overridden_fields: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    looser_details: list[dict] = field(default_factory=list)   # 用户阈值比默认更宽松的明细

    def to_dict(self) -> dict:
        return {
            "metric_key": self.metric_key,
            "rule_id": self.rule_id,
            "cumulative_mm": self.cumulative_mm,
            "cumulative_basis": self.cumulative_basis,
            "cumulative_upper_bound_only": self.cumulative_upper_bound_only,
            "rate_mm_per_day": self.rate_mm_per_day,
            "max_ratio_of_design": self.max_ratio_of_design,
            "min_ratio_of_design": self.min_ratio_of_design,
            "cumulative_inclination": self.cumulative_inclination,
            "rate_inclination_per_day": self.rate_inclination_per_day,
            "reference_length_key": self.reference_length_key,
            "missing_reference_code": self.missing_reference_code,
            "evidence": self.evidence,
            "origin": self.origin,
            "origin_display": self.origin_display,
            "source_id": self.source_id,
            "source_label": self.source_label,
            "overridden_fields": self.overridden_fields,
            "flags": self.flags,
            "looser_details": self.looser_details,
        }


def resolve_limit(
    registry: StandardsRegistry,
    metric_key: str,
    ctx: ProjectContext,
    timestamp: str | None = None,
) -> ResolvedLimit:
    """在规范库中解析某监测项在当前条件下的生效限值。"""
    node = registry.get_metric(metric_key)
    if node is None:
        return ResolvedLimit(
            metric_key=metric_key,
            rule_id=None,
            origin=ORIGIN_DEFAULT,
            source_id=registry.sources[0].source_id if registry.sources else None,
            flags=["UNKNOWN_METRIC"],
        )

    rules = node["rules"]
    # 条件维度：优先用规范库注册表注入的场景维度（隧道含 construction_method 等），
    # 缺省回落改造前的 5 个基坑维度。
    dims = tuple(
        getattr(registry, "condition_dimensions", None)
        or ("safety_level", "support_type", "pipeline_type", "road_type", "crack_state")
    )
    spec_dims = tuple(
        getattr(registry, "specificity_dimensions", None)
        or ("support_type", "pipeline_type", "road_type", "crack_state")
    )
    candidates = []
    for rid, rule in rules.items():
        ok = True
        # requires_conditions：该规则**必须**由调用方给出这些维度才能适用。
        # 用于区分"按管型/保护对象分档"的判据 —— 缺维度时若按通配处理，
        # 会在燃气/雨污水/供水之间随机命中最严或最松的一组，属于猜测。
        missing_req = [
            k for k in (rule.get("requires_conditions") or [])
            if ctx.condition_value(k) is None
        ]
        if missing_req:
            continue
        for k in dims:
            value = ctx.condition_value(k)
            if value is None:
                # 与改造前语义一致：调用方未提供的维度不参与筛选（视为通配）
                continue
            if not _match(rule.get(k), value):
                ok = False
                break
        if ok:
            spec = sum(1 for k in spec_dims if rule.get(k) not in (None, "any", []))
            candidates.append((rid, rule, spec))

    if not candidates:
        return ResolvedLimit(
            metric_key=metric_key,
            rule_id=None,
            origin=ORIGIN_DEFAULT,
            source_id=registry.sources[0].source_id if registry.sources else None,
            flags=["NO_APPLICABLE_RULE"],
        )

    # 命中多条时：优先用户上传规范（字段级覆盖），其次条件描述更具体的一条
    def rank(item: tuple[str, dict, int]) -> tuple[int, int]:
        rid, _rule, spec = item
        origins = registry.get_rule_origins(metric_key, rid)
        user_rank = 1 if any(o == ORIGIN_USER for o in origins.values()) else 0
        return (user_rank, spec)

    rid, rule, _ = max(candidates, key=rank)
    origins = registry.get_rule_origins(metric_key, rid)

    def origin_of(field_name: str) -> str:
        return origins.get(field_name, ORIGIN_DEFAULT)

    lim = ResolvedLimit(
        metric_key=metric_key,
        rule_id=rid,
        evidence=rule.get("evidence", {}),
        requires_continuous_development=bool(rule.get("requires_continuous_development")),
    )

    # --- 累计值限值：绝对量 与 相对 H 的限值 取小值 ---
    #
    # 安全边界（原 P1-2）：判据含 %H 分量时，**绝不允许**在缺 H 的情况下
    # 退回"只用绝对量限值"。真实限值 = min(绝对量, %H) ≤ 绝对量，
    # 用绝对量替代会把判定放宽，且 H 越浅偏松越多
    # （H=5 m 时 0.2%×H = 10 mm，绝对量 20 mm，偏松 100%）。
    #
    # 缺 H 时的处理：把绝对量记作**上界**（cumulative_upper_bound_only）——
    # 实测值已超上界 → 真实限值更小，超限结论仍成立，正常判定；
    # 未超上界 → 无法排除真实限值更小，判定侧弃权（MISSING_H），不判"正常"。
    abs_limit = _pick(rule.get("cumulative_mm"), registry.range_resolution)

    # --- 比例限值：参照长度可配置（基坑 = 设计深度 H；隧道 = 埋深/跨度/外径） ---
    # 写法一（新）：cumulative_pct_ref = {"ref": "buried_depth_m", "pct": 0.2}
    # 写法二（旧，保持不变）：cumulative_pct_H = 0.2，参照量固定为基坑设计深度 H
    ref_spec = rule.get("cumulative_pct_ref")
    if isinstance(ref_spec, dict):
        ref_key: str | None = str(ref_spec.get("ref") or "") or None
        declares_pct = True
        pct_value = _pick(
            ref_spec["pct"] if "pct" in ref_spec else ref_spec.get("value"),
            registry.range_resolution,
        )
        missing_code = "MISSING_REF_LENGTH"
    else:
        ref_key = "excavation_depth_m"
        pct_spec = rule.get("cumulative_pct_H")
        declares_pct = _num(pct_spec) or isinstance(pct_spec, dict)
        pct_value = _pick(pct_spec, registry.range_resolution) if declares_pct else None
        missing_code = "MISSING_H"

    if declares_pct and pct_value is not None:
        lim.reference_length_key = ref_key
        lim.missing_reference_code = missing_code

    ref_value = ctx.ref_length(ref_key) if ref_key else None
    has_ref = ref_value is not None
    # pct[%] × 参照长度[m] × 10 = mm（与 %H 换算同口径）
    pct_limit = (
        pct_value * ref_value * 10.0
        if (pct_value is not None and has_ref)
        else None
    )
    ref_missing = declares_pct and pct_value is not None and not has_ref
    ref_label_full = registry.reference_length_label(ref_key)
    ref_label = "H" if ref_key == "excavation_depth_m" else ref_label_full
    if ref_missing:
        for flag in (
            "PCT_H_NOT_EVALUATED" if missing_code == "MISSING_H" else "PCT_REF_NOT_EVALUATED",
            missing_code,
        ):
            if flag not in lim.flags:
                lim.flags.append(flag)

    if abs_limit is not None and pct_limit is not None:
        lim.cumulative_mm = min(abs_limit, pct_limit)
        lim.cumulative_basis = (
            f"min(绝对量 {abs_limit:g} mm, {pct_value:g}%×{ref_label}={pct_limit:g} mm) = {lim.cumulative_mm:g} mm"
        )
    elif ref_missing and abs_limit is not None:
        lim.cumulative_mm = abs_limit
        lim.cumulative_upper_bound_only = True
        lim.cumulative_basis = (
            f"⚠ 未提供{ref_label_full}，无法换算 {pct_value:g}%×{ref_label}；"
            f"绝对量限值 {abs_limit:g} mm 仅作为**上界**"
            f"（真实限值 = min(绝对量, {pct_value:g}%×{ref_label}) ≤ {abs_limit:g} mm），"
            f"实测值未超上界时不得判为正常"
        )
    elif abs_limit is not None:
        lim.cumulative_mm = abs_limit
        lim.cumulative_basis = f"绝对量限值 {abs_limit:g} mm"
    elif pct_limit is not None:
        lim.cumulative_mm = pct_limit
        lim.cumulative_basis = f"{pct_value:g}%×{ref_label} = {pct_limit:g} mm"
    elif ref_missing:
        lim.cumulative_upper_bound_only = True
        lim.cumulative_basis = (
            f"⚠ 未提供{ref_label_full}，无法换算 {pct_value:g}%×{ref_label}，"
            f"且该规则未给出绝对量限值，累计值无法判定"
        )

    # --- 速率限值（含底板浇筑后折减） ---
    rate = _pick(rule.get("rate_mm_per_day"), registry.range_resolution)
    if rate is not None and ctx.is_post_slab(timestamp):
        factor = registry.post_slab_policy.get("rate_factor_after_slab", 0.7)
        rate = rate * factor
        lim.flags.append("POST_SLAB_RATE_REDUCED")
    lim.rate_mm_per_day = rate

    lim.max_ratio_of_design = _pick(rule.get("max_ratio_of_design"), registry.range_resolution)
    lim.min_ratio_of_design = _pick(rule.get("min_ratio_of_design"), registry.range_resolution)
    lim.cumulative_inclination = _pick(rule.get("cumulative_inclination"), registry.range_resolution)
    lim.rate_inclination_per_day = _pick(rule.get("rate_inclination_per_day"), registry.range_resolution)

    # --- 生效来源：取本条规则中"最高优先级"的字段来源 ---
    if any(o == ORIGIN_USER for o in origins.values()):
        lim.origin = ORIGIN_USER
    else:
        lim.origin = ORIGIN_DEFAULT
    lim.origin_display = registry.origin_display(lim.origin)

    user_src = next((s for s in registry.sources if s.origin == ORIGIN_USER), None)
    def_src = next((s for s in registry.sources if s.origin == ORIGIN_DEFAULT), None)
    chosen = user_src if lim.origin == ORIGIN_USER else def_src
    if chosen:
        lim.source_id = chosen.source_id
        lim.source_label = chosen.source_label
    lim.overridden_fields = [
        f for f, o in origins.items() if o == ORIGIN_USER
    ]

    # --- 用户阈值宽松度校验（只反馈、不阻断） ---
    if lim.origin == ORIGIN_USER:
        try:
            from limit_strictness import (
                INCOMPARABLE_FLAG,
                LOOSER_FLAG,
                compare_rule_strictness,
                find_default_rule,
            )

            default_rule, _how = find_default_rule(registry, metric_key, rule, rid)
            if default_rule is not None:
                comps = compare_rule_strictness(
                    metric_key, rule, default_rule, registry, ctx,
                    metric_name=metric_key,
                    user_evidence=rule.get("evidence"),
                    default_evidence=default_rule.get("evidence"),
                    user_rule_id=rid,
                    effective_rule=rule,                      # rule 已是合并后的生效规则
                    scope_fields=set(lim.overridden_fields),  # 只比较用户覆盖的字段
                )
                looser = [c for c in comps if c["direction"] == "looser"]
                incomparable = [c for c in comps if c["direction"] == "incomparable"]
                if looser:
                    lim.looser_details = looser
                    if LOOSER_FLAG not in lim.flags:
                        lim.flags.append(LOOSER_FLAG)
                if incomparable and INCOMPARABLE_FLAG not in lim.flags:
                    lim.flags.append(INCOMPARABLE_FLAG)
        except Exception:  # noqa: BLE001 - 校验失败不得影响判定主流程
            pass

    return lim


# --- 判定 -----------------------------------------------------------------


@dataclass
class RiskJudgment:
    """单项风险判定结果。"""

    metric_key: str
    point_id: str | None
    timestamp: str | None
    data_origin: str
    risk_level: str = LEVEL_UNKNOWN
    utilization: float | None = None
    problem_category: str = "其他"
    checks: list[dict] = field(default_factory=list)
    effective_source: dict = field(default_factory=dict)
    rule_id: str | None = None
    evidence: dict = field(default_factory=dict)
    abstain: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    calc: dict = field(default_factory=dict)
    # 规范原文口径的管理等级（如按 U/U0 分三级）；本系统五级分级不因此改变。
    management_level: dict | None = None
    # 收敛稳定性（是否满足规范给出的"可降低频率/停测"量化条件）
    stability: dict | None = None
    # 断面归属（由调用方的显式映射给出；缺失为 None，不做推断）
    section_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "metric_key": self.metric_key,
            "point_id": self.point_id,
            "timestamp": self.timestamp,
            "data_origin": self.data_origin,
            "problem_category": self.problem_category,
            "risk_level": self.risk_level,
            "utilization": self.utilization,
            "checks": self.checks,
            "effective_source": self.effective_source,
            "rule_id": self.rule_id,
            "evidence": self.evidence,
            "abstain": self.abstain,
            "abstain_reasons": [ABSTAIN_REASONS.get(a, a) for a in self.abstain],
            "flags": self.flags,
            "calc": self.calc,
            "management_level": self.management_level,
            "stability": self.stability,
            "section_id": self.section_id,
        }


def _grade(utilization: float | None) -> str:
    if utilization is None:
        return LEVEL_UNKNOWN
    if utilization >= BAND_DANGER:
        return LEVEL_DANGER
    if utilization >= 1.0:
        return LEVEL_ALARM
    if utilization >= BAND_WARNING:
        return LEVEL_WARNING
    if utilization >= BAND_ATTENTION:
        return LEVEL_ATTENTION
    return LEVEL_NORMAL


def _higher(a: str, b: str) -> str:
    ra, rb = _LEVEL_RANK.get(a, -1), _LEVEL_RANK.get(b, -1)
    return a if ra >= rb else b


def _recent_rates(history: Sequence, timestamp: str | None = None, n: int = 3) -> list[float]:
    """取当前记录**之前**的 n 期速率。

    两种历史写法：
      - `(timestamp, rate)` 二元组：按时间过滤，只保留早于当前记录的部分；
      - 纯 `rate` 数值：整份列表即"当前之前"的历史，不做裁剪。
    """
    if not history:
        return []
    items = list(history)
    if items and isinstance(items[0], (tuple, list)) and len(items[0]) == 2:
        pairs = [(str(t), r) for t, r in items if _num(r)]
        if timestamp:
            pairs = [(t, r) for t, r in pairs if t < str(timestamp)]
        else:
            pairs = pairs[:-1]      # 无时间戳可对齐时，默认最后一期为"当前"
        vals = [r for _t, r in pairs]
    else:
        vals = [r for r in items if _num(r)]
    return vals[-n:]


def _consecutive_over_70(rate_history: Sequence, limit: float | None, timestamp: str | None = None) -> bool:
    """连续 3 期速率超过限值 70%。依据：GB 50497-2019 第 8.0.3 条 / 表 8.0.4 注。"""
    if not _num(limit) or not limit:
        return False
    tail = _recent_rates(rate_history, timestamp, n=3)
    if len(tail) < 3:
        return False
    return all(r > 0.7 * limit for r in tail)


def _non_convergent(rate: float | None, slope: float | None) -> bool:
    """变形是否"速率增长且不收敛"（当前速率显著高于序列平均速率）。

    依据：JGJ 120-2012 第 8.2.23 条第 2 款。
    加速序列的瞬时速率会高于最小二乘平均速率；收敛序列则相反。
    """
    if not _num(rate) or not _num(slope):
        return False
    if abs(rate) < NON_CONVERGENT_MIN_RATE:
        return False
    return abs(rate) > abs(slope) * NON_CONVERGENT_RATIO


def judge(
    calc: Any,
    registry: StandardsRegistry,
    ctx: ProjectContext,
    blocked_issues: Sequence[str] | None = None,
) -> RiskJudgment:
    """对阶段二的一项确定性计算结果做规范比对，输出风险等级。

    blocked_issues 为该期记录的高严重度数据质量问题码；非空时**弃权**，
    不做数值判定，并归入「数据质量异常」问题类别。
    """
    blocked = [c for c in (blocked_issues or []) if c in BLOCKING_ISSUE_CODES]

    j = RiskJudgment(
        metric_key=calc.metric_key,
        point_id=calc.point_id,
        timestamp=calc.timestamp,
        data_origin=getattr(calc, "data_origin", "real"),
        problem_category="数据质量异常" if blocked else problem_category(calc.metric_key),
        abstain=list(calc.abstain),
        flags=list(calc.flags),
        calc=calc.to_dict(),
    )

    if blocked:
        j.abstain.append("DATA_QUALITY_BLOCKED")
        j.flags.extend(f"DQ:{c}" for c in blocked if f"DQ:{c}" not in j.flags)
        j.risk_level = LEVEL_UNKNOWN
        j.effective_source = {
            "origin": ORIGIN_DEFAULT,
            "origin_display": registry.origin_display(ORIGIN_DEFAULT),
            "source_id": None,
            "source_label": None,
            "rule_id": None,
            "overridden_fields": [],
        }
        j.checks.append(
            {
                "check": "数据质量前置校验",
                "blocked_issues": blocked,
                "verdict": LEVEL_UNKNOWN,
                "note": "高严重度数据质量问题，按安全原则不参与风险判定",
            }
        )
        return j

    ctx = ctx.for_point(calc.point_id)
    lim = resolve_limit(registry, calc.metric_key, ctx, timestamp=calc.timestamp)
    j.rule_id = lim.rule_id
    j.evidence = lim.evidence
    j.effective_source = {
        "origin": lim.origin,
        "origin_display": lim.origin_display,
        "source_id": lim.source_id,
        "source_label": lim.source_label,
        "rule_id": lim.rule_id,
        "overridden_fields": lim.overridden_fields,
        "looser_details": lim.looser_details,
    }
    j.flags.extend(f for f in lim.flags if f not in j.flags)

    # 比例限值参照长度缺失时的弃权码与标记：
    # 基坑沿用 MISSING_H（既有回归依赖该码），其他场景用 MISSING_REF_LENGTH。
    miss_code = lim.missing_reference_code or "MISSING_H"
    miss_flag = (
        "H_MISSING_CUMULATIVE_ABSTAINED"
        if miss_code == "MISSING_H"
        else "REF_MISSING_CUMULATIVE_ABSTAINED"
    )
    ref_label_full = registry.reference_length_label(lim.reference_length_key)

    if lim.flags and lim.flags[0] in ("UNKNOWN_METRIC", "NO_APPLICABLE_RULE"):
        j.abstain.append(lim.flags[0])
        j.risk_level = LEVEL_UNKNOWN
        return j

    utils: list[float] = []
    level = LEVEL_NORMAL
    # 收敛性判据不产生利用率（utils），但确实决定等级，单独记一个标记。
    # 最终"是否真正判定过"= bool(utils) or convergence_fired，
    # **不能**用 bool(j.checks) —— 否则"缺 H 不可判定"这类说明性 check
    # 会把弃权项撑成"正常"。
    convergence_fired = False

    # --- 1) 累计值校核 ---
    # 缺 H 时 lim.cumulative_mm 只是上界（见 resolve_limit）：
    #   超过上界 → 真实限值更小，超限结论成立，照常判定；
    #   未超上界 → 无法排除真实限值更小，弃权，**不判"正常"**。
    if _num(calc.cumulative) and _num(lim.cumulative_mm) and lim.cumulative_mm:
        u = abs(calc.cumulative) / abs(lim.cumulative_mm)
        if lim.cumulative_upper_bound_only and u < 1.0:
            if miss_code not in j.abstain:
                j.abstain.append(miss_code)
            if miss_flag not in j.flags:
                j.flags.append(miss_flag)
            j.checks.append(
                {
                    "check": "累计值（缺参照长度，不可判定）",
                    "value": round(calc.cumulative, 4),
                    "limit": round(lim.cumulative_mm, 4),
                    "limit_basis": lim.cumulative_basis,
                    "utilization": round(u, 4),
                    "limit_is_upper_bound": True,
                    "verdict": LEVEL_UNKNOWN,
                    "note": f"未提供{ref_label_full}，累计值限值只能给出上界；实测值未超上界，"
                            "但无法排除真实限值更小，按安全原则不判定",
                }
            )
        else:
            utils.append(u)
            check = {
                "check": "累计值",
                "value": round(calc.cumulative, 4),
                "limit": round(lim.cumulative_mm, 4),
                "limit_basis": lim.cumulative_basis,
                "utilization": round(u, 4),
                "verdict": _grade(u),
            }
            if lim.cumulative_upper_bound_only:
                # 已超上界 ⇒ 必然超真实限值，结论成立；标明这是保守判定
                check["limit_is_upper_bound"] = True
                check["note"] = f"缺{ref_label_full}，实测值已超过绝对量上界，超限结论必然成立"
            j.checks.append(check)
            level = _higher(level, _grade(u))
    elif _num(lim.cumulative_mm):
        j.flags.append("CUMULATIVE_NOT_EVALUATED")
    elif lim.cumulative_upper_bound_only:
        if miss_code not in j.abstain:
            j.abstain.append(miss_code)
        if miss_flag not in j.flags:
            j.flags.append(miss_flag)
    elif not _num(lim.cumulative_mm) and "PCT_H_NOT_EVALUATED" not in j.flags:
        j.flags.append("NO_CUMULATIVE_LIMIT")

    # --- 2) 变化速率校核 ---
    history = []
    if ctx.rate_history:
        history = (
            ctx.rate_history.get((calc.point_id or "", calc.metric_key))
            or ctx.rate_history.get(calc.point_id or "", [])
        )
    if _num(calc.rate) and _num(lim.rate_mm_per_day) and lim.rate_mm_per_day:
        u = abs(calc.rate) / abs(lim.rate_mm_per_day)
        utils.append(u)
        over3 = _consecutive_over_70(history, lim.rate_mm_per_day, calc.timestamp)
        verdict = _grade(u)
        if over3 and _LEVEL_RANK[verdict] < _LEVEL_RANK[LEVEL_WARNING]:
            verdict = LEVEL_WARNING
        j.checks.append(
            {
                "check": "变化速率",
                "value": round(calc.rate, 4),
                "limit": round(lim.rate_mm_per_day, 4),
                "limit_basis": (
                    "底板浇筑后速率限值 ×0.7" if "POST_SLAB_RATE_REDUCED" in j.flags else "规范速率预警值"
                ),
                "utilization": round(u, 4),
                "consecutive_over_70": over3,
                "verdict": verdict,
            }
        )
        level = _higher(level, verdict)
    elif _num(lim.rate_mm_per_day):
        j.flags.append("RATE_NOT_EVALUATED")

    # --- 2b) 不收敛判据（JGJ 120-2012 §8.2.23-2） ---
    if _non_convergent(calc.rate, calc.slope):
        j.flags.append("NON_CONVERGENT")
        j.checks.append(
            {
                "check": "位移收敛性",
                "value": round(calc.rate, 4),
                "limit": round(calc.slope, 4),
                "limit_basis": f"当前速率 {calc.rate:.3f} mm/d > 序列平均速率 {calc.slope:.3f} mm/d × {NON_CONVERGENT_RATIO}，变形在加速",
                "verdict": LEVEL_WARNING,
            }
        )
        level = _higher(level, LEVEL_WARNING)
        convergence_fired = True

    # --- 3) 设计值比例校核（内力/轴力类） ---
    design = ctx.design_values.get(calc.metric_key)
    if _num(lim.max_ratio_of_design) or _num(lim.min_ratio_of_design):
        if not _num(design):
            j.abstain.append("MISSING_DESIGN_VALUE")
            j.flags.append("DESIGN_RATIO_NOT_EVALUATED")
        else:
            if _num(lim.max_ratio_of_design) and _num(calc.current):
                u = abs(calc.current) / (abs(design) * abs(lim.max_ratio_of_design))
                utils.append(u)
                j.checks.append(
                    {
                        "check": "实测值 / (设计值 × 控制比例)",
                        "value": round(calc.current, 4),
                        "limit": round(abs(design) * abs(lim.max_ratio_of_design), 4),
                        "limit_basis": f"设计值 {design:g} × {lim.max_ratio_of_design:g}",
                        "utilization": round(u, 4),
                        "verdict": _grade(u),
                    }
                )
                level = _higher(level, _grade(u))
            if _num(lim.min_ratio_of_design) and _num(calc.current) and abs(calc.current) > 0:
                floor = abs(design) * abs(lim.min_ratio_of_design)
                u = floor / abs(calc.current)   # >1 即低于下限（预应力损失/锚杆松弛）
                utils.append(u)
                j.checks.append(
                    {
                        "check": "设计值下限（预应力损失/锚杆松弛）",
                        "value": round(calc.current, 4),
                        "limit": round(floor, 4),
                        "limit_basis": f"设计值 {design:g} × {lim.min_ratio_of_design:g}",
                        "utilization": round(u, 4),
                        "breached": u > 1.0,
                        "verdict": _grade(u),
                    }
                )
                level = _higher(level, _grade(u))

    # --- 4) 倾斜类校核 ---
    if _num(lim.cumulative_inclination) and _num(calc.cumulative):
        u = abs(calc.cumulative) / abs(lim.cumulative_inclination)
        utils.append(u)
        j.checks.append(
            {
                "check": "累计倾斜",
                "value": round(calc.cumulative, 6),
                "limit": lim.cumulative_inclination,
                "utilization": round(u, 4),
                "verdict": _grade(u),
            }
        )
        level = _higher(level, _grade(u))

    evaluated = bool(utils) or convergence_fired
    if not evaluated and not any(
        reason in j.abstain for reason in ("MISSING_DESIGN_VALUE", "MISSING_H", "MISSING_REF_LENGTH")
    ):
        j.abstain.append("NO_LIMIT")

    j.utilization = round(max(utils), 4) if utils else None

    # --- 4b) 规范原文口径的附加结论（隧道等场景；判据库没有对应字段时跳过） ---
    # 这两项都**不改变** risk_level：管理等级是规范的分档表述，稳定性是"能否降低频率/停测"
    # 的量化条件，二者都是给工程师对照用的附加结论。
    metric_meta = (registry.get_metric(calc.metric_key) or {}).get("metric") or {}

    # 位移管理等级：规范多用「实测位移 U / 设计极限位移 U0」分档（如 JTG/T 3660-2020 表 18.6.3）。
    # 该口径需要设计给出的极限位移（常用设计预留变形量），缺值时**不猜**，只披露缺什么。
    ml_cfg = metric_meta.get("management_levels")
    ml_levels = ml_cfg.get("levels") if isinstance(ml_cfg, dict) else ml_cfg
    ml_ratio = j.utilization
    ml_missing = ""
    if isinstance(ml_cfg, dict) and ml_cfg.get("base") == "design_value":
        dv = ctx.design_values.get(ml_cfg.get("design_value_key") or calc.metric_key)
        if _num(dv) and abs(float(dv)) > 0 and _num(calc.cumulative):
            ml_ratio = abs(float(calc.cumulative)) / abs(float(dv))
        else:
            ml_ratio = None
            ml_missing = (
                f"缺设计极限位移（{ml_cfg.get('design_value_key') or calc.metric_key}），"
                "无法按规范 U/U0 分档"
            )
    ml = evaluate_management_level(ml_levels, ml_ratio)
    if ml is not None:
        if isinstance(ml_cfg, dict) and ml_cfg.get("base") == "design_value":
            ml["base"] = "design_value"
            ml["base_display"] = "实测位移 / 设计极限位移 U0"
        else:
            ml["base"] = "control_value"
            ml["base_display"] = "实测值 / 生效控制值（U0 未知时的替代口径，需工程师确认）"
        j.management_level = ml
        j.checks.append(
            {
                "check": "位移管理等级（规范分档）",
                "level": ml.get("code"),
                "label": ml.get("label"),
                "action": ml.get("action"),
                "utilization": ml.get("utilization"),
                "base": ml.get("base"),
                "evidence": ml.get("evidence"),
                "verdict": LEVEL_NORMAL if not ml.get("above_all_bands") else LEVEL_ALARM,
                "note": "规范原文分档，与五级风险分级并列展示，不互相替代。",
            }
        )
    elif ml_missing:
        if "MGMT_LEVEL_NOT_EVALUATED" not in j.flags:
            j.flags.append("MGMT_LEVEL_NOT_EVALUATED")
        j.checks.append(
            {
                "check": "位移管理等级（规范分档）",
                "verdict": LEVEL_UNKNOWN,
                "note": ml_missing + "；请补充设计预留变形量/极限位移后复核。",
            }
        )

    stab_cfg = metric_meta.get("stability_criterion")
    stab = evaluate_stability(
        stab_cfg,
        history,
        timestamp=calc.timestamp,
        current_rate=calc.rate,
    )
    if stab.get("status") != STATUS_NO_CRITERION:
        rate_state = evaluate_rate_state(stab_cfg, calc.rate)
        if rate_state:
            stab["rate_state"] = rate_state
        j.stability = stab
        j.checks.append(
            {
                "check": "收敛稳定性 / 可停测量化条件",
                "status": stab.get("status"),
                "status_display": stab.get("status_display"),
                "threshold": stab.get("threshold"),
                "consecutive_periods": stab.get("consecutive_periods"),
                "observed_rates": stab.get("observed_rates"),
                "rate_state": rate_state,
                "evidence": stab.get("evidence"),
                "verdict": LEVEL_UNKNOWN,
                "note": "只回答是否满足规范给出的量化条件；是否降低频率或停测由工程师决定。",
            }
        )

    # --- 5) 危险报警条件（GB 50497-2019 第 8.0.9 条，强制性条文） ---
    hit_danger: list[dict] = []
    for cond in registry.danger_conditions:
        code = cond.get("code")
        if ctx.danger_signals.get(code):
            hit_danger.append(cond)
    if hit_danger:
        level = LEVEL_DANGER
        j.checks.append(
            {
                "check": "危险报警条件",
                "matched": [c.get("code") for c in hit_danger],
                "conditions": [c.get("condition") for c in hit_danger],
                "evidence": [c.get("evidence") for c in hit_danger],
                "verdict": LEVEL_DANGER,
            }
        )

    # --- 5b) 缺参照长度降级：累计值限值无法确定时，不得给出"正常"结论 ---
    # 其余校核（如速率）给出更高等级时保留该等级；只有落在"正常"才降为未知。
    if (
        ("MISSING_H" in j.abstain or "MISSING_REF_LENGTH" in j.abstain)
        and level == LEVEL_NORMAL
    ):
        level = LEVEL_UNKNOWN

    # --- 6) 数据质量降级：阶段一标记的问题不得被判为"正常" ---
    if not calc.ok and level == LEVEL_NORMAL:
        level = LEVEL_UNKNOWN

    if not (evaluated or hit_danger):
        j.risk_level = LEVEL_UNKNOWN
    else:
        j.risk_level = level
    return j


def judge_batch(
    calcs: Sequence[Any],
    registry: StandardsRegistry,
    ctx: ProjectContext,
    blocked_map: dict[tuple, list[str]] | None = None,
) -> list[RiskJudgment]:
    """``blocked_map`` 以 ``(point_id, metric_key, timestamp)`` 为键。

    兼容旧调用方提供的 ``(point_id, timestamp)`` 键。
    """
    blocked_map = blocked_map or {}
    return [
        judge(
            c,
            registry,
            ctx,
            blocked_issues=(
                blocked_map.get((c.point_id, c.metric_key, c.timestamp))
                or blocked_map.get((c.point_id, c.timestamp))
            ),
        )
        for c in calcs
    ]


def summarize(judgments: Sequence[RiskJudgment]) -> dict:
    """汇总：按等级、问题类别、数据来源分别统计。"""
    by_level: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_origin: dict[str, int] = {}
    abstain: dict[str, int] = {}
    worst = LEVEL_UNKNOWN
    for j in judgments:
        by_level[j.risk_level] = by_level.get(j.risk_level, 0) + 1
        by_category[j.problem_category] = by_category.get(j.problem_category, 0) + 1
        by_origin[j.data_origin] = by_origin.get(j.data_origin, 0) + 1
        for a in j.abstain:
            abstain[a] = abstain.get(a, 0) + 1
        if _LEVEL_RANK.get(j.risk_level, -1) > _LEVEL_RANK.get(worst, -1):
            worst = j.risk_level
    return {
        "total": len(judgments),
        "by_risk_level": by_level,
        "by_problem_category": by_category,
        "by_data_origin": by_origin,   # 真实数据与模拟数据分开统计
        "abstain": abstain,
        "overall_risk_level": worst,
    }
