"""Deterministic range selection and summaries; never infer missing observations."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta
from hashlib import sha256
import calendar
import json
from zoneinfo import ZoneInfo

SCHEMA = "excavaguard.period_report_input/v1"
DAILY_SCHEMA = "excavaguard.daily_report_input/v1"
RANK = {"未知": -1, "正常": 0, "关注": 1, "预警": 2, "报警": 3, "危险报警": 4}
LABELS = {"weekly": "监测周报", "monthly": "监测月报", "custom": "监测区间报告"}


def day_of(value):
    if not value:
        raise ValueError("观测时间缺失，无法确定周期归属。")
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00").replace("/", "-"))
    if parsed.tzinfo:
        parsed = parsed.astimezone(ZoneInfo("Asia/Shanghai"))
    return parsed.date().isoformat()


def validate_period(period):
    if not isinstance(period, dict) or set(period) != {"type", "start_date", "end_date"}:
        raise ValueError("report_period需要type、start_date和end_date。")
    if period["type"] not in LABELS:
        raise ValueError("周期类型必须是weekly、monthly或custom。")
    start, end = date.fromisoformat(period["start_date"]), date.fromisoformat(period["end_date"])
    if start.isoformat() != period["start_date"] or end.isoformat() != period["end_date"]:
        raise ValueError("日期必须使用YYYY-MM-DD格式。")
    count = (end - start).days + 1
    if not 1 <= count <= 366:
        raise ValueError("起止日期必须有序，区间为1至366天（含首尾日）。")
    if period["type"] == "weekly" and count != 7:
        raise ValueError("周报必须包含连续7个自然日。")
    if period["type"] == "monthly" and (
        start.day != 1 or start.year != end.year or start.month != end.month
        or end.day != calendar.monthrange(start.year, start.month)[1]
    ):
        raise ValueError("月报必须覆盖完整自然月。")
    return [(start + timedelta(days=n)).isoformat() for n in range(count)]


def cutoff_records(records, end_date):
    """Validate every timestamp, preserve past history, exclude future observations."""
    output = []
    for record in records:
        # File reader normalizes column aliases before this boundary.
        day = day_of(record.get("timestamp"))
        if day <= end_date:
            item = deepcopy(record)
            # Convert aware times to the project timezone before daily grouping.
            ts = datetime.fromisoformat(str(item["timestamp"]).replace("Z", "+00:00").replace("/", "-"))
            if ts.tzinfo:
                item["timestamp"] = ts.astimezone(ZoneInfo("Asia/Shanghai")).isoformat()
            output.append(item)
    return output


def _worst(items):
    return max(items, key=lambda x: (RANK.get(x.get("risk_level"), -1), str(x.get("timestamp") or "")))


def _hash(value):
    # JSON round-trips through JavaScript turn 5.0 into 5; preserve semantic hashes.
    def normalized(item):
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, list):
            return [normalized(v) for v in item]
        if isinstance(item, dict):
            return {k: normalized(v) for k, v in item.items()}
        return item
    return sha256(json.dumps(normalized(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def period_statistics(items, spec):
    days = validate_period(spec)
    allowed = set(days)
    by_day = defaultdict(list)
    channels = defaultdict(list)
    for item in items:
        day = day_of(item.get("timestamp"))
        if day not in allowed:
            raise ValueError("周期明细含区间之外的观测。")
        by_day[day].append(item)
        channels[(str(item.get("point_id") or ""), str(item.get("metric_key") or ""))].append(item)
    if not items:
        raise ValueError("选定区间没有监测记录；不能生成空白正常报告。")
    if len(items) > 50000:
        raise ValueError("单次周期明细超过50000条，请缩短区间或减少通道。")
    daily = []
    for day in days:
        rows = by_day.get(day, [])
        daily.append({
            "date": day, "observation_count": len(rows),
            "warning_count": sum(RANK.get(x.get("risk_level"), -1) >= 2 for x in rows),
            "unknown_count": sum(x.get("risk_level") == "未知" for x in rows),
            "worst_known_risk": _worst(rows).get("risk_level") if rows else "未知",
            "missing": not rows, "content_hash": _hash(rows),
        })
    channel_stats, representatives = [], []
    for (point, metric), rows in sorted(channels.items()):
        rows.sort(key=lambda x: str(x.get("timestamp") or ""))
        observed = sorted({day_of(x["timestamp"]) for x in rows})
        warned = sorted({day_of(x["timestamp"]) for x in rows if RANK.get(x.get("risk_level"), -1) >= 2})
        unknown = sorted({day_of(x["timestamp"]) for x in rows if x.get("risk_level") == "未知"})
        longest, streak = 0, 0
        for day in days:
            streak = streak + 1 if day in warned else 0
            longest = max(longest, streak)
        representative = deepcopy(_worst(rows))
        representatives.append(representative)
        channel_stats.append({
            "point_id": point, "metric_key": metric, "metric_name": rows[0].get("metric_name"),
            "observed_days": len(observed), "missing_dates": [d for d in days if d not in observed],
            "warning_days": len(warned), "warning_dates": warned, "max_consecutive_warning_days": longest,
            "unknown_days": len(unknown), "unknown_dates": unknown,
            "worst_known_risk": representative.get("risk_level"),
            "first_observation_date": observed[0], "last_observation_date": observed[-1],
            "first_current": rows[0].get("current"), "last_current": rows[-1].get("current"),
            "representative_timestamp": representative.get("timestamp"),
        })
    return {
        **spec, "label": LABELS[spec["type"]], "timezone": "Asia/Shanghai",
        "calendar_days": len(days), "observed_days": len(by_day),
        "missing_dates": [d for d in days if d not in by_day],
        "observation_count": len(items), "channel_count": len(channels),
        "warning_point_days": sum(len({day_of(x["timestamp"]) for x in rows if RANK.get(x.get("risk_level"), -1) >= 2}) for rows in channels.values()),
        "unknown_observation_count": sum(x.get("risk_level") == "未知" for x in items),
        "daily_summaries": daily, "channels": channel_stats,
        "recurring_warnings": [x for x in channel_stats if x["warning_days"] >= 2],
        "aggregation_policy": "daily-facts/v1; distinct warning days >= 2; unknown and missing disclosed separately",
    }, representatives


def build_period_report_input(result, spec, *, project=None, points_meta=None):
    from orchestrator import build_daily_report_input, _summarize_report_items
    days = validate_period(spec)
    # No item-date filtering: this first preserves the calculation's complete history.
    base = build_daily_report_input(result, project=project, points_meta=points_meta, report_date=spec["end_date"])
    rows = [deepcopy(x) for x in base["items"] if days[0] <= day_of(x.get("timestamp")) <= days[-1]]
    rows.sort(key=lambda x: (day_of(x["timestamp"]), str(x.get("point_id")), str(x.get("metric_key")), str(x["timestamp"])))
    stats, representatives = period_statistics(rows, spec)
    base["schema"] = SCHEMA
    base["contract"]["schema_file"] = "确定性计算层/contracts/period_report_input.schema.json"
    base["period"] = {**stats, "daily_items": rows}
    base["items"] = representatives
    base["summary"] = _summarize_report_items(representatives)
    base["alerts"] = [x for x in representatives if RANK.get(x.get("risk_level"), -1) >= 3]
    base["review_queue"] = [x for x in rows if x.get("needs_review") or x.get("risk_level") == "未知"]
    issues = [x for x in (result.stage1.get("quality_report") or {}).get("issues", []) if x.get("timestamp") and days[0] <= day_of(x["timestamp"]) <= days[-1]]
    base["data_quality"] = {"issue_count": len(issues), "by_code": dict(Counter(x.get("code", "UNKNOWN") for x in issues)),
                            "blocked_records": sum("DATA_QUALITY_BLOCKED" in (x.get("abstain") or []) for x in rows)}
    base["context"].update({"records": len(representatives), "item_date": None,
        "real_records": sum(x.get("data_origin") == "real" for x in representatives),
        "simulated_records": sum(x.get("data_origin") == "simulated" for x in representatives)})
    base["project"]["report_date"] = spec["end_date"]
    base["note"] = "周期明细按选定区间统计，区间之前的历史仅用于计算；每通道附表展示周期最严重原观测，非期末值。未知、缺测独立披露。宽表沿用每日末值，日内极值未经独立风险判定，须结合原数据复核。工程条件和判据按本次输入统一应用，期间如有变化须分段重算。"
    return base


def validate_period_payload(payload):
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return ["非法周期载荷schema。"]
    try:
        period = payload["period"]
        spec = {k: period[k] for k in ("type", "start_date", "end_date")}
        expected, representatives = period_statistics(period["daily_items"], spec)
        if any(period.get(k) != v for k, v in expected.items()):
            return ["周期统计、日期覆盖或每日来源hash与冻结明细不一致。"]
        if payload.get("items") != representatives or payload.get("project", {}).get("report_date") != spec["end_date"]:
            return ["周期代表观测或报告日期不一致。"]
        from orchestrator import _summarize_report_items
        if payload.get("summary") != _summarize_report_items(representatives):
            return ["周期风险汇总与代表观测不一致。"]
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return [f"周期载荷无效：{exc}"]
    return []
