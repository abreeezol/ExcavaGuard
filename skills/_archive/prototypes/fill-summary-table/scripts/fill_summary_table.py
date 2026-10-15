# -*- coding: utf-8 -*-
"""
表 C / 表 D 规范化填表脚本
============================

把**杂乱的**应力与轴力监测数据，按 GB 50497-2019 附录 C / 附录 D 的表式，
规范地填入与「示例汇总表」同构的工作簿。

用法
----
    # ① 规范表式（表 C / 表 D）—— 默认
    python fill_summary_table.py --input <数据文件或目录> --output <输出.xlsx> \\
        [--meta meta.json] [--limits limits.json] [--date YYYY-MM-DD]

    # ② 判定汇总表（10 列版式，独立文件）
    python fill_summary_table.py --input <数据> --output <判定汇总表.xlsx> \\
        --layout verdict [--design design.json] [--rag auto|off|refresh]

    # ③ 两者同时产出
    python fill_summary_table.py --input <数据> --output <汇总表.xlsx> \\
        --layout both --verdict-out <判定汇总表.xlsx>

输入
----
- 支持 `.csv` / `.tsv` / `.xlsx` / `.xls`，可传单个文件或整个目录。
- 列名容错（中文/英文别名），时间格式容错，单位大小写与量纲容错。

输出
----
**layout=cd（默认）** —— 含 3 个 sheet 的工作簿：
- `表C` —— 围护墙内力、立柱内力及土压力、孔隙水压力（kPa）
- `表D` —— 支撑轴力、锚杆轴力（kN）
- `汇总` —— 结果汇总 / 超限清单 / 待复核 / 工况 / 分析结论 / 签署 / 说明

**layout=verdict** —— 「判定汇总表」独立工作簿：
- `表C判定汇总` / `表D判定汇总` —— 10 列：
  `监测项目 | 点号 | 本次变化量 | 变化速率 | 累计变化量 | 报警值 | 控制值 | 等级 | 规范条文 | 规范依据摘要`
- `说明` —— 抬头 / 判据来源 / 判定口径 / 边界声明 / 限值推导 / RAG 命中明细

边界
----
- 未提供阈值时**一律不判定**（预警等级 = `未判定(待复核)`），**不得默认为「正常」**。
- `未判定(待复核)` 表示**弃权，不是「安全」**。
- 本脚本只做数据整理与表式填充，**不替代**责任单位出具的正式监测报告。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime
from pathlib import Path

import rate_rules

try:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "openpyxl>=3.1.0"])
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter


# ===========================================================================
# 常量
# ===========================================================================
SCHEMA = "excavaguard.summary_table_fill/v1"

UNDETERMINED = "未判定(待复核)"
LEVELS = ["正常", "黄色预警", "橙色预警", "红色预警", UNDETERMINED]

COLUMN_ALIASES: dict[str, list[str]] = {
    "timestamp": ["时间", "日期", "观测日期", "监测日期", "监测时间", "测量时间",
                  "timestamp", "date", "time", "datetime"],
    "point_id": ["点号", "测点", "测点号", "测点编号", "点号编号", "编号",
                 "孔号", "孔号(点号)", "point_id", "point", "sensor_id"],
    "metric": ["监测项目", "项目", "监测项", "监测项目名称", "metric", "item", "metric_key", "sensor_type"],
    "value": ["测值", "本次测值", "本次测试值", "观测值", "实测值", "数值", "value", "reading", "engineering_value"],
    "unit": ["单位", "计量单位", "unit"],
    "depth": ["深度", "深度(m)", "埋深", "深度m", "depth", "depth_m"],
    "group": ["组号", "分组", "group"],
    "prev": ["上次测值", "上期测值", "上次值", "previous_value"],
    "change": ["本次变化", "本次变化量", "单次变化", "本次变化(mm)", "change"],
    "cumulative": ["累计变化", "累计变化量", "累计值", "累计位移量", "累计位移量(mm)",
                   "累计位移(mm)", "累计位移", "cumulative"],
    "rate": ["变化速率", "变化速率(mm/d)", "速率", "rate"],
    "form": ["形态", "裂缝形态", "form"],
    "length": ["长度", "长度(mm)", "length"],
    "width": ["宽度", "宽度(mm)", "width"],
    "elev_init": ["初始高程", "初始高程(m)", "elev_init"],
    "elev_now": ["本次高程", "本次高程(m)", "elev_now"],
    "elev_prev": ["上次高程", "上次高程(m)", "elev_prev"],
    "remark": ["备注", "说明", "remark", "note"],
    "quality": ["质量标记", "数据质量", "quality_flag", "quality"],
    "level": ["预警等级", "预警", "等级", "报警等级", "level", "warning_level"],
}

TIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
    "%Y.%m.%d %H:%M:%S", "%Y.%m.%d",
    "%Y年%m月%d日 %H:%M", "%Y年%m月%d日",
    "%Y%m%d%H%M", "%Y%m%d",
]

UNIT_TO_KPA = {"kpa": 1.0, "mpa": 1000.0, "pa": 0.001, "千帕": 1.0, "兆帕": 1000.0, "帕": 0.001}
UNIT_TO_KN = {"kn": 1.0, "n": 0.001, "mn": 1000.0, "千牛": 1.0, "牛": 0.001}
UNIT_TO_MM = {"mm": 1.0, "毫米": 1.0, "cm": 10.0, "厘米": 10.0, "m": 1000.0, "米": 1000.0}

# 监测项目 → 目标表 / 组号
TABLE_C_METRICS = {"围护墙内力", "立柱内力", "土压力", "孔隙水压力"}
TABLE_D_METRICS = {"支撑轴力", "锚杆轴力"}
TABLE_E_METRICS = {"地下水位", "周边地表竖向位移", "土体分层竖向位移", "坑底隆起"}
TABLE_F_METRICS = {"裂缝"}
# 明确不在本 Skill 处理范围（表 A / 表 B），单独提示，不静默丢弃
TABLE_AB_METRICS = {"水平位移", "深层水平位移"}

FAMILY_METRICS = {
    "表A": TABLE_AB_METRICS, "表B": TABLE_AB_METRICS,
    "表C": TABLE_C_METRICS, "表D": TABLE_D_METRICS,
    "表E": TABLE_E_METRICS, "表F": TABLE_F_METRICS,
}
FAMILY_TITLE = {
    "表C": "围护墙内力、立柱内力及土压力、孔隙水压力",
    "表D": "支撑轴力、锚杆轴力",
    "表E": "地下水位、地表竖向位移、分层竖向位移、坑底隆起",
    "表F": "裂缝",
}
FAMILY_UNIT = {"表C": "kPa", "表D": "kN", "表E": "mm", "表F": "mm", "表A": "mm", "表B": "mm"}

METRIC_ALIAS = {
    "wall_internal_force": "围护墙内力", "column_internal_force": "立柱内力",
    "earth_pressure": "土压力", "pore_pressure": "孔隙水压力",
    "support_axial_force": "支撑轴力", "anchor_axial_force": "锚杆轴力",
    "groundwater_level": "地下水位", "surface_settlement": "周边地表竖向位移",
    "soil_layered_vertical_displacement": "土体分层竖向位移", "basal_heave": "坑底隆起",
    "crack_width_building": "裂缝", "crack_width_surface": "裂缝",
    "wall_top_horizontal_displacement": "水平位移", "deep_horizontal_displacement": "深层水平位移",
}

KNOWN_METRICS = (TABLE_C_METRICS | TABLE_D_METRICS | TABLE_E_METRICS | TABLE_F_METRICS
                 | TABLE_AB_METRICS | set(METRIC_ALIAS.keys()))

# 测点号前缀 → 监测项目（用于「附录表式」中**没有监测项目列**时反推）
POINT_PREFIX_METRIC = {
    # 附录 C / D 族
    "CK": "孔隙水压力", "CL": "立柱内力", "CN": "围护墙内力", "CT": "土压力",
    "DM": "锚杆轴力", "DN": "支撑轴力",
    # CD_data 模拟数据集
    "TY": "土压力", "KL": "孔隙水压力", "QN": "围护墙内力", "LZ": "立柱内力",
    "ZL": "支撑轴力", "MG": "锚杆轴力",
    # 附录 E 族
    "EB": "坑底隆起", "ES": "周边地表竖向位移", "EW": "地下水位",
    "SW": "地下水位", "DBC": "周边地表竖向位移", "FC": "土体分层竖向位移", "KB": "坑底隆起",
    # 附录 F
    "F": "裂缝",
    # 附录 A / B（不在处理范围，仅识别以免误判）
    "A-DP": "水平位移", "A-SH": "水平位移", "B-DP": "深层水平位移", "B-SH": "深层水平位移",
}
_PREFIX_ORDER = sorted(POINT_PREFIX_METRIC, key=len, reverse=True)

# sheet 名 → 目标表（当监测项目与点号前缀都推不出时使用）
SHEET_FAMILY_HINT = [
    ("附表A", "表A"), ("附表B", "表B"), ("附表C", "表C"), ("附表D", "表D"),
    ("附表E", "表E"), ("附表F", "表F"),
]

# 「备注」中内嵌的预警等级（附录表式把等级写在备注里）
LEVEL_IN_REMARK_RE = re.compile(r"预警等级\s*[:：]\s*([^；;，,、]+)")
LEVEL_NORMALIZE = {
    "正常": "正常",
    "黄色(需关注)": "黄色预警", "黄色（需关注）": "黄色预警", "黄色预警": "黄色预警", "需关注": "黄色预警",
    "橙色(预警)": "橙色预警", "橙色（预警）": "橙色预警", "橙色预警": "橙色预警", "预警": "橙色预警",
    "红色(报警)": "红色预警", "红色（报警）": "红色预警", "红色预警": "红色预警", "报警": "红色预警",
    "未判定": UNDETERMINED, "未知": UNDETERMINED, "未判定(待复核)": UNDETERMINED,
}

# 页脚/说明行前缀（附录表式中数据区之后的内容，须跳过）
FOOTER_PREFIXES = (
    "工况描述", "简要分析", "当日监测的简要分析", "工程负责人", "监测单位", "第", "结论",
    "·", "•", "一、", "二、", "三、", "四、", "五、", "六、", "七、",
    "内容", "说明", "开挖/施工进展", "监测范围", "检索主题",
)

# 宽表列名形如「土压力 TY-01 (kPa)」：一行 = 一个时刻，一列 = 一个测点
WIDE_COL_RE = re.compile(
    r"^\s*(?P<metric>[^\s()（）]+)\s+(?P<pid>[A-Za-z]{1,8}[-_]?\d{0,5})\s*[（(](?P<unit>[^）)]+)[）)]\s*$"
)

TIME_COL_KEYS = {"时间", "日期", "观测日期", "监测时间", "测量时间",
                 "timestamp", "date", "time", "datetime"}

# 版式锚点（Excel 1-based 行号）
ROW_TITLE = 1
ROW_TIMES = 2
ROW_HEADER = 8
ROW_DATA = 9
N_COL = 9

THIN = Side(style="thin", color="FF999999")
BORDER_ALL = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


# ===========================================================================
# 读取
# ===========================================================================
def _header_hits(cells: list[str]) -> int:
    """统计一行中命中已知列名（长表别名或宽表列名）的个数，用于定位真实表头行。"""
    norm = {re.sub(r"[\s　]+", "", str(c)).lower() for c in cells if str(c).strip()}
    hits = 0
    for aliases in COLUMN_ALIASES.values():
        keys = {re.sub(r"[\s　]+", "", a).lower() for a in aliases}
        if norm & keys:
            hits += 1
    hits += sum(1 for c in cells if _parse_wide_col(c))   # 宽表列名同样计入
    return hits


def _find_header_row(rows: list[list[str]], limit: int = 12) -> int | None:
    """在前 limit 行中寻找真实表头行（命中 ≥2 个已知列名）。"""
    best_idx, best_hits = None, 1
    for i, r in enumerate(rows[:limit]):
        h = _header_hits(r)
        if h > best_hits:
            best_idx, best_hits = i, h
    return best_idx


def _parse_wide_col(name: str) -> tuple[str, str, str] | None:
    """解析宽表列名「土压力 TY-01 (kPa)」→ (监测项目, 测点号, 单位)。"""
    m = WIDE_COL_RE.match(str(name).strip())
    if not m:
        return None
    metric = m.group("metric").strip()
    if metric not in KNOWN_METRICS:
        return None
    return METRIC_ALIAS.get(metric, metric), m.group("pid"), m.group("unit").strip()


def melt_wide(rows: list[dict], headers: list[str]) -> list[dict]:
    """把宽表（一行 = 一个时刻，一列 = 一个测点）融化为长表。"""
    time_key = None
    for h in headers:
        if re.sub(r"[\s　]+", "", str(h)).lower() in TIME_COL_KEYS:
            time_key = h
            break
    if time_key is None and headers:
        time_key = headers[0]

    out: list[dict] = []
    for r in rows:
        ts = r.get(time_key)
        if ts in (None, ""):
            continue
        for h in headers:
            parsed = _parse_wide_col(h)
            if not parsed:
                continue
            metric, pid, unit = parsed
            val = r.get(h)
            if val in (None, "", "—", "-", "－", "/"):
                continue
            out.append({"时间": ts, "点号": pid, "监测项目": metric,
                        "测值": val, "单位": unit})
    return out


def _is_non_data_sheet(title: str) -> bool:
    """判断 xlsx 的某个 sheet 是否为「非记录表」（文字说明页 / 清单页），读取时跳过。"""
    t = str(title or "").strip()
    if t.startswith("附表"):
        return False
    if any(k in t for k in ("超限", "清单", "说明", "汇总")):
        return True
    if "监测日报" in t and not t.startswith("附表"):
        return True
    return False


def _is_footer_row(cells: list) -> bool:
    """附录表式中数据区之后的页脚/说明行（工况描述、简要分析、签署栏、统计条目等）。"""
    first = ""
    for c in cells:
        s = str(c).strip() if c is not None else ""
        if s:
            first = s
            break
    if not first:
        return True
    return first.startswith(FOOTER_PREFIXES)


def read_records(path: Path) -> tuple[list[dict], dict]:
    """读取单个 csv/tsv/xlsx 文件，返回 (原始行字典列表, 读取报告)。

    自动跳过标题行与元数据行，在前 12 行中定位真实表头。
    """
    rep = {"file": str(path), "encoding": None, "delimiter": None,
           "rows": 0, "header_row": None, "errors": []}
    suffix = path.suffix.lower()

    if suffix in (".csv", ".tsv", ".txt"):
        text, enc = None, None
        for e in ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin-1"):
            try:
                text = path.read_text(encoding=e)
                enc = e
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if text is None:
            rep["errors"].append("编码无法识别")
            return [], rep
        rep["encoding"] = enc
        sample = text[:8192]
        delim = max([",", "\t", ";", "|"], key=lambda d: sample.count(d))
        if sample.count(delim) == 0:
            delim = ","
        rep["delimiter"] = delim
        lines = text.splitlines()
        idx = _find_header_row([ln.split(delim) for ln in lines])
        rep["header_row"] = (idx + 1) if idx is not None else 1
        rows = list(csv.DictReader(lines[idx or 0:], delimiter=delim))
    elif suffix in (".xlsx", ".xlsm"):
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        rows = []
        skipped = []
        for ws in wb.worksheets:
            title = ws.title
            if _is_non_data_sheet(title):
                skipped.append(title)
                continue
            data = [[("" if c is None else c) for c in r] for r in ws.iter_rows(values_only=True)]
            if not data:
                continue
            idx = _find_header_row(data)
            if idx is None:
                continue
            rep["header_row"] = idx + 1
            header = [str(c).strip() for c in data[idx]]
            for r in data[idx + 1:]:
                if all(c in (None, "") for c in r):
                    continue
                if _is_footer_row(r):
                    continue
                rec = {header[i]: r[i] for i in range(min(len(header), len(r)))}
                rec["_sheet"] = title
                rows.append(rec)
        wb.close()
        rep["encoding"] = "xlsx"
        rep["delimiter"] = "—"
        if skipped:
            rep["skipped_sheets"] = skipped
    else:
        rep["errors"].append(f"不支持的文件类型：{suffix}")
        return [], rep

    # 宽表检测：列名形如「土压力 TY-01 (kPa)」→ 融化为长表
    if rows:
        headers = [k for k in rows[0].keys() if k]
        wide = [h for h in headers if _parse_wide_col(h)]
        if len(wide) >= 2:
            rows = melt_wide(rows, headers)
            rep["wide_format"] = True
            rep["wide_columns"] = len(wide)

    rep["rows"] = len(rows)
    return rows, rep


def collect_inputs(input_path: Path) -> list[Path]:
    if input_path.is_dir():
        files = []
        for ext in ("*.csv", "*.tsv", "*.xlsx", "*.xlsm", "*.txt"):
            files.extend(sorted(input_path.glob(ext)))
        return [f for f in files if not f.name.startswith("~$")]
    return [input_path]


# ===========================================================================
# 清洗
# ===========================================================================
def build_column_map(headers: list[str]) -> dict[str, str]:
    """把实际列名映射到规范字段名。"""
    norm = {re.sub(r"[\s　]+", "", str(h)).lower(): h for h in headers if h}
    mapping: dict[str, str] = {}
    for field, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            key = re.sub(r"[\s　]+", "", a).lower()
            if key in norm:
                mapping[field] = norm[key]
                break
    return mapping


def parse_time(raw) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace("T", " ").replace("Z", "").strip()
    for f in TIME_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def parse_number(raw) -> float | None:
    if isinstance(raw, (int, float)):
        return float(raw)
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace("，", "")
    if s in ("", "—", "-", "－", "N/A", "NA", "null", "None", "/"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


DIM_DEFAULT_UNIT = {"pressure": "kPa", "force": "kN", "length": "mm"}
DIM_TABLE = {"pressure": UNIT_TO_KPA, "force": UNIT_TO_KN, "length": UNIT_TO_MM}


def norm_unit(raw, target_dim: str) -> tuple[float | None, str | None, str | None]:
    """返回 (换算因子, 规范单位, 错误信息)。"""
    unit = DIM_DEFAULT_UNIT.get(target_dim, "")
    table = DIM_TABLE.get(target_dim, {})
    if raw is None or str(raw).strip() == "":
        return 1.0, unit, "单位缺失，按目标量纲假定"
    key = str(raw).strip().replace(" ", "").lower().replace("℃", "c")
    if key in table:
        return table[key], unit, None
    return None, None, f"单位无法识别或量纲不符：{raw}"


def classify_metric(metric: str) -> tuple[str, int] | None:
    """返回 (目标表, 组号)。`表AB` 表示识别到但不在本 Skill 处理范围。"""
    m = METRIC_ALIAS.get(str(metric).strip(), str(metric).strip())
    if m in TABLE_C_METRICS:
        return "表C", 1
    if m in TABLE_D_METRICS:
        return "表D", (2 if m == "支撑轴力" else 3)
    if m in TABLE_E_METRICS:
        return "表E", 4
    if m in TABLE_F_METRICS:
        return "表F", 5
    if m in TABLE_AB_METRICS:
        return "表AB", 0
    return None


def infer_metric(point_id, sheet_name, metric_raw) -> str | None:
    """附录表式没有「监测项目」列时，用**点号前缀**反推监测项目。

    前缀表见 `POINT_PREFIX_METRIC`（如 `CK-01`→孔隙水压力、`CN-01`→围护墙内力、
    `EB-01`→坑底隆起、`F-01`→裂缝）。推不出则返回 `None`，该行记入待复核。
    """
    if metric_raw not in (None, ""):
        return METRIC_ALIAS.get(str(metric_raw).strip(), str(metric_raw).strip())
    pid = re.sub(r"\s+", "", str(point_id or "")).upper()
    for p in _PREFIX_ORDER:
        if pid.startswith(p.upper()):
            return POINT_PREFIX_METRIC[p]
    return None


def level_from_remark(remark: str) -> str | None:
    """从「备注」中解析内嵌的预警等级（附录表式把等级写在备注里）。"""
    return parse_remark_fields(remark).get("level")


REMARK_WARN_RE = re.compile(r"报警值\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)")
REMARK_WARN_TEXT_RE = re.compile(r"报警值\s*[:：]\s*([^；;]+)")
REMARK_PCT_RE = re.compile(r"占报警值\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)")


def parse_remark_fields(remark) -> dict:
    """从「备注」中解析附录表式内嵌的字段。

    形如 `预警等级：黄色(需关注)；报警值：112 kN·m / kPa；占报警值：116.1%；超报警值：是`
    → `{"level": "黄色预警", "warn": 112.0, "pct": 116.1}`
    """
    out: dict = {}
    if not remark:
        return out
    s = str(remark)
    m = LEVEL_IN_REMARK_RE.search(s)
    if m:
        raw = m.group(1).strip()
        out["level"] = LEVEL_NORMALIZE.get(raw, raw)
    m = REMARK_WARN_RE.search(s)
    if m:
        try:
            out["warn"] = float(m.group(1))
        except ValueError:
            pass
    m = REMARK_WARN_TEXT_RE.search(s)
    if m:
        out["warn_text"] = m.group(1).strip()
    m = REMARK_PCT_RE.search(s)
    if m:
        try:
            out["pct"] = float(m.group(1))
        except ValueError:
            pass
    return out


# ===========================================================================
# 组装
# ===========================================================================
def _row_getter(row: dict):
    """按行构建取值器：把该行自身的列名归一后，按别名表取值。

    这样同一工作簿里**不同 sheet 用不同列名**（如「点号」与「孔号(点号)」）也能正确取到。
    """
    norm = {re.sub(r"[\s　]+", "", str(k)).lower(): v for k, v in row.items() if k}

    def get(field):
        for a in COLUMN_ALIASES.get(field, []):
            key = re.sub(r"[\s　]+", "", a).lower()
            if key in norm:
                return norm[key]
        return None

    return get


def normalize_rows(raw_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """清洗为统一记录。返回 (有效记录, 待复核条目)。

    支持两种来源形态：
    - **长表 / 宽表**（有「监测项目」列）；
    - **GB 50497 附录表式**（表头在第 6 行、组号点号在末尾、**无监测项目列**、
      预警等级内嵌在「备注」里）—— 监测项目由**点号前缀**反推。
    """
    if not raw_rows:
        return [], []
    records: list[dict] = []
    review: list[dict] = []

    for i, r in enumerate(raw_rows, start=1):
        get = _row_getter(r)

        pid = str(get("point_id") or "").strip()
        metric_raw = str(get("metric") or "").strip()
        sheet_name = str(r.get("_sheet") or "")
        ts_raw = get("timestamp")
        ts = parse_time(ts_raw)
        val = parse_number(get("value"))
        depth = parse_number(get("depth"))
        remark = str(get("remark") or "").strip()

        if not pid:
            review.append({"row": i, "point_id": "", "reason": "测点号缺失"})
            continue

        metric = infer_metric(pid, sheet_name, metric_raw)
        if metric is None:
            review.append({"row": i, "point_id": pid,
                           "reason": f"监测项目无法识别（无监测项目列且点号前缀未匹配）：{pid}"})
            continue
        route = classify_metric(metric)
        if route is None:
            review.append({"row": i, "point_id": pid, "reason": f"监测项目无法识别：{metric}"})
            continue
        sheet, group = route
        if sheet == "表AB":
            review.append({"row": i, "point_id": pid,
                           "reason": f"监测项目不在本 Skill 处理范围（表 A / 表 B）：{metric}"})
            continue

        dim = {"表C": "pressure", "表D": "force"}.get(sheet, "length")

        change_in = parse_number(get("change"))
        cum_in = parse_number(get("cumulative"))
        rate_in = parse_number(get("rate"))
        level_col = get("level")
        level_in = (str(level_col).strip() if level_col not in (None, "") else None)
        remark_fields = parse_remark_fields(remark)
        if not level_in:
            level_in = remark_fields.get("level")

        base = dict(
            pid=pid, metric=metric, sheet=sheet, group=group, ts=ts,
            value=val, depth=depth, remark=remark, seq=i,
            sheet_name=sheet_name, source=str(r.get("_source") or ""),
            prev_in=parse_number(get("prev")), cum_in=cum_in,
            change_in=change_in, rate_in=rate_in, level_in=level_in,
            warn_in=remark_fields.get("warn"), pct_in=remark_fields.get("pct"),
            warn_text_in=remark_fields.get("warn_text"),
            group_in=(parse_number(get("group"))),
            group_raw=(str(get("group")).strip() if get("group") not in (None, "") else None),
            form=str(get("form") or "").strip(),
            length=parse_number(get("length")), width=parse_number(get("width")),
            elev_init=parse_number(get("elev_init")),
            elev_now=parse_number(get("elev_now")),
            elev_prev=parse_number(get("elev_prev")),
        )

        if ts_raw not in (None, "") and ts is None:
            review.append({"row": i, "point_id": pid, "reason": "时间无法解析"})
            records.append(dict(base, unit=None, valid=False))
            continue

        factor, unit, uerr = norm_unit(get("unit"), dim)
        if factor is None:
            review.append({"row": i, "point_id": pid, "reason": uerr})
            records.append(dict(base, unit=None, valid=False))
            continue

        if val is not None:
            val = round(val * factor, 4)
        for k in ("cum_in", "change_in", "rate_in"):
            if base[k] is not None:
                base[k] = round(base[k] * factor, 4)

        if val is None and cum_in is None and change_in is None:
            review.append({"row": i, "point_id": pid, "reason": "测值缺失或非数值"})
            records.append(dict(base, value=None, unit=unit, valid=False))
            continue

        records.append(dict(base, value=val, unit=unit, valid=True))

    records.sort(key=lambda x: (x["pid"], x["ts"] or datetime.min, x.get("seq", 0)))
    return records, review


def aggregate_daily(records: list[dict]) -> list[dict]:
    """按 (测点, 日期) 聚合，取当日**最后一次**观测（日报表以「日」为最小期次）。

    **同时记录当日极值与观测条数**（`day_min` / `day_max` / `day_count`）：
    只取末次读数会掩盖日内变化，极值供「汇总」页做**日内极值提示**。
    """
    best: dict[tuple, dict] = {}
    agg: dict[tuple, list] = defaultdict(list)
    for r in records:
        if not r.get("valid") or r.get("ts") is None or r.get("value") is None:
            continue
        key = (r.get("source", ""), r["pid"], r["ts"].date())
        agg[key].append(float(r["value"]))
        cur = best.get(key)
        if cur is None or r["ts"] > cur["ts"]:
            best[key] = r
    out = []
    for key, rec in best.items():
        vals = agg[key]
        out.append(dict(rec, day_min=min(vals), day_max=max(vals), day_count=len(vals)))
    return sorted(out, key=lambda x: (x["sheet"], x["group"], x["pid"], x["ts"]))


def _point_series(rows: list[dict]) -> dict[tuple, list[dict]]:
    """按 (来源, sheet, 点号) 分组并按时间升序，供速率口径判据取序列。"""
    by: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        by[(r.get("source", ""), r.get("sheet_name", ""), r["pid"])].append(r)
    for k in by:
        by[k].sort(key=lambda x: (x["ts"] or datetime.min, x.get("seq", 0)))
    return by


def _tail_of(seq: list[dict], upto: int, tail: int = 8) -> tuple[list, list]:
    """截止第 upto 期（含）的最近 tail 期 → (本次变化序列, 变化速率序列)。

    输入自带 change/rate 时以输入为准；否则按期次派生。`None` 表示该期无法计算，
    速率口径判据遇到 `None` 会拒绝判「连续」/「突变」，避免跨缺口误判。
    """
    changes: list = []
    rates: list = []
    for i in range(max(0, upto - tail + 1), upto + 1):
        cur = seq[i]
        prev = seq[i - 1] if i > 0 else None
        v, pv = cur.get("value"), (prev or {}).get("value")
        ch = cur.get("change_in")
        if ch is None and v is not None and pv is not None:
            ch = round(v - pv, 4)
        rt = cur.get("rate_in")
        if rt is None and ch is not None and prev and cur.get("ts") and prev.get("ts"):
            dt = (cur["ts"] - prev["ts"]).total_seconds() / 86400.0
            rt = round(ch / dt, 4) if dt else None
        changes.append(ch)
        rates.append(rt)
    return changes, rates


def _interval_minutes_of(seq: list[dict], upto: int):
    if upto <= 0:
        return None
    a, b = seq[upto - 1].get("ts"), seq[upto].get("ts")
    if a is None or b is None:
        return None
    return (b - a).total_seconds() / 60.0


def build_period_rows(records: list[dict], target_date=None) -> tuple[list[dict], object]:
    """按日聚合后选出目标期，派生「上次测值 / 本次变化 / 累计变化」。

    - **基准值** = 该测点**最早一期**的测值（用于累计变化）
    - **上次测值** = 目标期的**前一期**（用于本次变化）
    """
    daily = aggregate_daily(records)
    if not daily:
        return [], None

    first: dict[tuple, float] = {}
    for r in daily:
        first.setdefault((r.get("source", ""), r["pid"]), r["value"])

    dates = sorted({r["ts"].date() for r in daily})
    tgt = target_date or dates[-1]
    if tgt not in dates:
        tgt = dates[-1]
    idx = dates.index(tgt)
    prev_date = dates[idx - 1] if idx > 0 else None

    lookup = {(r.get("source", ""), r["pid"], r["ts"].date()): r for r in daily}
    series = _point_series(daily)
    idx_of = {id(r): i for s in series.values() for i, r in enumerate(s)}
    rows: list[dict] = []
    for r in daily:
        if r["ts"].date() != tgt:
            continue
        skey = (r.get("source", ""), r["pid"])
        prev_rec = lookup.get((skey[0], skey[1], prev_date)) if prev_date else None
        prev = prev_rec["value"] if prev_rec else r["value"]
        base = first.get(skey)
        cur = r["value"]
        seq = series.get((r.get("source", ""), r.get("sheet_name", ""), r["pid"]), [r])
        i = idx_of.get(id(r), len(seq) - 1)
        changes, rates = _tail_of(seq, i)
        rows.append(dict(
            r,
            prev=prev,
            change=round(cur - prev, 2) if cur is not None and prev is not None else None,
            cumulative=round(cur - base, 2) if cur is not None and base is not None else None,
            series_changes=changes, series_rates=rates,
            interval_minutes=_interval_minutes_of(seq, i),
            day_min=r.get("day_min"), day_max=r.get("day_max"),
        ))
    rows.sort(key=lambda x: (x["sheet"], x["group"], x["pid"]))
    return rows, tgt


def build_interval_rows(records: list[dict], target_date=None) -> tuple[list[dict], object]:
    """按测点取「末期 vs 相邻上一期」，派生 本次变化量 / 变化速率 / 累计变化量。

    与 `build_period_rows`（按日聚合）不同，本函数**保留原始采样间隔**：

    - 本次变化量 = 末期测值 − 相邻上一期测值
    - 变化速率   = 本次变化量 ÷ 间隔天数（d）
    - 累计变化量 = 末期测值 − 该测点首期测值

    这与「判定汇总表」样例的口径一致（5 分钟采样 → 速率 ≈ 变化量 × 288）。
    """
    by: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        if r.get("valid") and r.get("ts") is not None and r.get("value") is not None:
            by[(r.get("source", ""), r["pid"])].append(r)

    rows: list[dict] = []
    dates: set = set()
    for _skey, seq in by.items():
        seq.sort(key=lambda x: x["ts"])
        dates.add(seq[-1]["ts"].date())
        last_i = len(seq) - 1
        if target_date is not None:
            cand = [i for i, x in enumerate(seq) if x["ts"].date() == target_date]
            if not cand:
                continue
            last_i = cand[-1]
        last, first = seq[last_i], seq[0]
        prev = seq[last_i - 1] if last_i > 0 else None
        dt = (last["ts"] - prev["ts"]).total_seconds() / 86400.0 if prev else None
        change = (last["value"] - prev["value"]) if prev else None
        rate = (change / dt) if (change is not None and dt) else None
        cum = last["value"] - first["value"]
        s_changes, s_rates = _tail_of(seq, last_i)
        rows.append(dict(
            last,
            prev=prev["value"] if prev else None,
            change=round(change, 4) if change is not None else None,
            rate=round(rate, 4) if rate is not None else None,
            cumulative=round(cum, 4),
            dt_days=dt, first_value=first["value"],
            interval_minutes=round(dt * 1440, 3) if dt else None,
            series_changes=s_changes, series_rates=s_rates,
        ))
    rows.sort(key=lambda x: (x["sheet"], x["group"], x["pid"]))
    tgt = target_date or (max(dates) if dates else None)
    return rows, tgt


FAMILY_ORDER = {"表A": 0, "表B": 1, "表C": 2, "表D": 3, "表E": 4, "表F": 5}


def build_appendix_rows(records: list[dict], periods: int = 3, target_date=None) -> list[dict]:
    """为**附录表式**（`--layout af`）组装行。

    与按日聚合的 `build_period_rows` 不同：

    - 分组键为 `(来源文件, sheet 名, 点号)`，**保留文件内出现顺序**；
    - 组内有可解析时间 → 先按日聚合，再取**最后 N 期**；
    - 组内无时间（附录 E / F 常不带日期列）→ 直接取**最后 N 条**；
    - 输入已自带 `本次变化 / 累计变化 / 变化速率` 时**以输入为准**，否则按期次派生。
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        if r.get("valid"):
            groups[(r.get("source", ""), r.get("sheet_name", ""), r["pid"])].append(r)

    out: list[dict] = []
    for _key, seq in groups.items():
        seq.sort(key=lambda x: (x["ts"] or datetime.min, x.get("seq", 0)))
        has_time = any(x.get("ts") is not None for x in seq)
        if has_time:
            best: dict = {}
            for x in seq:
                if x["ts"] is not None:
                    best[x["ts"].date()] = x
            picks = [best[d] for d in sorted(best)]
        else:
            picks = list(seq)
        if target_date is not None and has_time:
            win = [x for x in picks if x["ts"].date() == target_date]
            picks = win or picks[-max(periods, 1):]
        else:
            picks = picks[-max(periods, 1):]

        base_val = next((x["value"] for x in seq if x["value"] is not None), None)
        pos = {id(x): i for i, x in enumerate(seq)}
        for x in picks:
            i = pos[id(x)]
            prev = seq[i - 1] if i > 0 else None
            value = x.get("value")
            change = x.get("change_in")
            if change is None and value is not None and prev and prev.get("value") is not None:
                change = round(value - prev["value"], 4)
            cum = x.get("cum_in")
            if cum is None and value is not None and base_val is not None:
                cum = round(value - base_val, 4)
            rate = x.get("rate_in")
            if rate is None and change is not None and prev and x.get("ts") and prev.get("ts"):
                dt = (x["ts"] - prev["ts"]).total_seconds() / 86400.0
                rate = round(change / dt, 4) if dt else None
            prev_value = (prev or {}).get("value")
            if prev_value is None:
                # 首期：上次测值等于本期（与「示例汇总表」口径一致）
                prev_value = x.get("prev_in")
            if prev_value is None:
                prev_value = value
            s_changes, s_rates = _tail_of(seq, i)
            out.append(dict(
                x, prev_value=prev_value,
                change=change, cumulative=cum, rate=rate,
                first_value=base_val,
                series_changes=s_changes, series_rates=s_rates,
                interval_minutes=_interval_minutes_of(seq, i),
                group_out=(x.get("group_in") if x.get("group_in") is not None else None),
            ))

    out.sort(key=lambda x: (FAMILY_ORDER.get(x.get("sheet"), 9), str(x["pid"]),
                            x.get("ts") or datetime.min, x.get("seq", 0)))
    return out


