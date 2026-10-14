"""
阶段一 · 用户数据文件读取器
============================

把用户上传的监测数据文件（CSV / TSV / Excel）读成统一记录列表。

设计原则
--------
- **只读取与映射，不计算、不推断、不修改数值**。数值是否合法交由质量扫描判定。
- **列名宽松匹配**：支持中英文常见写法（见 `COLUMN_ALIASES`）。
- **编码自动探测**：UTF-8 BOM / UTF-8 / GB18030 / GBK / Big5 / Latin-1 依次尝试。
- **必需列缺失即拒收**，并明确列出缺了哪几列 —— 不猜、不补。
- 仅 `read_table()` 的 Excel 分支需要 `openpyxl`；**CSV 路径纯标准库**，
  未安装 openpyxl 时读取 .xlsx 会给出明确提示而不是崩溃。

必填列（5 个）
--------------
    point_id, timestamp, metric, value, unit

可派生列（缺失时由 `ingest.derive_temporal_fields()` 按测点时序派生）
--------------------------------------------------------------------
    baseline_value, previous_value, interval_days / interval_hours

可选列
------
    direction, data_origin, note
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

# --- 列名别名 -------------------------------------------------------------

REQUIRED_COLUMNS = ("point_id", "timestamp", "metric", "value", "unit")
DERIVABLE_COLUMNS = ("baseline_value", "previous_value", "interval_days", "interval_hours")
OPTIONAL_COLUMNS = (
    "direction",
    "data_origin",
    "measurement_semantics",
    "source_flags",
    "source_metadata",
    "note",
)

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "point_id": (
        "point_id", "pointid", "point", "point_no", "pointno", "point_code",
        "pointcode", "sensor_id", "sensorid", "id", "测点", "测点编号", "测点号", "点号", "编号",
    ),
    "timestamp": (
        "timestamp", "date", "time", "datetime", "obs_time", "obstime", "observation_time",
        "观测时间", "日期", "时间", "监测日期", "观测日期",
    ),
    "metric": (
        "metric", "metric_key", "metrickey", "item", "monitoring_item", "monitoringitem",
        "type", "监测项目", "监测项", "项目", "参数",
    ),
    "value": (
        "value", "reading", "observed", "observed_value", "current", "current_value",
        "measured", "measurement", "观测值", "本次观测值", "本次值", "实测值", "数值", "读数",
    ),
    "unit": ("unit", "units", "单位", "计量单位"),
    "direction": ("direction", "dir", "sign", "方向", "符号"),
    "baseline_value": (
        "baseline_value", "baselinevalue", "baseline", "base", "initial_value",
        "initialvalue", "initial", "reference_value", "初始值", "基准值", "初值",
    ),
    "previous_value": (
        "previous_value", "previousvalue", "previous", "prev", "prev_value",
        "last_value", "lastvalue", "上次观测值", "上次值", "前次值", "上期值",
    ),
    "interval_days": ("interval_days", "intervaldays", "interval", "间隔天数", "间隔"),
    "interval_hours": ("interval_hours", "intervalhours", "间隔小时"),
    "data_origin": ("data_origin", "dataorigin", "origin", "数据来源", "来源"),
    "measurement_semantics": (
        "measurement_semantics", "measurementsemantics", "value_semantics",
        "valuesemantics", "量值语义", "数值语义",
    ),
    "source_flags": ("source_flags", "sourceflags", "来源标记"),
    "source_metadata": ("source_metadata", "sourcemetadata", "来源元数据"),
    "note": ("note", "remark", "remarks", "comment", "comment_text", "备注", "说明"),
}

ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin-1")
DELIMITERS = (",", ";", "\t", "|")

WIDE_SEMANTICS = {
    "原始值": "raw_observation",
    "累计位移量": "precomputed_cumulative",
    "累计量": "precomputed_cumulative",
    "累计值": "precomputed_cumulative",
}

_WIDE_HEADER_RE = re.compile(
    r"^(?P<body>.+)-(?P<semantic>累计位移量|累计量|累计值|原始值)"
    r"\s*[\(（](?P<unit>[^()（）]+)[\)）]\s*$"
)
_POINT_ID_RE = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+$")


def _canon(name: str) -> str:
    """列名归一：去空白/下划线/连字符/括号/单位后缀，转小写。"""
    s = str(name or "").strip().lower()
    for ch in (" ", "_", "-", "　", "(", ")", "（", "）", "[", "]", "/", "\\", "."):
        s = s.replace(ch, "")
    return s


_ALIAS_LOOKUP: dict[str, str] = {}
for _target, _names in COLUMN_ALIASES.items():
    for _n in _names:
        _ALIAS_LOOKUP.setdefault(_canon(_n), _target)


def map_header(header: list[str]) -> tuple[dict[int, str], dict[str, int], list[str]]:
    """把表头映射为 {列下标: 规范字段名}。

    返回 (index_map, field_to_index, unmapped_headers)。
    同一规范字段出现多列时取**第一个**匹配，后续重复列记入 unmapped。
    """
    index_map: dict[int, str] = {}
    field_to_index: dict[str, int] = {}
    unmapped: list[str] = []
    for i, raw in enumerate(header):
        key = _canon(raw)
        field = _ALIAS_LOOKUP.get(key)
        if field is None:
            if str(raw or "").strip():
                unmapped.append(str(raw).strip())
            continue
        if field in field_to_index:
            unmapped.append(str(raw).strip())
            continue
        index_map[i] = field
        field_to_index[field] = i
    return index_map, field_to_index, unmapped


# --- 编码与分隔符探测 -----------------------------------------------------

def detect_encoding(path: Path, sample_bytes: int = 65536) -> str:
    """依次尝试候选编码，返回首个能完整解码且无替换字符的。"""
    raw = path.read_bytes()[:sample_bytes]
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        if "\ufffd" not in text:
            return enc
    return "latin-1"  # 兜底：任何字节都能解码，不丢数据


def detect_delimiter(sample: str) -> str:
    """用首行（表头）出现次数最多的候选分隔符。"""
    first = sample.splitlines()[0] if sample.splitlines() else ""
    counts = {d: first.count(d) for d in DELIMITERS}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] > 0 else ","


# --- 读取 -----------------------------------------------------------------

def read_table(path: str | Path) -> tuple[list[list[str]], dict]:
    """读成二维字符串表（含表头行），并返回读取元信息。

    数值不做转换，原样保留字符串 —— 非法数值由阶段一质量扫描识别。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在：{p}")

    suffix = p.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return _read_excel(p)
    if suffix in (".csv", ".txt", ".tsv"):
        return _read_delimited(p)
    # 无扩展名时按文本尝试
    return _read_delimited(p)


