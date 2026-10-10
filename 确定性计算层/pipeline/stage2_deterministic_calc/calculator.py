"""
阶段二 · 确定性计算

对阶段一准备好的风险识别参数执行纯确定性计算：
  1. 累计值      cumulative    = current − baseline
  2. 本次变化量  single_change = current − previous
  3. 变化速率    rate          = |single_change| / interval_days
  4. 趋势斜率    slope         = 最小二乘拟合（mm/d），用于判断加速/匀速/收敛

原则
----
- 相同输入 + 相同参数 ⇒ 相同输出，不做任何模型推断。
- 输入不足时**弃权**并给出明确弃权码，绝不猜测、绝不插补、绝不静默跳过。
- 每个结果都携带计算公式与输入值，供阶段三与人工复核追溯。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

ABSTAIN_REASONS = {
    "MISSING_CURRENT": "缺少本次观测值",
    "MISSING_BASELINE": "缺少初始值/基准值，累计值不可计算",
    "MISSING_PREVIOUS": "缺少上次观测值，本次变化量不可计算",
    "INVALID_INTERVAL": "观测间隔 <= 0，变化速率不可计算",
    "NON_NUMERIC": "观测值非数值",
    "NO_DATA": "无可用记录",
}


@dataclass
class CalcResult:
    """单项确定性计算结果。"""

    metric_key: str
    point_id: str | None = None
    timestamp: str | None = None
    data_origin: str = "real"

    current: float | None = None
    baseline: float | None = None
    previous: float | None = None
    interval_days: float | None = None

    cumulative: float | None = None
    single_change: float | None = None
    rate: float | None = None
    slope: float | None = None

    formula: dict = field(default_factory=dict)
    abstain: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.abstain

    def to_dict(self) -> dict:
        return {
            "metric_key": self.metric_key,
            "point_id": self.point_id,
            "timestamp": self.timestamp,
            "data_origin": self.data_origin,
            "inputs": {
                "current": self.current,
                "baseline": self.baseline,
                "previous": self.previous,
                "interval_days": self.interval_days,
            },
            "outputs": {
                "cumulative": self.cumulative,
                "single_change": self.single_change,
                "rate": self.rate,
                "slope": self.slope,
            },
            "formula": self.formula,
            "abstain": self.abstain,
            "abstain_reasons": [ABSTAIN_REASONS.get(a, a) for a in self.abstain],
            "flags": self.flags,
        }


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def cumulative_value(current: float | None, baseline: float | None) -> tuple[float | None, str | None]:
    """累计变化量 = 本次观测值 − 初始值。"""
    if not _num(current):
        return None, "MISSING_CURRENT"
    if not _num(baseline):
        return None, "MISSING_BASELINE"
    return current - baseline, None


def single_change_value(current: float | None, previous: float | None) -> tuple[float | None, str | None]:
    """本次变化量 = 本次观测值 − 上次观测值。"""
    if not _num(current):
        return None, "MISSING_CURRENT"
    if not _num(previous):
        return None, "MISSING_PREVIOUS"
    return current - previous, None


def rate_value(
    single_change: float | None,
    interval_days: float | None,
) -> tuple[float | None, str | None]:
    """变化速率 = |本次变化量| / 间隔天数。"""
    if not _num(single_change):
        return None, "MISSING_PREVIOUS"
    if not _num(interval_days) or interval_days <= 0:
        return None, "INVALID_INTERVAL"
    return abs(single_change) / interval_days, None


def trend_slope(pairs: Sequence[tuple[float, float]]) -> float | None:
    """最小二乘趋势斜率。pairs = [(day_index, value), ...]；返回 mm/d。"""
    n = len(pairs)
    if n < 3:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def compute(
    metric_key: str,
    current: float | None,
    baseline: float | None = None,
    previous: float | None = None,
    interval_days: float | None = None,
    point_id: str | None = None,
    timestamp: str | None = None,
    data_origin: str = "real",
    history: Sequence[tuple[float, float]] | None = None,
    expected_interval_days: float | None = None,
    input_flags: Sequence[str] | None = None,
) -> CalcResult:
    """一次性完成四项核心计算。

    `input_flags` 用于透传阶段一的标记（如 BASELINE_DERIVED / MISSING_VALUE），
    使"这个初始值是系统派生的、不是用户给的"能一路传到判定结果与日报。
    """
    r = CalcResult(
        metric_key=metric_key,
        point_id=point_id,
        timestamp=timestamp,
        data_origin=data_origin,
        current=current,
        baseline=baseline,
        previous=previous,
        interval_days=interval_days,
    )
    for f in input_flags or ():
        if f not in r.flags:
            r.flags.append(f)

    cum, e1 = cumulative_value(current, baseline)
    if e1:
        r.abstain.append(e1)
    r.cumulative = cum

    chg, e2 = single_change_value(current, previous)
    if e2 and e2 not in r.abstain:
        r.abstain.append(e2)
    r.single_change = chg

    rate, e3 = rate_value(chg, interval_days)
    if e3 and e3 not in r.abstain:
        r.abstain.append(e3)
    r.rate = rate

    r.slope = trend_slope(history) if history else None

    if expected_interval_days and _num(interval_days) and interval_days > expected_interval_days * 3:
        r.flags.append("IRREGULAR_INTERVAL")

    r.formula = {
        "cumulative": "cumulative = current - baseline",
        "single_change": "single_change = current - previous",
        "rate": "rate = |single_change| / interval_days",
        "slope": "slope = Σ((x-x̄)(y-ȳ)) / Σ((x-x̄)²)  # 最小二乘，单位 mm/d",
    }
    return r


def compute_batch(
    records: Sequence[Any],
    expected_interval_days: float | None = None,
    histories: dict[str, Sequence[tuple[float, float]]] | None = None,
) -> list[CalcResult]:
    """对归一化记录批量计算。记录需具备 point_id/timestamp/metric_key/value/baseline_value/previous_value/interval_days。

    histories 形如 {point_id: [(day_index, value), ...]}，用于计算趋势斜率；不传则不计算斜率。
    """
    out: list[CalcResult] = []
    if not records:
        return out
    for rec in records:
        out.append(
            compute(
                metric_key=getattr(rec, "metric_key", ""),
                current=getattr(rec, "value", None),
                baseline=getattr(rec, "baseline_value", None),
                previous=getattr(rec, "previous_value", None),
                interval_days=getattr(rec, "interval_days", None),
                point_id=getattr(rec, "point_id", None),
                timestamp=getattr(rec, "timestamp", None),
                data_origin=getattr(rec, "data_origin", "real"),
                history=(histories or {}).get(getattr(rec, "point_id", None)),
                expected_interval_days=expected_interval_days,
            )
        )
    return out