def derive(records: list[dict]) -> list[dict]:
    """按测点时序派生 上次测值 / 本次变化 / 累计变化。"""
    by_pid: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_pid[r["pid"]].append(r)

    out: list[dict] = []
    for pid, seq in by_pid.items():
        seq.sort(key=lambda x: x["ts"] or datetime.min)
        baseline = next((x["value"] for x in seq if x["value"] is not None), None)
        prev_val: float | None = None
        for r in seq:
            cur = r["value"]
            if r.get("prev_in") is not None:
                prev = r["prev_in"]
            elif prev_val is not None:
                prev = prev_val
            else:
                prev = cur
            if r.get("cum_in") is not None:
                cum = r["cum_in"]
            elif cur is not None and baseline is not None:
                cum = round(cur - baseline, 2)
            else:
                cum = None
            change = None if (cur is None or prev is None) else round(cur - prev, 2)
            r = dict(r, prev=prev, change=change, cumulative=cum)
            out.append(r)
            if cur is not None:
                prev_val = cur
    out.sort(key=lambda x: (x["sheet"], x["group"], x["pid"], x["ts"] or datetime.min))
    return out


# ===========================================================================
# 预警等级
# ===========================================================================
def grade(rec: dict, limits: dict | None,
          *, rate_rules_enabled: bool = True,
          sudden_factor: float = 3.0,
          sudden_ack: bool = False) -> tuple[str, str]:
    """返回 (预警等级, 判定理由)。

    本 Skill **不做风险判定**（判定由专门模块负责）。优先级：
    1) 输入数据自带「预警等级」→ **原样引用**为基线；
    2) 显式提供 `--limits` → 按累计值 / 变化量限值判定（**可选增强**）；
    3) 否则 → `未判定(待复核)`。

    在 1)、2) 之上**叠加**速率口径判据（GB 50497-2019 第 8.0.3 条「连续 3 次超 70%」、
    第 8.0.9-1 条「突然明显增大」）—— **只升不降**，并在理由中注明依据条款。
    """
    extra_reason = ""
    lvl: str | None = None
    if rec.get("level_in"):
        lvl = str(rec["level_in"]).strip()
        extra_reason = "原样引用输入数据填报的预警等级"
    elif not rec.get("valid"):
        lvl = UNDETERMINED
        extra_reason = "数据缺失或不可用，不作判定，需补充或复核原始记录"
    elif not limits:
        lvl = UNDETERMINED
        extra_reason = "阈值未配置，不作超限判定，需项目专项监测方案确认"
    else:
        spec = limits.get(rec["metric"]) or limits.get("*")
        if not spec:
            lvl = UNDETERMINED
            extra_reason = "阈值未配置，不作超限判定，需项目专项监测方案确认"

    reasons: list[str] = []
    if lvl is None:
        spec = limits.get(rec["metric"]) or limits.get("*")
        warn = spec.get("warn")       # 报警值
        ctrl = spec.get("control")    # 控制值
        rate = spec.get("rate")       # 速率限值（/期）
        unit = rec.get("unit") or ""
        cum = rec.get("cumulative")
        chg = rec.get("change")

        lvl = "正常"

        def bump(target: str) -> None:
            nonlocal lvl
            if LEVELS.index(target) > LEVELS.index(lvl):
                lvl = target

        if cum is not None and ctrl is not None and abs(cum) >= ctrl:
            bump("红色预警")
            reasons.append(f"累计量 {abs(cum):.2f} {unit} 达到/超过控制值 {ctrl:.2f} {unit}")
        elif cum is not None and warn is not None and abs(cum) >= warn:
            bump("橙色预警")
            reasons.append(f"累计量 {abs(cum):.2f} {unit} 达到/超过报警值 {warn:.2f} {unit}")
        elif cum is not None and warn is not None and abs(cum) >= warn * 0.7:
            bump("黄色预警")
            reasons.append(f"累计量 {abs(cum):.2f} {unit} 达到报警值的 70%（{warn * 0.7:.2f} {unit}）")

        if rate is not None and chg is not None and abs(chg) >= rate:
            bump("橙色预警")
            reasons.append(f"本期变化 {abs(chg):.2f} {unit} 达到/超过变化限值 {rate:.2f} {unit}")

        if not reasons:
            reasons.append("各项指标未达预警线")

    # 速率口径判据叠加（只升不降）
    if rate_rules_enabled and lvl in LEVELS:
        spec = (limits or {}).get(rec["metric"]) or (limits or {}).get("*") or {}
        rr = rate_rules.evaluate_series(
            rec.get("series_changes"), rec.get("series_rates"), spec.get("rate"),
            enable=True, sudden_factor=sudden_factor,
            interval_minutes=rec.get("interval_minutes"), sudden_ack=sudden_ack)
        if rr["level"] and LEVELS.index(rr["level"]) > LEVELS.index(lvl):
            lvl = rr["level"]
        if rr["reasons"]:
            reasons.extend(rr["reasons"])
            clauses = "；".join(rr["clauses"])
            if clauses:
                reasons.append(f"依据 {clauses}")
        if rr.get("sudden_blocked"):
            reasons.append("突变判据未确认，已停用（" + rr["sudden_blocked"] +
                           "；加 --ack-sudden-factor 后启用）")

    return lvl, "；".join([r for r in [extra_reason] + reasons if r])


