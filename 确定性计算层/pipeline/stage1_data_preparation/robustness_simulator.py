"""
阶段一 · 数据准备 —— 健壮性验证用模拟噪声注入

【用途边界 · 务必阅读】
------------------------------------------------------------------
本模块的**唯一目的**是检验 Agent 是否具备处理噪音与缺失的能力：
异常值、空值、格式不一致、重复记录、传感器漂移、间隔异常等。
它通过向**真实数据副本**注入受控噪声，生成"带病"数据集，
用于验证流程是否按预期识别、标记、弃权，而不是崩溃或静默出错。

【不使用方式】
------------------------------------------------------------------
- 模拟结果**不替代**真实数据；
- 模拟结果**不用于**对外输出工程结论；
- 模拟结果**不与**真实数据合并统计。

【强制标识】
------------------------------------------------------------------
- 输出文件名必须含 `SIMULATED`
- 每条记录强制携带 `data_origin = "simulated"`
- 保留 `source_dataset` 字段，标明噪声由哪份真实数据派生
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import Any


@dataclass
class NoiseProfile:
    """噪声注入配置（各项比例均为 0~1）。"""

    missing_rate: float = 0.05        # 观测值置空
    missing_baseline_rate: float = 0.03  # 初始值置空
    outlier_rate: float = 0.03        # 异常值（放大为均值+nσ 量级）
    non_numeric_rate: float = 0.02    # 数值写坏（格式不一致）
    bad_timestamp_rate: float = 0.02  # 日期写坏
    bad_unit_rate: float = 0.02       # 单位写坏
    duplicate_rate: float = 0.02      # 重复记录
    flatline_rate: float = 0.03       # 连续多期不变
    irregular_interval_rate: float = 0.03  # 间隔拉长
    outlier_factor: float = 8.0       # 异常值放大倍数（相对标准差）
    seed: int = 20261009

    def to_dict(self) -> dict:
        return dict(self.__dict__)


PROFILE_PRESETS: dict[str, dict[str, float]] = {
    "clean": {},
    "light": {"missing_rate": 0.03, "outlier_rate": 0.02, "non_numeric_rate": 0.01},
    "medium": {
        "missing_rate": 0.06,
        "missing_baseline_rate": 0.04,
        "outlier_rate": 0.04,
        "non_numeric_rate": 0.02,
        "bad_timestamp_rate": 0.02,
        "bad_unit_rate": 0.02,
        "duplicate_rate": 0.02,
        "flatline_rate": 0.03,
        "irregular_interval_rate": 0.03,
    },
    "heavy": {
        "missing_rate": 0.15,
        "missing_baseline_rate": 0.10,
        "outlier_rate": 0.10,
        "non_numeric_rate": 0.06,
        "bad_timestamp_rate": 0.06,
        "bad_unit_rate": 0.05,
        "duplicate_rate": 0.05,
        "flatline_rate": 0.08,
        "irregular_interval_rate": 0.08,
    },
    "missing_only": {"missing_rate": 0.20, "missing_baseline_rate": 0.10},
    "outlier_only": {"outlier_rate": 0.12},
    "format_only": {"non_numeric_rate": 0.08, "bad_timestamp_rate": 0.08, "bad_unit_rate": 0.06},
}


def profile_from_preset(name: str, **overrides: Any) -> NoiseProfile:
    if name not in PROFILE_PRESETS:
        raise ValueError(f"未知预设: {name}，可选: {sorted(PROFILE_PRESETS)}")
    p = NoiseProfile(**PROFILE_PRESETS[name])
    for k, v in overrides.items():
        if not hasattr(p, k):
            raise ValueError(f"未知配置项: {k}")
        setattr(p, k, v)
    return p


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return (sum((v - m) ** 2 for v in values) / (len(values) - 1)) ** 0.5


def inject_noise(
    records: list[dict],
    profile: NoiseProfile | None = None,
    source_dataset: str = "unknown",
) -> tuple[list[dict], dict]:
    """基于真实数据副本注入受控噪声。

    返回 (带噪记录, 注入统计)。所有记录被强制标记为 simulated。
    """
    profile = profile or profile_from_preset("medium")
    rng = random.Random(profile.seed)

    src = copy.deepcopy(records)
    vals = [r.get("value") for r in src if isinstance(r.get("value"), (int, float))]
    sd = _std(vals) or (abs(vals[0]) * 0.1 if vals else 1.0)
    mean = sum(vals) / len(vals) if vals else 0.0

    stats: dict[str, int] = {}
    out: list[dict] = []

    for r in src:
        rec = dict(r)
        rec["data_origin"] = "simulated"          # 强制标识
        rec["source_dataset"] = source_dataset    # 溯源：由哪份真实数据派生
        out.append(rec)

        if rng.random() < profile.missing_rate:
            rec["value"] = None
            stats["missing_value"] = stats.get("missing_value", 0) + 1

        if rng.random() < profile.missing_baseline_rate:
            rec["baseline_value"] = None
            stats["missing_baseline"] = stats.get("missing_baseline", 0) + 1

        if rng.random() < profile.outlier_rate and isinstance(rec.get("value"), (int, float)):
            sign = 1 if rng.random() < 0.5 else -1
            rec["value"] = mean + sign * profile.outlier_factor * sd
            rec["value"] = round(rec["value"], 4)
            stats["outlier"] = stats.get("outlier", 0) + 1

        if rng.random() < profile.non_numeric_rate:
            rec["value"] = rng.choice(["N/A", "—", "null", "待补", "1,2"])
            stats["non_numeric"] = stats.get("non_numeric", 0) + 1

        if rng.random() < profile.bad_timestamp_rate:
            rec["timestamp"] = rng.choice(["2026/13/45", "昨天", "", "2026-02-30 99:99"])
            stats["bad_timestamp"] = stats.get("bad_timestamp", 0) + 1

        if rng.random() < profile.bad_unit_rate:
            rec["unit"] = rng.choice(["MM", "厘米", "?", "mm/s"])
            stats["bad_unit"] = stats.get("bad_unit", 0) + 1

        if rng.random() < profile.irregular_interval_rate and rec.get("interval_days") is not None:
            rec["interval_days"] = round(float(rec["interval_days"]) * rng.choice([5, 8, 12]), 2)
            stats["irregular_interval"] = stats.get("irregular_interval", 0) + 1

        if rng.random() < profile.duplicate_rate:
            dup = dict(rec)
            out.append(dup)
            stats["duplicate"] = stats.get("duplicate", 0) + 1

    # 传感器漂移：把连续若干期值强制拉平
    if profile.flatline_rate > 0 and out:
        k = max(1, int(len(out) * profile.flatline_rate / 4))
        for i in range(0, max(0, len(out) - 4), max(4, len(out) // max(1, k) or 4)):
            if rng.random() < 0.5 and isinstance(out[i].get("value"), (int, float)):
                v = out[i]["value"]
                for j in range(i + 1, min(i + 4, len(out))):
                    out[j]["value"] = v
                stats["flatline"] = stats.get("flatline", 0) + 1

    stats["input_records"] = len(src)
    stats["output_records"] = len(out)
    stats["profile"] = profile.to_dict()
    stats["source_dataset"] = source_dataset
    return out, stats


def robustness_report(
    detected: dict[str, int],
    injected: dict[str, int],
) -> dict:
    """对比「注入量」与「识别量」，评价流程健壮性。

    detected 来自 quality_scan 的 by_code；injected 来自 inject_noise 的 stats。
    """
    mapping = {
        "missing_value": "MISSING_VALUE",
        "missing_baseline": "MISSING_BASELINE",
        "outlier": "OUTLIER",
        "non_numeric": "NON_NUMERIC_VALUE",
        "bad_timestamp": "UNPARSED_TIMESTAMP",
        "bad_unit": "UNSUPPORTED_UNIT",
        "duplicate": "DUPLICATE_RECORD",
        "flatline": "FLATLINE",
        "irregular_interval": "IRREGULAR_INTERVAL",
    }
    rows = []
    for inj_key, code in mapping.items():
        n_inj = injected.get(inj_key, 0)
        n_det = detected.get(code, 0)
        rows.append(
            {
                "injected_as": inj_key,
                "detected_as": code,
                "injected": n_inj,
                "detected": n_det,
                # 识别数可能因一条噪声触发多条问题码而高于注入数，故不做严格相等断言
                "recall": (min(n_det, n_inj) / n_inj) if n_inj else None,
                "status": "未注入" if n_inj == 0 else ("已识别" if n_det >= n_inj else "识别不足"),
            }
        )
    return {"rows": rows, "note": "本指标用于验证流程健壮性，不代表工程质量判定能力。"}