def _read_delimited(p: Path) -> tuple[list[list[str]], dict]:
    enc = detect_encoding(p)
    text = p.read_text(encoding=enc, errors="replace")
    if text.startswith("\ufeff"):
        text = text[1:]
    delim = detect_delimiter(text)
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim)]
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    return rows, {
        "source": str(p),
        "format": "delimited",
        "encoding": enc,
        "delimiter": {"\t": "\\t"}.get(delim, delim),
        "raw_rows": len(rows),
    }


def _read_excel(p: Path) -> tuple[list[list[str]], dict]:
    try:
        import openpyxl
    except ModuleNotFoundError as exc:  # pragma: no cover - 取决于运行环境
        raise RuntimeError(
            f"读取 {p.suffix} 需要 openpyxl，当前环境未安装。"
            "请将文件另存为 CSV（UTF-8）后重试，或安装 openpyxl。"
        ) from exc

    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    sheet_title = ws.title
    rows: list[list[str]] = []
    for row in ws.iter_rows(values_only=True):
        cells = ["" if c is None else str(c) for c in row]
        if any(c.strip() for c in cells):
            rows.append(cells)

    source_notes: list[str] = []
    for note_sheet in wb.worksheets[1:]:
        if not any(token in note_sheet.title.lower() for token in ("说明", "note", "readme")):
            continue
        for row in note_sheet.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                source_notes.append(" | ".join(cells))

    note_text = "\n".join(source_notes)
    source_flags: list[str] = []
    if "对齐" in note_text:
        source_flags.append("SOURCE_TIME_ALIGNED")
    if "重采样" in note_text:
        source_flags.append("SOURCE_RESAMPLED")
    if "线性插值" in note_text:
        source_flags.append("SOURCE_LINEAR_INTERPOLATION_PRESENT")
    if "末值保持" in note_text:
        source_flags.append("SOURCE_END_VALUE_HOLD_PRESENT")
    if any(flag.endswith("_PRESENT") for flag in source_flags):
        source_flags.append("SOURCE_CELL_PROVENANCE_UNAVAILABLE")

    sheet_names = list(wb.sheetnames)
    wb.close()
    return rows, {
        "source": str(p),
        "format": "excel",
        "encoding": None,
        "delimiter": None,
        "sheet": sheet_title,
        "sheets": sheet_names,
        "raw_rows": len(rows),
        "source_notes": source_notes,
        "source_flags": source_flags,
    }