# ===========================================================================
# 写表
# ===========================================================================
def style_sheet(ws, n_data_rows: int, sheet_title: str, header: list[str]) -> None:
    ws.cell(row=ROW_TITLE, column=1, value=sheet_title)
    ws.merge_cells(start_row=ROW_TITLE, start_column=1, end_row=ROW_TITLE, end_column=N_COL)
    c = ws.cell(row=ROW_TITLE, column=1)
    c.font = Font(bold=True, size=14)
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[ROW_TITLE].height = 30

    for ci, name in enumerate(header, start=1):
        h = ws.cell(row=ROW_HEADER, column=ci, value=name)
        h.font = Font(bold=True, size=10)
        h.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        h.border = BORDER_ALL

    for ci, w in enumerate([7, 12, 10, 16, 16, 16, 16, 15, 34], start=1):
        ws.column_dimensions[get_column_letter(ci)].width = w

    last = ROW_DATA + max(n_data_rows, 1) - 1
    for r in range(ROW_DATA, last + 1):
        for ci in range(1, N_COL + 1):
            cell = ws.cell(row=r, column=ci)
            cell.border = BORDER_ALL
            if cell.font.size is None:
                cell.font = Font(size=10)
            cell.alignment = Alignment(horizontal="center" if ci in (1, 2, 3, 5, 8) else "left",
                                       vertical="center", wrap_text=(ci == 9))
    ws.freeze_panes = f"A{ROW_DATA}"


