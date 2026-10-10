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
    "NO_APPLICABLE_RULE": "当前安全等级/支护形式组合下无适用判据",
    "NO_LIMIT": "该监测项在当前条件下未给出可比对的限值",
    "MISSING_DESIGN_VALUE": "该监测项需按设计值校核，但未提供设计值",
    "MISSING_H": "该监测项需按基坑设计深度 H 校核，但未提供 H",
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


def problem_category(metric_key: str) -> str:
    return PROBLEM_CATEGORIES.get(metric_key, "其他")


# --- 工程上下文 -----------------------------------------------------------


@dataclass
class ProjectContext:
    """判定所需的工程条件。缺失字段按弃权处理，不做推断。"""

    safety_level: str = "一级"
    support_type: str = "地下连续墙"
    excavation_depth_m: float | None = None   # 基坑设计深度 H（m）
    pipeline_type: str | None = None
    road_type: str | None = None
    crack_state: str | None = None
    post_slab: bool = False                   # 底板是否已浇筑
    design_values: dict[str, float] = field(default_factory=dict)
    danger_signals: dict[str, bool] = field(default_factory=dict)  # {"DANGER-1": True, ...}
    # point_id -> [(timestamp, rate), ...]（旧→新）；也兼容直接给 [rate, ...]
    rate_history: dict[str, list] = field(default_factory=dict)
    # 逐测点条件覆盖：{point_id: {"crack_state": ..., "pipeline_type": ..., "road_type": ...}}
    point_overrides: dict[str, dict] = field(default_factory=dict)
    # 底板浇筑日期；记录时间 >= 该日期时，速率限值按 ×0.7 折减
    post_slab_from: str | None = None

    def for_point(self, point_id: str | None) -> "ProjectContext":
        """返回某测点的有效上下文（应用逐测点条件覆盖）。"""
        if not point_id or point_id not in self.point_overrides:
            return self
        import copy as _copy

        c = _copy.copy(self)
        c.__dict__.update({k: v for k, v in self.point_overrides[point_id].items() if hasattr(self, k)})
        return c

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
    candidates = []
    for rid, rule in rules.items():
        if (
            _match(rule.get("safety_level"), ctx.safety_level)
            and _match(rule.get("support_type"), ctx.support_type)
            and (ctx.pipeline_type is None or _match(rule.get("pipeline_type"), ctx.pipeline_type))
            and (ctx.road_type is None or _match(rule.get("road_type"), ctx.road_type))
            and (ctx.crack_state is None or _match(rule.get("crack_state"), ctx.crack_state))
        ):
            spec = sum(
                1
                for k in ("support_type", "pipeline_type", "road_type", "crack_state")
                if rule.get(k) not in (None, "any", [])
            )
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
    pct_spec = rule.get("cumulative_pct_H")
    declares_pct = _num(pct_spec) or isinstance(pct_spec, dict)
    pct_value = _pick(pct_spec, registry.range_resolution) if declares_pct else None
    has_h = _num(ctx.excavation_depth_m) and ctx.excavation_depth_m > 0

    pct_limit = (
        pct_value * ctx.excavation_depth_m * 10.0   # pct[%] × H[m] × 10 = mm
        if (pct_value is not None and has_h)
        else None
    )
    h_missing = declares_pct and pct_value is not None and not has_h
    if h_missing:
        if "PCT_H_NOT_EVALUATED" not in lim.flags:
            lim.flags.append("PCT_H_NOT_EVALUATED")
        if "MISSING_H" not in lim.flags:
            lim.flags.append("MISSING_H")

    if abs_limit is not None and pct_limit is not None:
        lim.cumulative_mm = min(abs_limit, pct_limit)
        lim.cumulative_basis = (
            f"min(绝对量 {abs_limit:g} mm, {pct_value:g}%×H={pct_limit:g} mm) = {lim.cumulative_mm:g} mm"
        )
    elif h_missing and abs_limit is not None:
        lim.cumulative_mm = abs_limit
        lim.cumulative_upper_bound_only = True
        lim.cumulative_basis = (
            f"⚠ 未提供基坑设计深度 H，无法换算 {pct_value:g}%×H；"
            f"绝对量限值 {abs_limit:g} mm 仅作为**上界**"
            f"（真实限值 = min(绝对量, {pct_value:g}%×H) ≤ {abs_limit:g} mm），"
            f"实测值未超上界时不得判为正常"
        )
    elif abs_limit is not None:
        lim.cumulative_mm = abs_limit
        lim.cumulative_basis = f"绝对量限值 {abs_limit:g} mm"
    elif pct_limit is not None:
        lim.cumulative_mm = pct_limit
        lim.cumulative_basis = f"{pct_value:g}%×H = {pct_limit:g} mm"
    elif h_missing:
        lim.cumulative_upper_bound_only = True
        lim.cumulative_basis = (
            f"⚠ 未提供基坑设计深度 H，无法换算 {pct_value:g}%×H，"
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
    lim.origin_display = {
        ORIGIN_DEFAULT: "默认规范库（基坑智守项目相关规范）",
        ORIGIN_USER: "用户上传规范",
    }[lim.origin]

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
            "origin_display": "默认规范库（基坑智守项目相关规范）",
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
            if "MISSING_H" not in j.abstain:
                j.abstain.append("MISSING_H")
            if "H_MISSING_CUMULATIVE_ABSTAINED" not in j.flags:
                j.flags.append("H_MISSING_CUMULATIVE_ABSTAINED")
            j.checks.append(
                {
                    "check": "累计值（缺 H，不可判定）",
                    "value": round(calc.cumulative, 4),
                    "limit": round(lim.cumulative_mm, 4),
                    "limit_basis": lim.cumulative_basis,
                    "utilization": round(u, 4),
                    "limit_is_upper_bound": True,
                    "verdict": LEVEL_UNKNOWN,
                    "note": "未提供基坑设计深度 H，累计值限值只能给出上界；实测值未超上界，"
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
                check["note"] = "缺 H，实测值已超过绝对量上界，超限结论必然成立"
            j.checks.append(check)
            level = _higher(level, _grade(u))
    elif _num(lim.cumulative_mm):
        j.flags.append("CUMULATIVE_NOT_EVALUATED")
    elif lim.cumulative_upper_bound_only:
        if "MISSING_H" not in j.abstain:
            j.abstain.append("MISSING_H")
        if "H_MISSING_CUMULATIVE_ABSTAINED" not in j.flags:
            j.flags.append("H_MISSING_CUMULATIVE_ABSTAINED")
    elif not _num(lim.cumulative_mm) and "PCT_H_NOT_EVALUATED" not in j.flags:
        j.flags.append("NO_CUMULATIVE_LIMIT")

    # --- 2) 变化速率校核 ---
    history = ctx.rate_history.get(calc.point_id or "", []) if ctx.rate_history else []
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
        reason in j.abstain for reason in ("MISSING_DESIGN_VALUE", "MISSING_H")
    ):
        j.abstain.append("NO_LIMIT")

    j.utilization = round(max(utils), 4) if utils else None

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

    # --- 5b) 缺 H 降级：累计值限值无法确定时，不得给出"正常"结论 ---
    # 其余校核（如速率）给出更高等级时保留该等级；只有落在"正常"才降为未知。
    if "MISSING_H" in j.abstain and level == LEVEL_NORMAL:
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
    """blocked_map: {(point_id, timestamp): [问题码, ...]}，来自阶段一的质量扫描。"""
    blocked_map = blocked_map or {}
    return [
        judge(
            c,
            registry,
            ctx,
            blocked_issues=blocked_map.get((c.point_id, c.timestamp)),
        )
        for c in calcs
    ]


def summarize(judgments: Sequence[RiskJudgment]) -> dict:
    """汇总：按等级、问题类别、数据来源分别统计。"""
    by_level: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_origin: dict[str, int] = {}
    abstain: dict[str, int] = {}
    worst = LEVEL_NORMAL
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
