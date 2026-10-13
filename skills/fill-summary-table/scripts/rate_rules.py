# -*- coding: utf-8 -*-
"""
rate_rules.py —— 速率口径判据（GB 50497-2019 第 8.0.3 条 / 第 8.0.9-1 条）
=============================================================================

同事在开发同类 skill 时踩到的**最易踩的坑**：

1. **只取末次读数** → 掩盖日内变化；
2. **用日平均速率** → 掩盖突变。

本模块把规范里这两条**量化判据**补齐，供各输出形态共用：

| 判据 | 依据 | 触发条件 | 等级 |
|---|---|---|---|
| 连续超 70% | GB 50497-2019 **第 8.0.3 条** / 表 8.0.4 注 | 变化速率**连续 N 次**（默认 3）≥ 速率限值 × 70% | 至少 **橙色预警** |
| 突然明显增大 | GB 50497-2019 **第 8.0.9-1 条**（强制性条文） | 本次变化量 ≥ **k 倍**（默认 3）前若干期变化量**中位数** | **红色预警**（危险报警） |

**重要边界**：

- 「连续 3 次超 70%」中的「次」指**监测期次**，不是「天」。期次口径由调用方给出
  （`cd` = 日；`af` = 日或文件顺序；`verdict` = `--period`）。
- **亚日级序列（采样间隔 < 1 天）不适用**：5 分钟级数据由测量噪声主导，
  中位数倍数判据会产生大量假突变。此时本模块**主动弃权**（返回空结果）并说明原因。
- 「突然明显增大」规范**未定量**，倍数阈值属**工程经验判据**，默认 3.0，
  须由项目专项监测方案确认；可用 `--sudden-factor 0` 关闭。
"""

from __future__ import annotations

import statistics

CONSEC_RATIO = 0.7
CONSEC_COUNT = 3
SUDDEN_FACTOR = 3.0
SUDDEN_MIN_PREV = 3
SUBDaily_MINUTES = 1440

LEVEL_OK = "正常"
LEVEL_YELLOW = "黄色预警"
LEVEL_ORANGE = "橙色预警"
LEVEL_RED = "红色预警"
_ORDER = [LEVEL_OK, LEVEL_YELLOW, LEVEL_ORANGE, LEVEL_RED]

# 各模块的等级用词并不完全一致（判定汇总表用「黄色/橙色/红色」，附录表式用「黄色预警」…），
# 比较前必须先归一到同一把尺子 —— 否则 bump 会**静默失效**（同事踩过的口径错位坑）。
_LEVEL_RANK = {
    "": -1, "未知": -1, "未判定": -1, "未判定(待复核)": -1, "未知(待复核)": -1,
    "正常": 0, "LEVEL_OK": 0,
    "黄色": 1, "黄色预警": 1, "黄色(需关注)": 1, "需关注": 1,
    "橙色": 2, "橙色预警": 2, "橙色(预警)": 2, "预警": 2,
    "红色": 3, "红色预警": 3, "红色(报警)": 3, "报警": 3, "危险报警": 3,
}


def level_rank(level) -> int:
    """把各模块的等级用词归一到 0~3 的序（未知/弃权 = -1）。"""
    return _LEVEL_RANK.get(str(level or "").strip(), -1)


def bump_level(cur: str, target: str) -> str:
    """取两者中较高的等级；`cur` 为空表示尚未定级。**跨模块用词不一致也能正确比较。**"""
    if not cur:
        return target
    return target if level_rank(target) > level_rank(cur) else cur

CLAUSE_CONSEC = "GB 50497-2019 第 8.0.3 条"
CLAUSE_SUDDEN = "GB 50497-2019 第 8.0.9-1 条（强制性条文）"


def is_sub_daily(interval_minutes) -> bool:
    """采样/期次间隔是否短于 1 天（亚日级 → 速率口径判据不适用）。"""
    try:
        return interval_minutes is not None and float(interval_minutes) < SUBDaily_MINUTES
    except (TypeError, ValueError):
        return False