def write_table_sheet(ws, sheet_key: str, title: str, recs: list[dict],
                      limits: dict | None, meta: dict, *,
                      rate_rules_enabled: bool = True,
                      sudden_factor: float = 3.0,
                      sudden_ack: bool = False) -> list[dict]:
    unit = "kPa" if sheet_key == "表C" else "kN"
    header = ["组号", "点号", "深度(m)", f"本次测值({unit})", f"上次测值({unit})",
              f"本次变化({unit})", f"累计变化({unit})", "预警等级", "备注"]

    ws.cell(row=ROW_TIMES, column=1, value=f"第（{meta.get('times', 1)}）次")
    ws.cell(row=ROW_TIMES + 1, column=1,
            value=(f"工程名称：{meta.get('project', '＿＿＿＿')}　　　"
                   f"报表编号：{meta.get('report_no', '＿＿＿＿')}　　　"
                   f"天气：{meta.get('weather', '＿＿＿＿')}"))
    ws.cell(row=ROW_TIMES + 2, column=1,
            value=(f"观测者：{meta.get('observer', '＿＿＿＿')}　　　"
                   f"计算者：{meta.get('calculator', '＿＿＿＿')}　　　"
                   f"校核者：{meta.get('checker', '＿＿＿＿')}"))
    ws.cell(row=ROW_TIMES + 3, column=1,
            value=(f"仪器型号：{meta.get('instrument_model', '＿＿＿＿')}　　　"
                   f"仪器编号：{meta.get('instrument_no', '＿＿＿＿')}　　　"
                   f"检定有效期：{meta.get('instrument_valid', '＿＿＿＿')}"))
    ws.cell(row=ROW_TIMES + 4, column=1,
            value=(f"本次监测时间：{meta.get('current_time', '＿＿＿＿')}　　　"
                   f"上次监测时间：{meta.get('previous_time', '＿＿＿＿')}"))
    for r in range(ROW_TIMES, ROW_TIMES + 5):
        cc = ws.cell(row=r, column=1)
        cc.font = Font(size=10)
        cc.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    style_sheet(ws, len(recs), title, header)

    alerts: list[dict] = []
    review: list[dict] = []
    row = ROW_DATA
    for rec in recs:
        lvl, reason = grade(rec, limits, rate_rules_enabled=rate_rules_enabled,
                            sudden_factor=sudden_factor, sudden_ack=sudden_ack)
        ws.cell(row=row, column=1, value=rec["group"])
        ws.cell(row=row, column=2, value=rec["pid"])
        ws.cell(row=row, column=3,
                value=rec["depth"] if rec["depth"] is not None else "—")
        for off, key in ((4, "value"), (5, "prev"), (6, "change"), (7, "cumulative")):
            v = rec.get(key)
            cell = ws.cell(row=row, column=off, value=v if v is not None else "—")
            if isinstance(v, (int, float)):
                cell.number_format = "0.00"
        ws.cell(row=row, column=8, value=lvl)

        notes = []
        if rec.get("remark"):
            notes.append(rec["remark"])
        if rec.get("prev_in") is not None and rec.get("value") is not None and rec.get("change") is not None:
            diff = abs(rec["prev_in"] - (rec["value"] - rec["change"]))
            if diff > 0.5:
                notes.append(f"本次变化 {rec['change']:.1f} 与测值差 {rec['value'] - rec['prev_in']:.1f} 不一致，需核对原始记录")
        if lvl == UNDETERMINED and not notes:
            notes.append(reason)
        ws.cell(row=row, column=9, value="；".join(notes))

        entry = dict(sheet=sheet_key, point=rec["pid"], metric=rec["metric"], level=lvl,
                     cumulative=rec.get("cumulative"), unit=unit,
                     change=rec.get("change"), reason=reason, depth=rec.get("depth"))
        if lvl in ("黄色预警", "橙色预警", "红色预警"):
            alerts.append(entry)
        if lvl == UNDETERMINED:
            review.append(entry)
        row += 1

    # 页脚区
    foot = row + 1
    ws.cell(row=foot, column=1, value=f"工况描述：{meta.get('work_condition', '＿＿＿＿')}")
    ws.merge_cells(start_row=foot, start_column=1, end_row=foot, end_column=N_COL)
    ws.cell(row=foot + 1, column=1, value=f"简要分析及判断性结论：{meta.get('analysis', '＿＿＿＿')}")
    ws.merge_cells(start_row=foot + 1, start_column=1, end_row=foot + 1, end_column=N_COL)
    ws.cell(row=foot + 3, column=1,
            value="工程负责人：＿＿＿＿　　　　　监测单位：＿＿＿＿　　　　　第 　 页 共 　 页")
    ws.merge_cells(start_row=foot + 3, start_column=1, end_row=foot + 3, end_column=N_COL)
    ws.cell(row=foot + 4, column=1,
            value="编制：＿＿＿＿　　　　　审核：＿＿＿＿　　　　　签发：＿＿＿＿（留空待签，不得代填）")
    ws.merge_cells(start_row=foot + 4, start_column=1, end_row=foot + 4, end_column=N_COL)
    for r in (foot, foot + 1, foot + 3, foot + 4):
        cc = ws.cell(row=r, column=1)
        cc.font = Font(size=10)
        cc.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
    ws.row_dimensions[foot + 1].height = 60

    return alerts, review


