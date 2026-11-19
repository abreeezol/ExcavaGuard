"""阶段三 · 收敛稳定 / 可停测的量化条件判定
==========================================

为什么单独一个模块
------------------
基坑判定关心的是"超没超限值"，隧道还多一个工程问题：**变形是否已经稳定、能否降低
监测频率或停测**。这不是阈值比对，而是"连续若干期速率低于某值"的时序条件判断，
现有 `risk_identifier` 里只有反方向的"NON_CONVERGENT（速率增长且不收敛）"标记。

判定口径
--------
- 阈值与连续期数**全部来自判据库**（metric 级 `stability_criterion`），代码不含数字。
- 规范给区间时按同一口径取严（`range_resolution=conservative`）。
- 期数不足 → `insufficient`，不得因为"最近几期都小"就推断稳定。
- 结论措辞只描述"是否满足规范给出的量化条件"，**不替工程师决定停测**。

依据示例（由判据库写入 evidence 字段，代码不假定）：
    规范给出的稳定判据原文 + 条文号 + 出处。
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

STATUS_SATISFIED = "satisfied"
STATUS_NOT_SATISFIED = "not_satisfied"
STATUS_INSUFFICIENT = "insufficient"
STATUS_NO_CRITERION = "no_criterion"

STATUS_DISPLAY = {
    STATUS_SATISFIED: "满足稳定判据（停测由工程师决定）",
    STATUS_NOT_SATISFIED: "未满足稳定判据（速率仍高于阈值）",
    STATUS_INSUFFICIENT: "有效速率期数不足，无法判断稳定性",
    STATUS_NO_CRITERION: "该测项未配置稳定性判据",
}

# 判定为"稳定"需要同时满足：速率 <= 阈值。允许一定数值容差，避免浮点比较抖动。
EPS = 1e-9


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not (isinstance(v, float) and v != v)


def _pick_threshold(spec: Any) -> float | None:
    """区间取严（下限），与阶段三的 `range_resolution=conservative` 同口径。"""
    if spec is None:
        return None
    if isinstance(spec, (int, float)):
        return float(spec)
    if isinstance(spec, dict):
        lo, hi = spec.get("min"), spec.get("max")
        if _num(lo) and _num(hi):
            return float(min(lo, hi))
        if _num(lo):
            return float(lo)
        if _num(hi):
            return float(hi)
    return None


def _recent_rates(history: Sequence, timestamp: str | None, n: int) -> list[float]:
    """取**含当前期**的最近 n 期速率（旧→新）。"""
    if not history:
        return []
    items = list(history)
    if items and isinstance(items[0], (tuple, list)) and len(items[0]) == 2:
        pairs = [(str(t), r) for t, r in items if _num(r)]
        if timestamp:
            pairs = [(t, r) for t, r in pairs if t <= str(timestamp)]
        vals = [r for _t, r in pairs]
    else:
        vals = [r for r in items if _num(r)]
    return vals[-n:]


def evaluate_stability(
    criterion: Any,
    history: Iterable,
    *,
    timestamp: str | None = None,
    current_rate: float | None = None,
) -> dict:
    """按判据库给出的 stability_criterion 判断是否满足稳定条件。

    参数
    ----
    criterion : metric 级的 `stability_criterion`
        ``{"rate_mm_per_day": 0.15 | {"min":0.1,"max":0.2},
           "consecutive_periods": 3,
           "evidence": {"standard": "...", "clause": "..."}}``
    history   : ``[(timestamp, rate), ...]``（旧→新）或纯速率列表
    timestamp : 当前记录时间，用于裁剪"截至本期"的历史
    current_rate : 当前期速率；提供且 history 未包含时会被追加

    返回可直接放进 `checks` 的字典，含口径与证据。
    """
    out: dict[str, Any] = {
        "status": STATUS_NO_CRITERION,
        "status_display": STATUS_DISPLAY[STATUS_NO_CRITERION],
        "threshold": None,
        "consecutive_periods": None,
        "observed_rates": [],
        "evidence": {},
    }
    if not isinstance(criterion, dict):
        return out

    threshold = _pick_threshold(criterion.get("rate_mm_per_day"))
    need = criterion.get("consecutive_periods")
    need = int(need) if isinstance(need, (int, float)) and need >= 1 else 0
    out["threshold"] = threshold
    out["consecutive_periods"] = need or None
    out["evidence"] = criterion.get("evidence") or {}
    if threshold is None or need <= 0:
        return out

    rates = _recent_rates(history, timestamp, need)
    if _num(current_rate) and (not rates or abs(rates[-1] - float(current_rate)) > EPS):
        rates = [*rates, float(current_rate)][-need:]
    out["observed_rates"] = [round(float(r), 4) for r in rates]

    if len(rates) < need:
        out["status"] = STATUS_INSUFFICIENT
        out["status_display"] = STATUS_DISPLAY[STATUS_INSUFFICIENT]
        return out

    ok = all(abs(float(r)) <= threshold + EPS for r in rates)
    out["status"] = STATUS_SATISFIED if ok else STATUS_NOT_SATISFIED
    out["status_display"] = STATUS_DISPLAY[out["status"]]
    out["max_abs_rate"] = round(max(abs(float(r)) for r in rates), 4)
    return out


def evaluate_rate_state(criterion: Any, rate: float | None) -> dict | None:
    """按规范给出的速率分档判断变形阶段（如 JTG/T 3660-2020 第 18.6.3 条第 2 款）。

    分档以「速率下限/上限」表达，全部来自判据库：
        ``rate_state_bands: [
             {"state": "急剧变形", "rate_min": 1.0, "action": "…"},
             {"state": "缓慢变形", "rate_min": 0.2, "rate_max": 1.0, "action": "…"},
             {"state": "基本稳定", "rate_max": 0.2, "action": "…"}]``
    """
    if not isinstance(criterion, dict) or not _num(rate):
        return None
    bands = [b for b in (criterion.get("rate_state_bands") or []) if isinstance(b, dict)]
    if not bands:
        return None
    r = abs(float(rate))
    for band in bands:
        lo, hi = band.get("rate_min"), band.get("rate_max")
        if _num(lo) and _num(hi):
            if lo <= r < hi:
                return {"state": band.get("state"), "action": band.get("action"),
                        "rate": round(r, 4), "band": [lo, hi], "evidence": band.get("evidence") or {}}
        elif _num(lo):
            if r >= lo:
                return {"state": band.get("state"), "action": band.get("action"),
                        "rate": round(r, 4), "band": [lo, None], "evidence": band.get("evidence") or {}}
        elif _num(hi):
            if r < hi:
                return {"state": band.get("state"), "action": band.get("action"),
                        "rate": round(r, 4), "band": [None, hi], "evidence": band.get("evidence") or {}}
    return None


def evaluate_management_level(criterion: Any, utilization: float | None) -> dict | None:
    """按判据库的 `management_levels` 给出规范原文口径的管理等级。

    与系统五级风险分级**并列展示、互不替代**：五级是本系统统一口径，
    管理等级是规范原文（如按 U/U0 分为三级）的表述，供工程师对照。
    """
    if not isinstance(criterion, list) or not criterion or not _num(utilization):
        return None
    rows = [r for r in criterion if isinstance(r, dict) and _num(r.get("ratio_upper"))]
    if not rows:
        return None
    rows.sort(key=lambda r: float(r["ratio_upper"]))
    u = float(utilization)
    for row in rows:
        if u < float(row["ratio_upper"]) - EPS:
            return {
                "code": row.get("level"),
                "label": row.get("label") or row.get("level"),
                "action": row.get("action"),
                "ratio_upper": row["ratio_upper"],
                "utilization": round(u, 4),
                "evidence": row.get("evidence") or {},
            }
    last = rows[-1]
    return {
        "code": last.get("level"),
        "label": last.get("label") or last.get("level"),
        "action": last.get("action"),
        "ratio_upper": last.get("ratio_upper"),
        "utilization": round(u, 4),
        "evidence": last.get("evidence") or {},
        "above_all_bands": True,
    }