# --- 主入口 ---------------------------------------------------------------

def parse_wide_channel_header(header: str) -> dict[str, str] | None:
    """解析 ``监测项目-测点号-量值语义(单位)`` 宽表通道名。

    裂缝长度/宽度共享点号，长度或宽度并入监测项名称，不并入点号。
    无法明确拆分时返回 ``None``，调用方必须拒绝而不是猜测。
    """
    text = str(header or "").strip()
    match = _WIDE_HEADER_RE.fullmatch(text)
    if match is None:
        return None

    parts = [part.strip() for part in match.group("body").split("-") if part.strip()]
    if len(parts) < 3:
        return None

    metric = parts[0]
    point_parts = parts[1:]
    if metric == "裂缝" and point_parts[-1] in ("长度", "宽度"):
        metric += point_parts[-1]
        point_parts = point_parts[:-1]

    point_id = "-".join(point_parts)
    if not metric or not _POINT_ID_RE.fullmatch(point_id):
        return None

    semantic_label = match.group("semantic")
    return {
        "point_id": point_id,
        "metric": metric,
        "unit": match.group("unit").strip(),
        "measurement_semantics": WIDE_SEMANTICS[semantic_label],
        "semantic_label": semantic_label,
    }


def _read_wide_rows(
    rows: list[list[str]],
    meta: dict,
    field_to_index: dict[str, int],
) -> tuple[list[dict], dict]:
    header, body = rows[0], rows[1:]
    timestamp_index = field_to_index.get("timestamp")
    if timestamp_index is None:
        return [], {
            **meta,
            "layout": "wide",
            "header": [str(h) for h in header],
            "missing_required": list(REQUIRED_COLUMNS),
            "data_rows": len(body),
            "ok": False,
            "errors": ["宽表缺少可识别的时间列。"],
        }

    channels: list[tuple[int, dict[str, str]]] = []
    unparsed: list[str] = []
    duplicate_channels: list[str] = []
    seen_channels: set[tuple[str, str]] = set()
    for index, raw_header in enumerate(header):
        if index == timestamp_index or not str(raw_header or "").strip():
            continue
        parsed = parse_wide_channel_header(str(raw_header))
        if parsed is None:
            unparsed.append(str(raw_header).strip())
        else:
            channel_key = (parsed["point_id"], parsed["metric"])
            if channel_key in seen_channels:
                duplicate_channels.append(str(raw_header).strip())
            else:
                seen_channels.add(channel_key)
                channels.append((index, parsed))

    errors: list[str] = []
    if not channels:
        errors.append("未识别到符合“监测项目-测点号-量值语义(单位)”格式的宽表通道。")
    if unparsed:
        errors.append(f"存在 {len(unparsed)} 个无法明确解析的宽表通道，未静默丢弃。")
    if duplicate_channels:
        errors.append(f"存在 {len(duplicate_channels)} 个重复的测点+监测项通道。")

    report: dict[str, Any] = {
        **meta,
        "layout": "wide",
        "header": [str(h) for h in header],
        "mapped_columns": {timestamp_index: "timestamp"},
        "unmapped_columns": unparsed,
        "duplicate_channels": duplicate_channels,
        "missing_required": (
            [] if channels and not unparsed and not duplicate_channels
            else list(REQUIRED_COLUMNS)
        ),
        "derivable_columns_present": [],
        "data_rows": len(body),
        "channel_count": len(channels),
        "expanded_records": len(body) * len(channels),
        "wide_channels": [
            {
                "column": index,
                "header": str(header[index]),
                **parsed,
            }
            for index, parsed in channels
        ],
        "ok": bool(channels) and not unparsed and not duplicate_channels,
        "errors": errors,
    }
    if not report["ok"]:
        return [], report

    workbook_flags = [str(flag) for flag in meta.get("source_flags", [])]
    records: list[dict] = []
    for row in body:
        timestamp = row[timestamp_index] if timestamp_index < len(row) else ""
        timestamp = str(timestamp).strip() or None
        for index, channel in channels:
            value = row[index] if index < len(row) else ""
            value_text = "" if value is None else str(value).strip()
            records.append(
                {
                    "point_id": channel["point_id"],
                    "timestamp": timestamp,
                    "metric": channel["metric"],
                    "value": value_text or None,
                    "unit": channel["unit"],
                    "measurement_semantics": channel["measurement_semantics"],
                    "data_origin": "real",
                    "source_flags": ["WIDE_FORMAT_EXPANDED", *workbook_flags],
                    "source_metadata": {
                        "source_sheet": meta.get("sheet"),
                        "source_column": index,
                        "source_header": str(header[index]),
                        "semantic_label": channel["semantic_label"],
                    },
                }
            )
    return records, report