def consecutive_rate_alarm(rates, warn_rate, ratio: float = CONSEC_RATIO,
                           count: int = CONSEC_COUNT) -> tuple[bool, str]:
    """GB 50497-2019 第 8.0.3 条：变化速率连续 count 次超过规定值的 ratio → 应预警。"""
    try:
        if warn_rate is None or float(warn_rate) <= 0:
            return False, ""
        wr = float(warn_rate)
    except (TypeError, ValueError):
        return False, ""
    seq = list(rates or [])
    if len(seq) < count:
        return False, ""
    tail = seq[-count:]
    if any(r is None for r in tail):   # 期次不连续 → 不判「连续」
        return False, ""
    if all(abs(float(r)) >= ratio * wr for r in tail):
        return True, (f"变化速率连续 {count} 次达到速率限值的 {ratio:.0%} 以上"
                      f"（限值 {wr:g}，阈值 {ratio * wr:g}，本期 {abs(float(tail[-1])):g}）")
    return False, ""


def sudden_increase_alarm(changes, factor: float = SUDDEN_FACTOR,
                          min_prev: int = SUDDEN_MIN_PREV) -> tuple[bool, str]:
    """GB 50497-2019 第 8.0.9-1 条：位移值突然明显增大 → 必须立即危险报警。

    「明显增大」规范未定量，此处按「本次变化量 ≥ factor × 前若干期变化量中位数」判定；
    前若干期几乎无变化（中位数 ≤ 0）时，本期一旦出现非零变化即视为突变。
    """
    try:
        factor = float(factor)
    except (TypeError, ValueError):
        return False, ""
    if factor <= 0:
        return False, ""
    seq = [c for c in (changes or [])]
    if len(seq) < min_prev + 1:
        return False, ""
    window = seq[-(min_prev + 1):]
    if any(c is None for c in window):   # 期次不连续 → 不作突变判定
        return False, ""
    nums = [abs(float(c)) for c in window]
    cur = nums[-1]
    prev = nums[:-1]
    if cur <= 0:
        return False, ""
    med = statistics.median(prev)
    if med <= 0:
        return True, f"本次变化量 {cur:g}，而前 {min_prev} 期几乎无变化（突变）"
    if cur >= factor * med:
        return True, (f"本次变化量 {cur:g} ≥ {factor:g} × 前 {min_prev} 期变化量中位数 "
                      f"{med:g}（突变）")
    return False, ""


def evaluate_series(series_changes, series_rates, warn_rate, *,
                    enable: bool = True, sudden_factor: float = SUDDEN_FACTOR,
                    interval_minutes=None, sudden_ack: bool = True) -> dict:
    """按期次序列评估两条速率口径判据。

    返回 `{"level", "reasons", "clauses", "skipped", "sudden_blocked"}`：

    - `level` 为空串表示未触发；
    - `skipped` 非空表示**主动弃权**及原因；
    - `sudden_blocked` 非空表示「突然明显增大」判据**本会触发但因未确认而停用**，
      调用方应据此在产物中注明，但**不得据此升级等级**。

    **「突然明显增大」需一次性确认（`sudden_ack`）才生效**：该条规范未定量，
    阈值属工程经验判据，用于真实工程前必须由项目专项监测方案确认。
    """
    out = {"level": "", "reasons": [], "clauses": [], "skipped": "", "sudden_blocked": ""}
    if not enable:
        out["skipped"] = "用户关闭速率口径判据（--rate-rules off）"
        return out
    if is_sub_daily(interval_minutes):
        out["skipped"] = (f"期次间隔约 {float(interval_minutes):g} 分钟（亚日级），"
                          f"序列由测量噪声主导，速率口径判据不适用")
        return out

    hit, why = consecutive_rate_alarm(series_rates, warn_rate)
    if hit:
        out["level"] = bump_level(out["level"], LEVEL_ORANGE)
        out["reasons"].append(why)
        out["clauses"].append(CLAUSE_CONSEC)

    hit, why = sudden_increase_alarm(series_changes, sudden_factor)
    if hit:
        if sudden_ack:
            out["level"] = bump_level(out["level"], LEVEL_RED)
            out["reasons"].append(why)
            out["clauses"].append(CLAUSE_SUDDEN)
        else:
            out["sudden_blocked"] = why
    return out