def intraday_flags(period_rows: list[dict]) -> list[dict]:
    """**日内极值提示**：只取末次读数会掩盖日内变化。

    当某测点当日观测的**极值摆动**（`day_max − day_min`）显著大于本期变化量
    （> 2 倍）时，说明日内出现了末次读数看不到的波动，列出以便人工复核。
    """
    flags: list[dict] = []
    for r in period_rows:
        lo, hi = r.get("day_min"), r.get("day_max")
        if lo is None or hi is None:
            continue
        span = abs(float(hi) - float(lo))
        if span <= 0:
            continue
        chg = r.get("change")
        base = abs(float(chg)) if chg is not None else 0.0
        if span > 2 * base:
            flags.append({"point": r["pid"], "metric": r["metric"], "sheet": r["sheet"],
                          "unit": r.get("unit") or "", "span": round(span, 3),
                          "change": round(base, 3), "n": r.get("day_count")})
    flags.sort(key=lambda x: -x["span"])
    return flags


def write_summary_sheet(ws, table_rows: list[dict], alerts: list[dict],
                        review: list[dict], meta: dict,
                        intraday: list[dict] | None = None) -> None:
    ws.cell(row=1, column=1, value=f"{meta.get('project', '××工程')}监测数据汇总表（草稿）")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=11)
    ws.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="center")

    ws.cell(row=2, column=1,
            value=f"第（{meta.get('times', 1)}）次　　报表编号：{meta.get('report_no', '＿＿＿＿')}　　"
                  f"天气：{meta.get('weather', '＿＿＿＿')}")
    ws.cell(row=3, column=1,
            value=f"本次监测时间：{meta.get('current_time', '＿＿＿＿')}　　"
                  f"上次监测时间：{meta.get('previous_time', '＿＿＿＿')}　　"
                  f"观测者：{meta.get('observer', '＿＿＿＿')}　　计算者：{meta.get('calculator', '＿＿＿＿')}　　"
                  f"校核者：{meta.get('checker', '＿＿＿＿')}")
    ws.cell(row=4, column=1,
            value=f"数据来源：{meta.get('source', '用户上传监测数据')}；"
                  f"口径：按 GB 50497-2019 附录 C/D 表式整理；未配置阈值的测点不作判定")

    ws.cell(row=6, column=1, value="一、各类监测数据结果汇总（按附录表式分类）")
    ws.cell(row=6, column=1).font = Font(bold=True, size=11)

    hdr = ["表式", "测项", "测点数", "正常", "黄色预警", "橙色预警", "红色预警", "未判定",
           "最大|累计量|", "最大|变化速率|", "单位"]
    for ci, h in enumerate(hdr, start=1):
        c = ws.cell(row=7, column=ci, value=h)
        c.font = Font(bold=True, size=10)
        c.alignment = Alignment(horizontal="center", wrap_text=True)
        c.border = BORDER_ALL

    r = 8
    for tr in table_rows:
        for ci, v in enumerate([tr["sheet"], tr["metric"], tr["points"], tr["正常"],
                                tr["黄色预警"], tr["橙色预警"], tr["红色预警"], tr["未判定"],
                                tr["max_cum"], tr["max_change"], tr["unit"]], start=1):
            c = ws.cell(row=r, column=ci, value=v)
            c.border = BORDER_ALL
            c.font = Font(size=10)
        r += 1
    tot = [ "合计", "", sum(t["points"] for t in table_rows),
            sum(t["正常"] for t in table_rows), sum(t["黄色预警"] for t in table_rows),
            sum(t["橙色预警"] for t in table_rows), sum(t["红色预警"] for t in table_rows),
            sum(t["未判定"] for t in table_rows), "", "", "" ]
    for ci, v in enumerate(tot, start=1):
        c = ws.cell(row=r, column=ci, value=v)
        c.border = BORDER_ALL
        c.font = Font(bold=True, size=10)

    r += 2
    ws.cell(row=r, column=1, value="二、超限测点清单（预警信息，按等级排序，便于优先核查）")
    ws.cell(row=r, column=1).font = Font(bold=True, size=11)
    r += 1
    for ci, h in enumerate(["测点", "表式", "预警等级", "累计量", "单位", "变化速率", "判定理由"], start=1):
        c = ws.cell(row=r, column=ci, value=h)
        c.font = Font(bold=True, size=10)
        c.border = BORDER_ALL
    r += 1
    order = {"红色预警": 0, "橙色预警": 1, "黄色预警": 2}
    for a in sorted(alerts, key=lambda x: order.get(x["level"], 9)):
        vals = [a["point"], a["sheet"], a["level"],
                a["cumulative"] if a["cumulative"] is not None else "—", a["unit"],
                a["change"] if a["change"] is not None else "—", a["reason"]]
        for ci, v in enumerate(vals, start=1):
            c = ws.cell(row=r, column=ci, value=v)
            c.border = BORDER_ALL
            c.font = Font(size=10)
        r += 1
    if not alerts:
        ws.cell(row=r, column=1, value="（本期无超限测点）").font = Font(size=10)
        r += 1
    if any(a["level"] == "红色预警" for a in alerts):
        ws.cell(row=r, column=1,
                value="▲ 存在红色预警测点：预警正式发布与工程处置须经人工确认后按既有责任流程执行，本表不作发布。")
        ws.cell(row=r, column=1).font = Font(size=10)
        r += 1

    r += 1
    ws.cell(row=r, column=1, value="二·补充、日内极值提示（只取末次读数可能掩盖日内变化）")
    ws.cell(row=r, column=1).font = Font(bold=True, size=11)
    r += 1
    if intraday:
        for ci, h in enumerate(["测点", "表式", "测项", "日内极值摆动", "单位", "本期变化量", "当日观测条数"], start=1):
            c = ws.cell(row=r, column=ci, value=h)
            c.font = Font(bold=True, size=10)
            c.border = BORDER_ALL
        r += 1
        for f in intraday[:30]:
            for ci, v in enumerate([f["point"], f["sheet"], f["metric"], f["span"],
                                    f["unit"], f["change"], f["n"]], start=1):
                c = ws.cell(row=r, column=ci, value=v)
                c.font = Font(size=10)
                c.border = BORDER_ALL
            r += 1
        if len(intraday) > 30:
            ws.cell(row=r, column=1, value=f"（仅列摆动最大的 30 项，共 {len(intraday)} 项）").font = Font(size=10)
            r += 1
        ws.cell(row=r, column=1,
                value="▲ 上述测点当日观测的极值摆动显著大于「当日末次 − 前日末次」，"
                      "日报口径的本次变化量可能低估日内实际波动，须人工复核原始时序。").font = Font(size=10)
        r += 1
    else:
        ws.cell(row=r, column=1, value="（本期无显著日内极值摆动）").font = Font(size=10)
        r += 1

    r += 1
    ws.cell(row=r, column=1, value="三、待复核事项")
    ws.cell(row=r, column=1).font = Font(bold=True, size=11)
    r += 1
    # 同因同类合并计数，避免成百上千条刷屏
    grouped: "OrderedDict[tuple, list[str]]" = OrderedDict()
    for e in review:
        reason = str(e.get("reason", "")).strip()
        key = (reason.split("：")[0], reason)
        grouped.setdefault(key, []).append(str(e.get("point") or e.get("point_id") or "（未识别测点）"))
    if not grouped:
        ws.cell(row=r, column=1, value="（本期无待复核事项）").font = Font(size=10)
        r += 1
    for (_k, reason), names in grouped.items():
        head = f"{reason}　—— 共 {len(names)} 项"
        ws.cell(row=r, column=1, value=head).font = Font(size=10)
        r += 1
        if len(names) <= 12:
            ws.cell(row=r, column=1, value="　涉及：" + "、".join(names)).font = Font(size=10)
        else:
            ws.cell(row=r, column=1,
                    value="　涉及：" + "、".join(names[:12]) + f" … 等 {len(names)} 项").font = Font(size=10)
        r += 1

    r += 1
    for title, key in (("四、工况描述", "work_condition"),
                       ("五、简要分析及判断性结论", "analysis")):
        ws.cell(row=r, column=1, value=title).font = Font(bold=True, size=11)
        r += 1
        ws.cell(row=r, column=1, value=meta.get(key, "＿＿＿＿")).font = Font(size=10)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=11)
        ws.cell(row=r, column=1).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 60
        r += 2

    ws.cell(row=r, column=1, value="六、签署").font = Font(bold=True, size=11)
    r += 1
    ws.cell(row=r, column=1, value="编制：＿＿＿＿　　　　审核：＿＿＿＿　　　　签发：＿＿＿＿（留空待签，不得代填）")
    r += 2

    ws.cell(row=r, column=1, value="七、说明").font = Font(bold=True, size=11)
    notes = [
        "1. 本表为监测数据分析与日报编制的辅助材料，由责任人员复核后进入签发、归档流程，不替代责任单位出具的正式监测报告。",
        "2. 表式以 GB 50497-2019 附录 A~G 为基准，格式修改：①各表增加“预警等级”列；②表 B 增加“点号”列；③超限与待复核信息写入“备注”列并在本页集中列示。",
        "3. 指标值原样引用填报数据或确定性计算输出；判定阈值以项目专项监测方案为准，未配置阈值的一律不作判定。",
        "4. 系统仅完成异常识别与提示；红色预警须经人工确认，正式预警发布与工程处置沿用既有责任流程。",
        "5. 表中“—”表示该字段数据源未提供或该期数据缺失，未作插值填补；标 ＿＿＿＿ 的字段须由填报人补充。",
        "6. 速率口径判据：" + (meta.get("rate_rules_note") or
                              "见命令行 --rate-rules / --sudden-factor / --ack-sudden-factor 说明。"),
    ]
    for n in notes:
        r += 1
        ws.cell(row=r, column=1, value=n).font = Font(size=10)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=11)
        ws.cell(row=r, column=1).alignment = Alignment(wrap_text=True, vertical="top")

    for ci, w in enumerate([14, 14, 8, 8, 10, 10, 10, 10, 14, 14, 8], start=1):
        ws.column_dimensions[get_column_letter(ci)].width = w


