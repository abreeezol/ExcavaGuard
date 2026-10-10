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
from pathlib import Path
from typing import Any

# --- 列名别名 -------------------------------------------------------------

REQUIRED_COLUMNS = ("point_id", "timestamp", "metric", "value", "unit")
DERIVABLE_COLUMNS = ("baseline_value", "previous_value", "interval_days", "interval_hours")
OPTIONAL_COLUMNS = ("direction", "data_origin", "note")

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
    "note": ("note", "remark", "remarks", "comment", "comment_text", "备注", "说明"),
}

ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin-1")
DELIMITERS = (",", ";", "\t", "|")


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
    rows: list[list[str]] = []
    for row in ws.iter_rows(values_only=True):
        cells = ["" if c is None else str(c) for c in row]
        if any(c.strip() for c in cells):
            rows.append(cells)
    wb.close()
    return rows, {
        "source": str(p),
        "format": "excel",
        "encoding": None,
        "delimiter": None,
        "sheet": ws.title,
        "raw_rows": len(rows),
    }


# --- 主入口 ---------------------------------------------------------------

def read_monitoring_file(path: str | Path) -> tuple[list[dict], dict]:
    """读取用户上传的监测数据文件 → (records, report)。

    records 的键为规范字段名，值一律为**字符串原样**（除缺列为 None）。
    report 记录读取与映射过程，供用户核对；`missing_required` 非空表示拒收。
    """
    rows, meta = read_table(path)

    if not rows:
        return [], {**meta, "ok": False, "errors": ["文件没有可读数据行"], "missing_required": list(REQUIRED_COLUMNS)}

    header, body = rows[0], rows[1:]
    index_map, field_to_index, unmapped = map_header(header)
    missing_required = [c for c in REQUIRED_COLUMNS if c not in field_to_index]

    report: dict[str, Any] = {
        **meta,
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
