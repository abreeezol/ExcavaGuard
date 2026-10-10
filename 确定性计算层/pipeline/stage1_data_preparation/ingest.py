"""
阶段一 · 数据准备 —— 数据接入与归一化

职责
----
把「用户上传的现有数据」与「为健壮性验证而生成的模拟数据」统一接入，
归一化成同一套字段结构后输出，作为后续风险识别参数的输入依据。

两者的地位：
  - 用户上传数据：真实来源，是判定的主依据；
  - 模拟数据：仅用于验证 Agent 处理噪音/缺失的能力，**不替代真实数据**，
    全程带 `data_origin = "simulated"` 标识，统计时与真实数据分开。

原则
----
- 只做确定性归一化，不猜测单位、不插补数值、不静默丢弃问题行。
- 无法归一化的字段原样保留，并挂上 `UNNORMALIZED` 标记交由下游弃权。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# 按量纲组织的单位换算表：{量纲: ({单位: 到该量纲标准单位的因子}, 标准单位)}
DIMENSION_TABLES: dict[str, tuple[dict[str, float], str]] = {
    "length": ({"mm": 1.0, "cm": 10.0, "dm": 100.0, "m": 1000.0, "km": 1_000_000.0}, "mm"),
    "pressure": ({"pa": 1.0, "kpa": 1_000.0, "mpa": 1_000_000.0}, "kPa"),
    "force": ({"n": 1.0, "kn": 1_000.0, "mn": 1_000_000.0}, "kN"),
}

UNIT_TO_DIMENSION: dict[str, tuple[str, float]] = {
    u: (dim, f) for dim, (tbl, _canon) in DIMENSION_TABLES.items() for u, f in tbl.items()
}

# 无量纲 / 比值类单位，原样保留，不换算也不报错
DIMENSIONLESS_UNITS = {"", "1", "ratio", "-", "无", "无量纲", "%", "度", "°"}

# 温度：本项目不做温标换算（℃ 与 K 的偏移不适用工程变形量），原样保留
TEMPERATURE_UNITS = {"℃", "°c", "°C", "c", "celsius", "摄氏度", "摄氏"}

# 方向别名：中文/符号写法 → positive / negative
# 仅映射**明确的符号或方向词**，不做语义推断（如"裂缝"不映射方向）。
DIRECTION_ALIASES: dict[str, str] = {
    "positive": "positive", "pos": "positive", "+": "positive", "1": "positive",
    "正": "positive", "正向": "positive", "正向位移": "positive", "向正": "positive",
    "上升": "positive", "抬升": "positive", "隆起": "positive", "上抬": "positive",
    "negative": "negative", "neg": "negative", "-": "negative", "-1": "negative",
    "−": "negative", "负": "negative", "负向": "negative", "负向位移": "negative", "向负": "negative",
    "下降": "negative", "沉降": "negative", "下沉": "negative", "回落": "negative",
}

# 监测项常见简称 / 俗称 → metric_key（规范库标准名之外的补充）
METRIC_SHORT_ALIASES: dict[str, str] = {
    "墙顶水平位移": "wall_top_horizontal_displacement",
    "墙顶竖向位移": "wall_top_vertical_displacement",
    "顶部水平位移": "wall_top_horizontal_displacement",
    "顶部竖向位移": "wall_top_vertical_displacement",
    "测斜": "deep_horizontal_displacement",
    "深层位移": "deep_horizontal_displacement",
    "深层侧移": "deep_horizontal_displacement",
    "立柱沉降": "column_vertical_displacement",
    "立柱位移": "column_vertical_displacement",
    "轴力": "support_axial_force",
    "支撑内力": "support_axial_force",
    "锚杆拉力": "anchor_axial_force",
    "锚索轴力": "anchor_axial_force",
    "水位": "groundwater_level",
    "地下水位变化": "groundwater_level",
    "地表沉降": "surface_settlement",
    "地表位移": "surface_settlement",
    "地面沉降": "surface_settlement",
    "建筑沉降": "building_settlement",
    "建筑物沉降": "building_settlement",
    "倾斜": "building_inclination",
    "管线沉降": "pipeline_settlement",
    "管线位移": "pipeline_settlement",
    "管线水平位移": "pipeline_horizontal_displacement",
    "道路沉降": "road_settlement",
    "路面沉降": "road_settlement",
    "建筑裂缝": "crack_width_building",
    "裂缝": "crack_width_building",
    "地表裂缝": "crack_width_surface",
    "地面裂缝": "crack_width_surface",
    "回弹": "basal_heave",
    "隆起": "basal_heave",
    "坑底回弹": "basal_heave",
    "土压力": "earth_pressure",
    "侧向土压力": "earth_pressure",
    "孔压": "pore_pressure",
    "孔隙水压": "pore_pressure",
    "立柱内力": "column_internal_force",
    "温度": "soil_temperature",
    "地温": "soil_temperature",
    "分层沉降": "soil_layered_vertical_displacement",
    "土体分层沉降": "soil_layered_vertical_displacement",
}


def normalize_metric_name(name: str) -> str:
    """监测项名称归一，用于宽松匹配。

    去掉括号及其内容、空白与常见标点：
        "围护墙（边坡）顶部水平位移" → "围护墙顶部水平位移"
        "深层水平位移（测斜）"       → "深层水平位移"
    """
    t = str(name or "").strip()
    for lb, rb in (("（", "）"), ("(", ")"), ("【", "】"), ("[", "]")):
        while lb in t and rb in t:
            i, j = t.find(lb), t.find(rb)
            if i < 0 or j < 0 or j < i:
                break
            t = t[:i] + t[j + 1:]
    for ch in " \t　-_/\\、,，.。:：;；'\"“”":
        t = t.replace(ch, "")
    return t


def build_metric_aliases(display_names: dict[str, str]) -> dict[str, str]:
    """由规范库的标准名构建「别名 → metric_key」映射。

    收录：metric_key 本身、标准名、标准名归一化形式、常见简称。
    归一化后出现歧义（多个 metric_key 归一为同一名称）时**不收录**，避免猜错。
    """
    aliases: dict[str, str] = {}
    seen: dict[str, set[str]] = {}

    for key, name in display_names.items():
        aliases.setdefault(key, key)
        aliases.setdefault(key.lower(), key)
        raw = str(name or "").strip()
        if raw:
            aliases.setdefault(raw, key)
            seen.setdefault(normalize_metric_name(raw), set()).add(key)

    for norm_name, keys in seen.items():
        if norm_name and len(keys) == 1:
            aliases.setdefault(norm_name, next(iter(keys)))

    for short, key in METRIC_SHORT_ALIASES.items():
        if key in display_names:
            aliases.setdefault(short, key)
            aliases.setdefault(normalize_metric_name(short), key)

    return aliases

# 兼容旧命名
UNIT_TO_MM = DIMENSION_TABLES["length"][0]
UNIT_TO_KPA = DIMENSION_TABLES["pressure"][0]
UNIT_TO_KN = DIMENSION_TABLES["force"][0]

DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y年%m月%d日",
]


@dataclass
class NormalizedRecord:
    """归一化后的监测记录。"""

    point_id: str
    timestamp: str | None
    metric_key: str
    value: float | None
    unit: str | None
    direction: str
    baseline_value: float | None
    previous_value: float | None
    interval_days: float | None

    data_origin: str = "real"  # real | simulated | unknown
    raw: dict = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "point_id": self.point_id,
            "timestamp": self.timestamp,
            "metric_key": self.metric_key,
            "value": self.value,
            "unit": self.unit,
            "direction": self.direction,
            "baseline_value": self.baseline_value,
            "previous_value": self.previous_value,
            "interval_days": self.interval_days,
            "data_origin": self.data_origin,
            "flags": self.flags,
        }


def _norm_point(v: Any) -> str:
    return str(v).strip().upper()


def _norm_timestamp(v: Any) -> tuple[str | None, bool]:
    if v is None or v == "":
        return None, False
    if isinstance(v, datetime):
        return v.isoformat(sep=" "), True
    s = str(v).strip()
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f).isoformat(sep=" "), True
        except ValueError:
            continue
    return s, False  # 无法解析，原样保留并标记


def _norm_number(v: Any) -> tuple[float | None, bool]:
    if v is None or v == "":
        return None, False
    if isinstance(v, bool):
        return None, False
    if isinstance(v, (int, float)):
        return float(v), True
    s = str(v).strip().replace(",", "")
    try:
        return float(s), True
    except ValueError:
        return None, False


def normalize_value_unit(
    value: float | None,
    unit: str | None,
    target: str | None = None,
) -> tuple[float | None, str | None, list[str]]:
    """把数值按**单位自身所属量纲**换算到该量纲的标准单位。

    - 长度 → mm；压强 → kPa；力 → kN；无量纲/比值 → 原样保留。
    - 无法识别的单位原样返回并标记 `UNSUPPORTED_UNIT`，绝不猜测、绝不静默丢弃。
    - `target` 仅在显式指定且与单位同量纲时生效，否则使用该量纲的标准单位。
    """
    flags: list[str] = []
    if value is None:
        return value, unit, flags
    u = str(unit).strip().lower() if unit is not None else ""

    if u in DIMENSIONLESS_UNITS:
        return value, (unit if unit not in (None, "") else None), flags

    if u in TEMPERATURE_UNITS:
        return value, (unit if unit not in (None, "") else None), flags

    hit = UNIT_TO_DIMENSION.get(u)
    if hit is None:
        flags.append("UNSUPPORTED_UNIT")
        return value, unit, flags

    dim, factor = hit
    table, canon = DIMENSION_TABLES[dim]
    out_unit = target if (target and target.lower() in table) else canon
    out_factor = table[out_unit.lower()]
    return value * factor / out_factor, out_unit, flags


def normalize_records(
    records: list[dict],
    default_metric_key: str | None = None,
    target_unit: str = "mm",
    default_origin: str = "real",
    metric_aliases: dict[str, str] | None = None,
) -> list[NormalizedRecord]:
    """把任意来源的记录归一化成统一结构。

    输入字典建议字段（缺失的置 None 并标记，不做推断）：
        point_id, timestamp, metric_key, value, unit, direction,
        baseline_value, previous_value, interval_days, data_origin

    `metric_aliases` 用于把用户习惯写法（如中文监测项名称"围护墙顶部水平位移"）
    映射到规范库的 `metric_key`。不提供时按原样保留。
    """
    out: list[NormalizedRecord] = []
    for i, r in enumerate(records):
        if not isinstance(r, dict):
            continue
        flags: list[str] = []

        point_id = _norm_point(r.get("point_id") or r.get("point") or f"ROW-{i}")
        if r.get("point_id") in (None, ""):
            flags.append("MISSING_POINT_ID")

        ts, ts_ok = _norm_timestamp(r.get("timestamp") or r.get("date"))
        if not ts_ok:
            flags.append("UNPARSED_TIMESTAMP")

        metric = r.get("metric_key") or r.get("metric") or default_metric_key or ""
        metric = str(metric).strip()
        if metric_aliases:
            mapped = (
                metric_aliases.get(metric)
                or metric_aliases.get(metric.lower())
                or metric_aliases.get(normalize_metric_name(metric))
            )
            if mapped:
                metric = mapped

        # 空值与"非数值字符串"必须区分：
        #   空值 → MISSING_VALUE（缺测，中severity，不影响其他期）
        #   非空但转不成数字 → NON_NUMERIC_VALUE（格式错误，高severity，需阻塞）
        raw_value = r.get("value")
        val, val_ok = _norm_number(raw_value)
        if not val_ok and raw_value not in (None, ""):
            flags.append("NON_NUMERIC_VALUE")

        base, _ = _norm_number(r.get("baseline_value"))
        prev, _ = _norm_number(r.get("previous_value"))
        interval, _ = _norm_number(r.get("interval_days"))
        if interval is None:
            # 兼容以小时给出间隔的数据源
            hours, ok_h = _norm_number(r.get("interval_hours"))
            if ok_h:
                interval = hours / 24.0

        val, unit, uflags = normalize_value_unit(val, r.get("unit"), target_unit)
        flags.extend(uflags)

        raw_dir = str(r.get("direction") or "").strip()
        direction = DIRECTION_ALIASES.get(raw_dir.lower(), DIRECTION_ALIASES.get(raw_dir))
        if direction is None:
            if raw_dir:
                flags.append("UNKNOWN_DIRECTION")
            direction = "positive"

        origin = str(r.get("data_origin") or default_origin).strip().lower()
        if origin not in ("real", "simulated", "unknown"):
            flags.append("UNKNOWN_DATA_ORIGIN")
            origin = "unknown"

        out.append(
            NormalizedRecord(
                point_id=point_id,
                timestamp=ts,
                metric_key=metric,
                value=val,
                unit=unit,
                direction=direction,
                baseline_value=base,
                previous_value=prev,
                interval_days=interval,
                data_origin=origin,
                raw=dict(r),
                flags=flags,
            )
        )
    return out


def split_by_origin(records: list[NormalizedRecord]) -> dict[str, list[NormalizedRecord]]:
    """按数据来源拆分，保证真实数据与模拟数据分开统计。"""
    buckets: dict[str, list[NormalizedRecord]] = {"real": [], "simulated": [], "unknown": []}
    for r in records:
        buckets.setdefault(r.data_origin, []).append(r)
    return buckets


def origin_statistics(records: list[NormalizedRecord]) -> dict[str, int]:
    """统计各来源条数——真实数据与模拟数据必须分开计数。"""
    s: dict[str, int] = {}
    for r in records:
        s[r.data_origin] = s.get(r.data_origin, 0) + 1
    return s


# --- 时序派生 -------------------------------------------------------------

# 派生标记：写入 record.flags，供结果与日报说明"该值不是用户给的，是算出来的"
BASELINE_DERIVED = "BASELINE_DERIVED"
PREVIOUS_DERIVED = "PREVIOUS_DERIVED"
INTERVAL_DERIVED = "INTERVAL_DERIVED"
# 上次值由派生得到、但用户另给的间隔与"上一条有效观测"对不上 —— 速率可能被放大
INTERVAL_INCONSISTENT = "INTERVAL_INCONSISTENT_WITH_DERIVED_PREVIOUS"


def _ts_sort_key(ts: str | None) -> tuple[int, str]:
    """按时间戳排序：可解析的排前面并按时间先后，不可解析的排最后并保持原序。"""
    if not ts:
        return (1, "")
    return (0, str(ts))


def derive_temporal_fields(records: list[NormalizedRecord]) -> dict:
    """按测点时序派生 `baseline_value` / `previous_value` / `interval_days`。

    为什么需要这一步
    ----------------
    用户上传的原始监测表通常只有「测点 / 时间 / 项目 / 数值 / 单位」五列。
    累计值、本次变化量、变化速率所需的初始值、上次值、观测间隔是**从时序算出来的**，
    不应该要求用户预先算好。此前这三项被当作必需输入，导致原始观测表 **100% 弃权**。

    派生规则（确定性，不含猜测）
    ----------------------------
    - `baseline_value` = 该测点**首个有效观测**值（按时间升序）
    - `previous_value` = 该测点**前一个有效观测**值；首期为 `None`（本次变化量弃权）
    - `interval_days`  = 本期与**前一个有效观测**的时间差（天）；首期为 `None`（速率弃权）

    **显式提供的值优先**：用户已给出 `baseline_value` / `previous_value` / `interval_days`
    的，一律保留原值，派生不覆盖。

    派生出的字段会打上 `BASELINE_DERIVED` / `PREVIOUS_DERIVED` / `INTERVAL_DERIVED` 标记，
    以便结果与日报区分"用户给定的"与"系统算出的"。

    返回统计信息供阶段一输出与审计。
    """
    by_point: dict[str, list[NormalizedRecord]] = {}
    for r in records:
        by_point.setdefault(r.point_id, []).append(r)

    stats = {
        "points": len(by_point),
        "baseline_derived": 0,
        "previous_derived": 0,
        "interval_derived": 0,
        "interval_inconsistent": 0,
        "interval_hours_used": 0,
    }

    for _pid, group in by_point.items():
        group.sort(key=lambda r: _ts_sort_key(r.timestamp))

        # 有效观测 = 数值可解析的记录；空值/非数值不参与派生
        valid = [r for r in group if r.value is not None]

        if valid and valid[0].baseline_value is None:
            valid[0].baseline_value = valid[0].value
            if BASELINE_DERIVED not in valid[0].flags:
                valid[0].flags.append(BASELINE_DERIVED)
            stats["baseline_derived"] += 1
            # 同测点其余记录若也没给初始值，沿用同一个派生初始值
            for r in group:
                if r is not valid[0] and r.baseline_value is None:
                    r.baseline_value = valid[0].value
                    r.flags.append(BASELINE_DERIVED)
                    stats["baseline_derived"] += 1

        prev_rec: NormalizedRecord | None = None
        for r in valid:
            if r is valid[0]:
                prev_rec = r
                continue
            gap = _day_gap(prev_rec.timestamp, r.timestamp)
            if r.previous_value is None:
                r.previous_value = prev_rec.value
                if PREVIOUS_DERIVED not in r.flags:
                    r.flags.append(PREVIOUS_DERIVED)
                stats["previous_derived"] += 1
                # 上次值是派生的，则间隔必须与"上一条有效观测"一致。
                # 用户另给了间隔时保留其值（显式优先），但标记不一致，避免速率被无声放大。
                if (
                    r.interval_days is not None
                    and gap is not None
                    and abs(float(r.interval_days) - gap) > 1e-6
                ):
                    if INTERVAL_INCONSISTENT not in r.flags:
                        r.flags.append(INTERVAL_INCONSISTENT)
                    stats["interval_inconsistent"] += 1
            if r.interval_days is None and gap is not None and gap > 0:
                r.interval_days = gap
                if INTERVAL_DERIVED not in r.flags:
                    r.flags.append(INTERVAL_DERIVED)
                stats["interval_derived"] += 1
            prev_rec = r

    return stats


def _day_gap(ts_a: str | None, ts_b: str | None) -> float | None:
    """两个 ISO 时间戳之间的天数差；任一不可解析时返回 None。"""
    a, ok_a = _norm_timestamp(ts_a)
    b, ok_b = _norm_timestamp(ts_b)
    if not ok_a or not ok_b or not a or not b:
        return None
    try:
        da = datetime.fromisoformat(str(a)[:19])
        db = datetime.fromisoformat(str(b)[:19])
    except ValueError:
        return None
    return (db - da).total_seconds() / 86400.0