# ===========================================================================
# 主流程
# ===========================================================================
def summarize_table(recs: list[dict], limits: dict | None, *,
                    rate_rules_enabled: bool = True,
                    sudden_factor: float = 3.0,
                    sudden_ack: bool = False) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in recs:
        groups[(r["sheet"], r["metric"])].append(r)

    rows = []
    for (sheet, metric), items in sorted(groups.items()):
        lv = defaultdict(int)
        cums, chgs = [], []
        for it in items:
            g, _ = grade(it, limits, rate_rules_enabled=rate_rules_enabled,
                         sudden_factor=sudden_factor, sudden_ack=sudden_ack)
            lv[g] += 1
            if it.get("cumulative") is not None:
                cums.append(abs(it["cumulative"]))
            if it.get("change") is not None:
                chgs.append(abs(it["change"]))
        rows.append(dict(
            sheet=sheet, metric=metric, points=len({i["pid"] for i in items}),
            正常=lv.get("正常", 0), 黄色预警=lv.get("黄色预警", 0),
            橙色预警=lv.get("橙色预警", 0), 红色预警=lv.get("红色预警", 0),
            未判定=lv.get(UNDETERMINED, 0),
            max_cum=round(max(cums), 2) if cums else "—",
            max_change=round(max(chgs), 2) if chgs else "—",
            unit=FAMILY_UNIT.get(sheet, ""),
        ))
    return rows


