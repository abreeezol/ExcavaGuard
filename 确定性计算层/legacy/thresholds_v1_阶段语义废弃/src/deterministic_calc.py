"""
基坑智守 · 确定性计算核心函数

四项核心功能：
  1. 累计值计算      cumulative = current - baseline
  2. 本次变化量计算  single_change = current - previous
  3. 变化速率计算    rate = |single_change| / interval_days
  4. 阈值校核        与 ThresholdConfig 解析出的生效阈值比较，输出风险等级与生效来源

设计原则：
  - 纯确定性：相同输入 + 相同参数 => 相同输出，不做任何模型推断。
  - 可弃权：输入不足时返回明确弃权码，绝不猜测、绝不补造数值。
  - 可追溯：每条判定都携带计算公式、输入值、生效阈值、阈值来源阶段。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from threshold_loader import ResolvedThreshold

# ---------------------------------------------------------------------------
# 弃权码
# ---------------------------------------------------------------------------

ABSTAIN_CODES = {
    "MISSING_BASELINE": "缺少初始值/基准值，累计值不可计算",
    "MISSING_PREVIOUS": "缺少上次观测值，本次变化量不可计算",
    "INVALID_INTERVAL": "观测间隔 <= 0，变化速率不可计算",
    "IRREGULAR_INTERVAL": "观测间隔显著超出正常监测周期，速率标记为待复核",
    "MISSING_CURRENT": "缺少本次观测值",
    "NO_THRESHOLD": "该监测项无可用阈值",
    "NO_APPLICABLE_RULE": "该监测项在当前安全等级/支护形式下无适用规则",
    "MISSING_DESIGN_VALUE": "缺少设计值（f1/f2/fy），比值类阈值不可计算",
    "NON_NUMERIC": "观测值非数值",
}


@dataclass
class CalcResult:
    """单项确定性计算结果。"""

    metric_key: str
    point_id: str | None = None
    timestamp: str | None = None

    current_value: float | None = None
    baseline_value: float | None = None
    previous_value: float | None = None
    interval_days: float | None = None

    cumulative: float | None = None
    single_change: float | None = None
    rate: float | None = None

    formula: dict = field(default_factory=dict)
    abstain: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.abstain


@dataclass
class Judgment:
    """阈值校核判定结果。"""

    metric_key: str
    point_id: str | None
    timestamp: str | None

    checks: dict = field(default_factory=dict)
    exceeded: bool = False
    risk_level: str = "未知"
    issue_types: list[str] = field(default_factory=list)

    threshold_snapshot: dict = field(default_factory=dict)
    calc_snapshot: dict = field(default_factory=dict)
    trace: dict = field(default_factory=dict)
    abstain: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def threshold_source_stage(self) -> int | None:
        return self.threshold_snapshot.get("threshold_source_stage")

    @property
    def threshold_source_stage_display(self) -> str | None:
        return self.threshold_snapshot.get("threshold_source_stage_display")

    @property
    def threshold_source_label(self) -> str | None:
        return self.threshold_snapshot.get("threshold_source_label")


# ---------------------------------------------------------------------------
# 1~3. 三项核心计算
# ---------------------------------------------------------------------------


def compute_cumulative(current: float | None, baseline: float | None) -> tuple[float | None, str | None]:
    """累计变化量 = 本次观测值 − 初始值。"""
    if current is None or baseline is None:
        return None, "MISSING_BASELINE" if baseline is None else "MISSING_CURRENT"
    if not _num(current) or not _num(baseline):
        return None, "NON_NUMERIC"
    return current - baseline, None


def compute_single_change(current: float | None, previous: float | None) -> tuple[float | None, str | None]:
    """本次变化量 = 本次观测值 − 上次观测值。"""
    if current is None:
        return None, "MISSING_CURRENT"
    if previous is None:
        return None, "MISSING_PREVIOUS"
    if not _num(current) or not _num(previous):
        return None, "NON_NUMERIC"
    return current - previous, None


def compute_rate(
    single_change: float | None,
    interval_days: float | None,
    expected_interval_days: float | None = None,
) -> tuple[float | None, str | None, list[str]]:
    """变化速率 = |本次变化量| / 间隔天数。"""
    flags: list[str] = []
    if single_change is None:
        return None, "MISSING_PREVIOUS", flags
    if interval_days is None or interval_days <= 0:
        return None, "INVALID_INTERVAL", flags
    rate = abs(single_change) / interval_days
    if expected_interval_days and expected_interval_days > 0:
        if interval_days > expected_interval_days * 3:
            flags.append("IRREGULAR_INTERVAL")
    return rate, None, flags


def compute_metrics(
    metric_key: str,
    current: float | None,
    baseline: float | None = None,
    previous: float | None = None,
    interval_days: float | None = None,
    point_id: str | None = None,
    timestamp: str | None = None,
    expected_interval_days: float | None = None,
) -> CalcResult:
    """一次性完成三项核心计算。"""
    res = CalcResult(
        metric_key=metric_key,
        point_id=point_id,
        timestamp=timestamp,
        current_value=current,
        baseline_value=baseline,
        previous_value=previous,
        interval_days=interval_days,
    )

    cum, e1 = compute_cumulative(current, baseline)
    if e1:
        res.abstain.append(e1)
    res.cumulative = cum

    chg, e2 = compute_single_change(current, previous)
    if e2:
        res.abstain.append(e2)
    res.single_change = chg

    rate, e3, flags = compute_rate(chg, interval_days, expected_interval_days)
    if e3 and e3 not in res.abstain:
        res.abstain.append(e3)
    res.rate = rate
    res.flags.extend(flags)

    res.formula = {
        "cumulative": "cumulative = current - baseline",
        "single_change": "single_change = current - previous",
        "rate": "rate = |single_change| / interval_days",
    }
    return res


# ---------------------------------------------------------------------------
# 4. 阈值校核
# ---------------------------------------------------------------------------


def _utilization(value: float | None, limit: float | None) -> float | None:
    """限值利用率 = |value| / limit。"""
    if value is None or limit in (None, 0):
        return None
    return abs(value) / abs(limit)


def classify_risk(
    utilization: float | None,
    consecutive_over_70: bool = False,
) -> str:
    """按利用率划分风险等级。

    正常  < 50%
    关注  50% ~ 70%
    预警  70% ~ 100%，或连续3次超过70%
    报警  >= 100%
    """
    if utilization is None:
        return "未知"
    if utilization >= 1.0:
        return "报警"
    if utilization >= 0.7 or consecutive_over_70:
        return "预警"
    if utilization >= 0.5:
        return "关注"
    return "正常"


def judge(
    calc: CalcResult,
    threshold: ResolvedThreshold,
    design_value: float | None = None,
    consecutive_over_70: bool = False,
    issue_types: list[str] | None = None,
) -> Judgment:
    """对一项计算结果做阈值校核，输出风险等级与生效阈值来源。"""
    j = Judgment(
        metric_key=calc.metric_key,
        point_id=calc.point_id,
        timestamp=calc.timestamp,
        abstain=list(calc.abstain),
        flags=list(calc.flags),
    )
    j.threshold_snapshot = threshold.to_dict()
    j.calc_snapshot = {
        "current_value": calc.current_value,
        "baseline_value": calc.baseline_value,
        "previous_value": calc.previous_value,
        "interval_days": calc.interval_days,
        "cumulative": calc.cumulative,
        "single_change": calc.single_change,
        "rate": calc.rate,
        "formula": calc.formula,
    }

    if "NO_APPLICABLE_RULE" in threshold.flags:
        j.abstain.append("NO_APPLICABLE_RULE")
        j.risk_level = "未知"
        return j

    mode = threshold.limit_mode
    utils: list[float] = []

    # 累计值判据
    if mode == "displacement" and threshold.cumulative_limit_mm:
        u = _utilization(calc.cumulative, threshold.cumulative_limit_mm)
        j.checks["cumulative"] = {
            "value": calc.cumulative,
            "limit": threshold.cumulative_limit_mm,
            "basis": threshold.cumulative_basis,
            "utilization": u,
            "exceeded": bool(u is not None and u >= 1.0),
        }
        if u is not None:
            utils.append(u)

    # 变化速率判据
    if mode == "displacement" and threshold.rate_limit_mm_per_day:
        u = _utilization(calc.rate, threshold.rate_limit_mm_per_day)
        j.checks["rate"] = {
            "value": calc.rate,
            "limit": threshold.rate_limit_mm_per_day,
            "unit": "mm/d",
            "utilization": u,
            "exceeded": bool(u is not None and u >= 1.0),
        }
        if u is not None:
            utils.append(u)

    # 上次变化量（本次变化量）判据：无独立限值时按速率限值 × 间隔折算参考
    if mode == "displacement" and threshold.rate_limit_mm_per_day and calc.interval_days:
        implied = threshold.rate_limit_mm_per_day * calc.interval_days
        u = _utilization(calc.single_change, implied)
        j.checks["single_change_implied"] = {
            "value": calc.single_change,
            "implied_limit": implied,
            "basis": "rate_limit * interval_days（由速率限值折算，非规范直接规定）",
            "utilization": u,
            "exceeded": bool(u is not None and u >= 1.0),
        }

    # 比值类判据（支撑轴力 / 围护墙内力 / 土压力 / 孔隙水压）
    if mode == "max_ratio" and threshold.max_ratio_of_design is not None:
        if design_value in (None, 0):
            j.abstain.append("MISSING_DESIGN_VALUE")
        else:
            ratio = (calc.current_value or 0.0) / design_value
            u = _utilization(ratio, threshold.max_ratio_of_design)
            j.checks["max_ratio_of_design"] = {
                "ratio": ratio,
                "limit": threshold.max_ratio_of_design,
                "utilization": u,
                "exceeded": bool(u is not None and u >= 1.0),
            }
            if u is not None:
                utils.append(u)

    if mode == "min_ratio" and threshold.min_ratio_of_design is not None:
        if design_value in (None, 0):
            j.abstain.append("MISSING_DESIGN_VALUE")
        else:
            ratio = (calc.current_value or 0.0) / design_value
            # 低于下限即判超限（锚杆松弛）
            exceeded = ratio < threshold.min_ratio_of_design
            u = ratio / threshold.min_ratio_of_design if threshold.min_ratio_of_design else None
            j.checks["min_ratio_of_design"] = {
                "ratio": ratio,
                "limit": threshold.min_ratio_of_design,
                "utilization": u,
                "exceeded": bool(exceeded),
                "note": "低于下限判为松弛/预应力损失",
            }
            if exceeded:
                utils.append(1.0)
            elif u is not None:
                utils.append(1.0 - (1.0 - u))  # 越接近下限，利用率越高

    if mode == "inclination":
        u = _utilization(calc.cumulative, threshold.cumulative_inclination)
        j.checks["inclination"] = {
            "value": calc.cumulative,
            "limit": threshold.cumulative_inclination,
            "utilization": u,
            "exceeded": bool(u is not None and u >= 1.0),
        }
        if u is not None:
            utils.append(u)

    if mode == "crack":
        u = _utilization(calc.cumulative, threshold.cumulative_limit_mm)
        j.checks["crack_width"] = {
            "value": calc.cumulative,
            "limit": threshold.cumulative_limit_mm,
            "utilization": u,
            "exceeded": bool(u is not None and u >= 1.0),
            "requires_continuous_development": threshold.requires_continuous_development,
        }
        if u is not None:
            utils.append(u)

    if mode == "none" or not utils:
        if "MISSING_DESIGN_VALUE" not in j.abstain and mode != "none":
            j.abstain.append("NO_THRESHOLD")

    j.exceeded = any(bool(c.get("exceeded")) for c in j.checks.values())
    j.risk_level = classify_risk(max(utils) if utils else None, consecutive_over_70)

    if j.exceeded:
        j.risk_level = "报警"
    if "IRREGULAR_INTERVAL" in j.flags and j.risk_level == "正常":
        j.risk_level = "关注"

    j.issue_types = list(issue_types or [])
    j.trace = {
        "metric_key": calc.metric_key,
        "rule_id": threshold.rule_id,
        "threshold_source_stage": threshold.stage,
        "threshold_source_stage_display": threshold.stage_display,
        "threshold_source_label": threshold.source_label,
        "threshold_source_id": threshold.source.get("source_id"),
        "overridden_fields": threshold.overrides,
        "selection_used": threshold.selection_used,
        "checks": j.checks,
        "abstain": j.abstain,
        "abstain_reasons": [ABSTAIN_CODES.get(a, a) for a in j.abstain],
    }
    return j


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