def read_monitoring_rows(rows: list[list[str]], meta: dict | None = None) -> tuple[list[dict], dict]:
    """把已读取的二维表映射为长表记录，供文件入口和固定样例测试复用。"""
    read_meta = dict(meta or {})
    if not rows:
        return [], {
            **read_meta,
            "ok": False,
            "errors": ["文件没有可读数据行"],
            "missing_required": list(REQUIRED_COLUMNS),
        }

    header, body = rows[0], rows[1:]
    index_map, field_to_index, unmapped = map_header(header)
    missing_required = [c for c in REQUIRED_COLUMNS if c not in field_to_index]

    if missing_required and "timestamp" in field_to_index:
        parsed_channels = [
            parse_wide_channel_header(str(raw))
            for index, raw in enumerate(header)
            if index != field_to_index["timestamp"] and str(raw or "").strip()
        ]
        if any(channel is not None for channel in parsed_channels):
            return _read_wide_rows(rows, read_meta, field_to_index)

    report: dict[str, Any] = {
        **read_meta,
        "layout": "long",
        "header": [str(h) for h in header],
        "mapped_columns": {field_to_index[f]: f for f in field_to_index},
        "unmapped_columns": unmapped,
        "missing_required": missing_required,
        "derivable_columns_present": [c for c in DERIVABLE_COLUMNS if c in field_to_index],
        "data_rows": len(body),
        "ok": not missing_required,
        "errors": [],
    }

    if missing_required:
        report["errors"].append(
            f"缺少必填列：{'、'.join(missing_required)}。"
            f"必填列为 {list(REQUIRED_COLUMNS)}；"
            f"baseline_value / previous_value / interval_days / interval_hours 可缺失，"
            f"由阶段一按测点时序派生。"
        )
        return [], report

    records: list[dict] = []
    for row in body:
        rec: dict[str, Any] = {}
        for idx, field in index_map.items():
            v = row[idx] if idx < len(row) else ""
            rec[field] = str(v).strip() if v is not None and str(v).strip() != "" else None
        records.append(rec)

    return records, report


def read_monitoring_file(path: str | Path) -> tuple[list[dict], dict]:
    """读取用户上传的监测数据文件 → ``(records, report)``。

    五列长表按字段别名映射；混合宽表按明确通道名展开为长记录。
    ``report`` 记录布局、列映射、来源说明和展开数量，供用户核对。
    """
    rows, meta = read_table(path)
    return read_monitoring_rows(rows, meta)