def load_rag_hits(metrics: list[str], skill_root: Path, mode: str,
                  rag_dir: str | None = None) -> tuple[dict, bool]:
    """获取知识库命中结果。

    - `auto`    —— 优先用 `assets/rag_hits.json` 缓存；缓存缺项则实时检索
    - `refresh` —— 强制实时检索并回写缓存
    - `off`     —— 不检索（I/J 的 RAG 部分留空并注明，不补造条文）

    返回 `(结果 dict, 是否真正接入知识库)`；任何失败都安静降级，不抛异常。
    """
    cache = skill_root / "assets" / "rag_hits.json"
    if mode == "off":
        return {"hits": {}, "available": False, "reason": "用户指定 --rag off"}, False

    if mode == "auto" and cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if data is not None and set(metrics) <= set((data.get("hits") or {}).keys()):
            return data, bool(data.get("available"))

    import subprocess
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="rag_"))
    qf, of = tmp / "queries.json", tmp / "hits.json"
    qf.write_text(json.dumps(sorted(set(metrics)), ensure_ascii=False), encoding="utf-8")
    cmd = [sys.executable, str(skill_root / "scripts" / "rag_lookup.py"),
           "--queries", str(qf), "--out", str(of)]
    if rag_dir:
        cmd += ["--rag-dir", rag_dir]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except Exception as exc:  # noqa: BLE001
        return {"hits": {}, "available": False,
                "reason": f"{type(exc).__name__}: {exc}"}, False
    if not of.exists():
        return {"hits": {}, "available": False, "reason": "检索脚本未产出结果"}, False
    data = json.loads(of.read_text(encoding="utf-8"))
    if data.get("available"):
        try:
            cache.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    return data, bool(data.get("available"))


def write_verdict_workbook(rows: list[dict], meta: dict, rag: dict, rag_available: bool):
    """生成「判定汇总表」独立工作簿（表C判定汇总 / 表D判定汇总 / 说明）。"""
    import verdict_table as vt

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for key, name in (("表C", "表C判定汇总"), ("表D", "表D判定汇总")):
        sub = [r for r in rows if r.get("sheet") == key]
        ws = wb.create_sheet(title=name)
        vt.write_verdict_sheet(ws, sub, key)
    ws = wb.create_sheet(title="说明")
    vt.write_notes_sheet(ws, meta, rows, rag, rag_available)
    return wb


def main() -> int:
    ap = argparse.ArgumentParser(description="把杂乱的表C/表D数据按规范格式填入汇总表 / 判定汇总表")
    ap.add_argument("--input", required=True, help="输入数据文件或目录")
    ap.add_argument("--output", required=True, help="输出 xlsx 路径")
    ap.add_argument("--layout", choices=["cd", "verdict", "af", "both", "all"], default="cd",
                    help="输出形态：cd=表C/表D工作簿（默认）；verdict=判定汇总表；"
                         "af=附录C/D/E/F原表式；both=cd+verdict；all=cd+verdict+af")
    ap.add_argument("--verdict-out", help="判定汇总表输出路径（layout=both 时用；"
                                          "默认 <output>_判定汇总.xlsx）")
    ap.add_argument("--split", action="store_true",
                    help="af 形态下：每张附表**单独输出一个文件**（<output>_附表C.xlsx …）")
    ap.add_argument("--appendix-periods", type=int, default=3,
                    help="af 形态下每个测点保留的期次数（默认 3，与参考文档一致）")
    ap.add_argument("--tables", choices=["cd", "cdef"], default="cd",
                    help="af 形态输出的附表范围：cd=仅 附表C/附表D（默认，参考文档点名的两张）；"
                         "cdef=附表C/D/E/F 全出")
    ap.add_argument("--rate-rules", choices=["on", "off"], default="on",
                    help="速率口径判据（GB 50497-2019 第 8.0.3 条「连续 3 次超 70%%」与"
                         "第 8.0.9-1 条「位移值突然明显增大」）：on=启用（默认）/ off=关闭")
    ap.add_argument("--sudden-factor", type=float, default=3.0,
                    help="「突然明显增大」的倍数阈值（默认 3.0 倍于前若干期变化量的中位数）；"
                         "规范未定量，属工程经验判据，须由项目专项方案确认；设为 0 关闭该条")
    ap.add_argument("--ack-sudden-factor", action="store_true",
                    help="确认启用「突然明显增大」判据（GB 50497-2019 第 8.0.9-1 条）。"
                         "**未确认时该条不参与判定**（退出码仍为 0），仅在产物中注明；"
                         "也可用环境变量 EXCAVAGUARD_ACK_SUDDEN_FACTOR=1")
    ap.add_argument("--derived-note", choices=["auto", "always", "never"], default="auto",
                    help="af 形态下「备注」末端的来源说明：auto=仅在确实推算时追加（默认）；"
                         "always=与参考文档逐字一致（所有附表都追加）；never=不追加")
    ap.add_argument("--meta", help="元数据 JSON（工程名称、报表编号、观测者等）")
    ap.add_argument("--limits", help="阈值 JSON（按监测项目给出 warn/control/rate，绝对量）")
    ap.add_argument("--design", help='设计值 JSON（内力/轴力类换算绝对量限值，如 {"支撑轴力": 800}）')
    ap.add_argument("--date", help="目标期日期 YYYY-MM-DD（默认取最新一期）")
    ap.add_argument("--period", choices=["interval", "daily"], default="interval",
                    help="判定汇总表的期次口径：interval=末期与相邻上一期（默认，与样例一致）；"
                         "daily=按日聚合")
    ap.add_argument("--safety-level", default="一级", help="基坑设计安全等级（一级/二级/三级）")
    ap.add_argument("--rag", choices=["auto", "off", "refresh"], default="auto",
                    help="知识库检索：auto=优先用缓存（默认）；off=不检索；refresh=重新检索并更新缓存")
    ap.add_argument("--rag-dir", help="jikeng-rag 根目录（默认自动探测）")
    ap.add_argument("--report", help="可选：把清洗报告写入 JSON")
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"✗ 输入不存在：{in_path}", file=sys.stderr)
        return 2

    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    meta = {"source": str(in_path), "safety_level": args.safety_level}
    if args.meta:
        meta.update(json.loads(Path(args.meta).read_text(encoding="utf-8")))
    limits = json.loads(Path(args.limits).read_text(encoding="utf-8")) if args.limits else None
    design = json.loads(Path(args.design).read_text(encoding="utf-8")) if args.design else None

    # ---- 「突然明显增大」判据的确认机制（方案 A：未确认则停用，不阻断） ----
    sudden_factor_cfg = max(0.0, float(args.sudden_factor))
    ack_env = str(os.environ.get("EXCAVAGUARD_ACK_SUDDEN_FACTOR", "")).strip().lower()
    sudden_ack = bool(args.ack_sudden_factor) or ack_env in ("1", "true", "yes", "on")
    rate_on = args.rate_rules == "on"
    if rate_on and sudden_factor_cfg > 0:
        state = ("已确认，判据生效" if sudden_ack else "未确认，判据停用")
        print("=" * 78)
        print("【判据使用提示】「位移值突然明显增大」—— GB 50497-2019 第 8.0.9-1 条（强制性条文）")
        print(f"  · 触发条件：本次变化量 ≥ {sudden_factor_cfg:g} × 前 3 期变化量中位数")
        print("  · 规范**未给出定量阈值**，该倍数属【工程经验判据】，")
        print("    用于真实工程前**必须由项目专项监测方案确认**。")
        print(f"  · 当前状态：{state}")
        if not sudden_ack:
            print("    该条不参与判定，仅在产物中注明；确认后启用：")
            print("      加参数  --ack-sudden-factor")
            print("      或设环境变量  EXCAVAGUARD_ACK_SUDDEN_FACTOR=1")
        print("=" * 78)
    rate_note = "未启用速率口径判据（--rate-rules off）。" if not rate_on else (
        f"已启用 GB 50497-2019 第 8.0.3 条「变化速率连续 3 次超过规定值 70%」；"
        f"第 8.0.9-1 条「位移值突然明显增大」："
        + (f"已确认启用，阈值 {sudden_factor_cfg:g} 倍（工程经验判据，须项目专项方案确认）。"
           if (sudden_ack and sudden_factor_cfg > 0)
           else "未确认，已停用（加 --ack-sudden-factor 启用）。"))
    meta["rate_rules_note"] = rate_note

    # --- 读取 ---
    all_raw: list[dict] = []
    read_reports = []
    for f in collect_inputs(in_path):
        rows, rep = read_records(f)
        for r in rows:
            r["_source"] = f.name
        read_reports.append(rep)
        all_raw.extend(rows)
    print(f"读取 {len(read_reports)} 个文件，共 {len(all_raw)} 行原始记录")

    # --- 清洗 ---
    records, review = normalize_rows(all_raw)
    valid = [r for r in records if r.get("valid")]
    print(f"清洗后有效记录 {len(valid)} 条，待复核 {len(review)} 项")

    skill_root = Path(__file__).resolve().parent.parent
    outputs: list[Path] = []
    all_alerts: list[dict] = []
    all_review: list[dict] = []
    summary_rows: list[dict] = []
    vrows: list[dict] = []
    v_date = None
    rag_ok = False
    af_rows: list[dict] = []

    # ================= ① 表 C / 表 D 规范表式工作簿 =================
    if args.layout in ("cd", "both", "all"):
        period_rows, period_date = build_period_rows(records, target_date)
        if period_date:
            meta.setdefault("current_time", f"{period_date} 观测")
        print(f"[表C/表D] 目标期：{period_date}（每日取最后一次观测；累计变化基准为该测点首期）")

        by_sheet = {k: [r for r in period_rows if r["sheet"] == k] for k in ("表C", "表D")}
        for k, v in by_sheet.items():
            print(f"  {k}：{len(v)} 条")
        other = [r for r in period_rows if r["sheet"] not in ("表C", "表D")]
        if other:
            fams = sorted({r["sheet"] for r in other})
            print(f"  提示：另有 {'/'.join(fams)} 类测点 {len(other)} 条，"
                  f"本形态不输出（用 --layout af 输出附录表式）")
        if not period_rows and valid:
            print("  提示：未能取得目标期（数据中缺少可解析的日期列）。"
                  "日报表式需要日期；如需按原表式输出请用 --layout af。")

        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for key, title in (("表C", "表 C 围护墙内力、立柱内力及土压力、孔隙水压力监测日报表"),
                           ("表D", "表 D 支撑轴力、锚杆轴力监测日报表")):
            ws = wb.create_sheet(title=key)
            a, rv = write_table_sheet(ws, key, title, by_sheet[key], limits, meta,
                                      rate_rules_enabled=rate_on,
                                      sudden_factor=sudden_factor_cfg,
                                      sudden_ack=sudden_ack)
            all_alerts.extend(a)
            all_review.extend(rv)

        summary_rows = summarize_table(period_rows, limits,
                                       rate_rules_enabled=rate_on,
                                       sudden_factor=sudden_factor_cfg,
                                       sudden_ack=sudden_ack)
        intraday = intraday_flags(period_rows)
        ws = wb.create_sheet(title="汇总")
        write_summary_sheet(ws, summary_rows, all_alerts, all_review + review, meta,
                            intraday=intraday)

        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        wb.properties.title = f"{meta.get('project', '')} 监测数据汇总表"
        wb.save(out)
        outputs.append(out)

        print(f"\n✓ 已生成 {out}")
        print(f"  sheet：{wb.sheetnames}")
        print(f"  超限测点 {len(all_alerts)} 个（红 {sum(1 for a in all_alerts if a['level'] == '红色预警')} / "
              f"橙 {sum(1 for a in all_alerts if a['level'] == '橙色预警')} / "
              f"黄 {sum(1 for a in all_alerts if a['level'] == '黄色预警')}）")
        print(f"  待复核 {len(all_review) + len(review)} 项")

    # ================= ② 判定汇总表（10 列版式，独立文件） =================
    if args.layout in ("verdict", "both", "all"):
        import verdict_table as vt

        if args.period == "interval":
            v_raw, v_date = build_interval_rows(records, target_date)
            period_desc = "末期与相邻上一期（保留原始采样间隔）"
        else:
            v_raw, v_date = build_period_rows(records, target_date)
            period_desc = "按日聚合（每日最后一次观测）"
        print(f"\n[判定汇总表] 目标期：{v_date}（{period_desc}）")

        lib = vt.load_library(skill_root / "assets" / "standards" / "GB50497-2019_预警值判据库.json")
        metrics = sorted({r["metric"] for r in v_raw})
        rag, rag_ok = load_rag_hits(metrics, skill_root, args.rag, args.rag_dir)

        vmeta = dict(meta, period=str(v_date), safety_level=args.safety_level)
        vrows = vt.build_verdict_rows(v_raw, lib, limits=limits, design=design, rag=rag,
                                      safety_level=args.safety_level, rag_available=rag_ok,
                                      rate_rules_enabled=rate_on,
                                      sudden_factor=sudden_factor_cfg,
                                      sudden_ack=sudden_ack)

        if args.verdict_out:
            vout = Path(args.verdict_out)
        elif args.layout == "verdict":
            vout = Path(args.output)
        else:
            vout = Path(args.output).with_name(Path(args.output).stem + "_判定汇总.xlsx")
        vout.parent.mkdir(parents=True, exist_ok=True)

        vwb = write_verdict_workbook(vrows, vmeta, rag, rag_ok)
        vwb.properties.title = f"{meta.get('project', '')} 监测数据判定汇总表"
        vwb.save(vout)
        outputs.append(vout)

        dist = " / ".join(f"{lv} {sum(1 for r in vrows if r['level'] == lv)}"
                          for lv in (vt.LEVEL_OK, vt.LEVEL_YELLOW, vt.LEVEL_ORANGE,
                                     vt.LEVEL_RED, vt.LEVEL_UNKNOWN))
        print(f"✓ 已生成判定汇总表 {vout}")
        print(f"  sheet：{vwb.sheetnames}")
        print(f"  行数 {len(vrows)}；等级分布 {dist}")
        print(f"  知识库检索：{'已接入' if rag_ok else '未接入（I/J 的 RAG 部分留空并注明）'}")
        print(f"  速率口径判据：{'开' if args.rate_rules == 'on' else '关'}"
              + (f"（突变倍数 {sudden_factor_cfg:g}，"
                 + ("已确认生效）" if sudden_ack else "未确认已停用）")
                 if (rate_on and sudden_factor_cfg > 0) else ""))

    # ================= ③ 附录 C/D/E/F 原表式（参考 监测日报_附表AF_RAG.xlsx） =================
    if args.layout in ("af", "all"):
        import appendix_table as at
        import verdict_table as vt

        af_rows = build_appendix_rows(records, periods=args.appendix_periods,
                                      target_date=target_date)
        lib = vt.load_library(skill_root / "assets" / "standards" / "GB50497-2019_预警值判据库.json")
        af_keys = ("表C", "表D") if args.tables == "cd" else ("表C", "表D", "表E", "表F")
        by_family = {k: [r for r in af_rows if r.get("sheet") == k]
                     for k in ("表C", "表D", "表E", "表F")}
        print(f"\n[附录表式] 输出 {('、'.join(af_keys))}；每测点保留 {args.appendix_periods} 期；"
              f"速率口径判据 {'开' if args.rate_rules == 'on' else '关'}")
        for k in af_keys:
            print(f"  {k}：{len(by_family[k])} 条")
        skipped_fam = [k for k in ("表E", "表F") if k not in af_keys and by_family[k]]
        if skipped_fam:
            print(f"  提示：另有 {'、'.join(skipped_fam)} 类测点 "
                  f"{sum(len(by_family[k]) for k in skipped_fam)} 条未输出"
                  f"（加 --tables cdef 可一并输出）")

        af_meta = dict(meta)
        dates = sorted({r["ts"].date() for r in af_rows if r.get("ts")})
        if dates and not af_meta.get("current_time"):
            af_meta["current_time"] = str(dates[-1])
            af_meta.setdefault("previous_time", str(dates[0]))

        def _sheet_name(key: str) -> str:
            return f"附表{key[1]}_{at.FAMILY_TITLE[key]}监测日报表"

        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for key in af_keys:
            ws = wb.create_sheet(title=_sheet_name(key)[:31])
            at.write_appendix_sheet(ws, key, by_family[key], af_meta, lib,
                                    limits=limits, design=design,
                                    safety_level=args.safety_level,
                                    derived_note=args.derived_note,
                                    rate_rules_enabled=rate_on,
                                    sudden_factor=sudden_factor_cfg,
                                    sudden_ack=sudden_ack)
        out = Path(args.output)
        if args.layout == "all":
            out = out.with_name(out.stem + "_附录表式" + out.suffix)
        out.parent.mkdir(parents=True, exist_ok=True)
        wb.properties.title = f"{meta.get('project', '')} 监测日报 附表C/D/E/F"
        wb.save(out)
        outputs.append(out)
        print(f"✓ 已生成附录表式 {out.resolve()}")
        print(f"  sheet：{wb.sheetnames}")

        if args.split:
            for key in af_keys:
                if not by_family[key]:
                    continue
                swb = openpyxl.Workbook()
                swb.remove(swb.active)
                sws = swb.create_sheet(title=_sheet_name(key)[:31])
                at.write_appendix_sheet(sws, key, by_family[key], af_meta, lib,
                                        limits=limits, design=design,
                                        safety_level=args.safety_level,
                                        derived_note=args.derived_note,
                                        rate_rules_enabled=rate_on,
                                        sudden_factor=sudden_factor_cfg,
                                        sudden_ack=sudden_ack)
                sp = out.with_name(f"{out.stem}_附表{key[1]}{out.suffix}")
                swb.save(sp)
                outputs.append(sp)
            print(f"  已单独提取 {sum(1 for k in af_keys if by_family[k])} 个附表文件")

    # ================= 报告 =================
    if args.report:
        payload = {
            "schema": SCHEMA, "input": str(in_path),
            "outputs": [str(p) for p in outputs],
            "read_reports": read_reports,
            "records_total": len(records), "records_valid": len(valid),
            "review": review,
        }
        if args.layout in ("cd", "both", "all"):
            payload.update(alerts=all_alerts, review_all=all_review + review,
                           summary_rows=summary_rows)
        if args.layout in ("verdict", "both", "all"):
            payload["period"] = str(v_date)
            payload["rag_available"] = bool(rag_ok)
            payload["verdict_rows"] = [{k: v for k, v in r.items() if k != "limit"} for r in vrows]
        if args.layout in ("af", "all"):
            payload["appendix_rows"] = [{k: v for k, v in r.items() if k != "limit"}
                                        for r in af_rows]
        Path(args.report).write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                                 default=str),
                                     encoding="utf-8")
        print(f"  报告已写入 {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