def _parse_record_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def aggregate_daily_records(
    records: list[dict],
    report_date: str | None = None,
) -> tuple[list[dict], dict]:
    """把宽表高频记录压缩为截至报告日的逐通道每日末值历史。

    该函数不插值、不修复观测值，只从每个自然日已有记录中选取时间最晚的一条，
    并把日内统计放入 ``source_metadata.daily_aggregation``。
    """
    target_date: date | None = None
    if report_date:
        try:
            target_date = date.fromisoformat(report_date)
        except ValueError as exc:
            raise ValueError(f"报告日期不是有效 ISO 日期：{report_date}") from exc

    grouped: dict[tuple[str, str], list[tuple[datetime, dict]]] = {}
    available_dates: set[date] = set()
    invalid_timestamps = 0
    for record in records:
        ts = _parse_record_timestamp(record.get("timestamp"))
        if ts is None:
            invalid_timestamps += 1
            continue
        available_dates.add(ts.date())
        key = (str(record.get("point_id") or ""), str(record.get("metric") or record.get("metric_key") or ""))
        grouped.setdefault(key, []).append((ts, record))

    if invalid_timestamps:
        raise ValueError(f"宽表存在 {invalid_timestamps} 条无法解析时间的记录，不能执行日报聚合。")
    if target_date and target_date not in available_dates:
        raise ValueError(f"报告日期 {report_date} 在宽表中没有记录。")

    output: list[dict] = []
    included_dates: set[date] = set()
    for values in grouped.values():
        values.sort(key=lambda item: item[0])
        by_day: dict[date, list[tuple[datetime, dict]]] = {}
        for ts, record in values:
            if target_date and ts.date() > target_date:
                continue
            by_day.setdefault(ts.date(), []).append((ts, record))

        for day, samples in by_day.items():
            included_dates.add(day)
            end_ts, end_record = samples[-1]
            selected = dict(end_record)
            numeric: list[tuple[datetime, float]] = []
            for ts, sample in samples:
                try:
                    numeric.append((ts, float(str(sample.get("value")).replace(",", ""))))
                except (TypeError, ValueError):
                    continue

            max_step: float | None = None
            max_step_at: str | None = None
            for (_previous_ts, previous), (current_ts, current) in zip(numeric, numeric[1:]):
                step = abs(current - previous)
                if max_step is None or step > max_step:
                    max_step = step
                    max_step_at = current_ts.isoformat(sep=" ")

            source_metadata = selected.get("source_metadata")
            source_metadata = dict(source_metadata) if isinstance(source_metadata, dict) else {}
            source_metadata["daily_aggregation"] = {
                "date": day.isoformat(),
                "method": "last_record_of_day",
                "sample_count": len(samples),
                "source_start": samples[0][0].isoformat(sep=" "),
                "source_end": end_ts.isoformat(sep=" "),
                "first_value": numeric[0][1] if numeric else None,
                "last_value": numeric[-1][1] if numeric else None,
                "minimum": min((value for _ts, value in numeric), default=None),
                "maximum": max((value for _ts, value in numeric), default=None),
                "max_abs_step": max_step,
                "max_abs_step_at": max_step_at,
            }
            selected["source_metadata"] = source_metadata
            source_flags = list(selected.get("source_flags") or [])
            if "DAILY_END_AGGREGATED" not in source_flags:
                source_flags.append("DAILY_END_AGGREGATED")
            selected["source_flags"] = source_flags
            output.append(selected)

    output.sort(
        key=lambda record: (
            str(record.get("point_id") or ""),
            str(record.get("metric") or record.get("metric_key") or ""),
            str(record.get("timestamp") or ""),
        )
    )
    return output, {
        "method": "last_record_of_day",
        "source_records": len(records),
        "output_records": len(output),
        "channels": len(grouped),
        "report_date": report_date,
        "dates_included": [day.isoformat() for day in sorted(included_dates)],
        "preserved_intraday_fields": [
            "sample_count",
            "source_start",
            "source_end",
            "first_value",
            "last_value",
            "minimum",
            "maximum",
            "max_abs_step",
            "max_abs_step_at",
        ],
    }


def write_contract_example(dest: str | Path) -> Path:
    """导出一份最小可用示例文件（供用户对照填写）。"""
    d = Path(dest)
    d.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "point_id,timestamp,metric,value,unit,direction",
        "WTHD-01,2026-08-01,wall_top_horizontal_displacement,0.0,mm,positive",
        "WTHD-01,2026-08-02,wall_top_horizontal_displacement,2.1,mm,positive",
        "WTHD-01,2026-08-03,wall_top_horizontal_displacement,4.6,mm,positive",
    ]
    d.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return d


if __name__ == "__main__":  # pragma: no cover
    import sys

    if len(sys.argv) < 2:
        print("用法：python file_reader.py <数据文件>")
        raise SystemExit(2)
    recs, rep = read_monitoring_file(sys.argv[1])
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    print(f"记录数：{len(recs)}")
