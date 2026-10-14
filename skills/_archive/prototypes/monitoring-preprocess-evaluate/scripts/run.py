# -*- coding: utf-8 -*-
"""
run.py — 监测数据预处理为 GB 50497-2019 附表 E / 附表 F 格式 + 三级预警评价（含 RAG 证据）

两阶段：
  阶段 A（确定性，仅标准库即可运行）：宽表 CSV → 长表 → 按监测日重采样时间序列
        → 套 thresholds_gb50497_2019.json 分三级（正常 / 黄色(需关注) / 红色(报警)）
        → 输出 附表E_格式化.csv / .xlsx、附表F_格式化.csv / .xlsx、
           评价结论 evaluation.json、简要分析及判断性结论
  阶段 B（RAG 证据，需 chromadb）：对每个有阈值的监测项查 jikeng_norms（标准库）
        取 evidence.clause 对应条文，附 source/clause/score；缺失依赖或集合时优雅降级。

输出格式严格对齐真实基坑监测日报「附表E_地下水位等监测日报表 / 附表F_裂缝监测日报表」：
  附表E 列 = 初始高程, 本次高程, 上次高程, 本次变化, 累计变化, 变化速率, 日内峰值速率(mm/d), 编号, 点号, 备注
  附表F 列 = 长度(mm), 宽度(mm), 本次测试值, 单次变化, 累计变化, 变化速率, 日内峰值速率(mm/d), 点号, 形态, 备注
  其中「备注」集中承载预警信息：预警等级 / 报警值 / 控制值 / 占报警值% / 超报警值 / 触发原因 /
    速率增强(8.0.3-3连续超70% / 8.0.9突变 / 日内峰值速率) / 规范依据(RAG)。
  速率口径（A–D）：
    - 变化速率列 = 日内首末差 / 当日实际时长（日平均，保留用户要求的"日内变化"口径）；
    - 逐期速率序列（相邻读数差 / 监测间隔, mm/d）用于 8.0.3-3「连续3期≥70%报警速率⇒红」、
      8.0.9-1「位移突然明显增大⇒危险报警」判定；
    - 日内峰值速率 = 当日内相邻读数最大 |速率|，作为辅助列（非规范强制字段）凸显瞬时突变，
      日平均速率会掩盖此类突变。

用法：
  python run.py --csv <path> [--foundation 深基础|浅基础] [--interval-minutes 5]
                [--no-rag] [--output-dir <dir>] [--self-test]

退出码：0=成功；2=输入/数据质量弃权；3=RAG 依赖缺失（仅当 --require-rag）。
"""
import argparse
import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ROOT = ExcavaGuard 仓库根（scripts/monitoring-preprocess-evaluate/scripts/run.py -> parents[3]）
HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
THRESHOLDS_PATH = ROOT / "确定性计算层" / "standards" / "default" / "thresholds_gb50497_2019.json"
DB_DIR = ROOT / "data" / "chroma_db"
MODEL_DIR = ROOT / "models" / "bge-small-zh"
COLLECTION = "jikeng_norms"

# 附表 E / F 输出列（对齐真实日报模板；日内峰值速率(mm/d) 为 A-D 增强列，非规范强制字段）
E_HEADER = ["初始高程", "本次高程", "上次高程", "本次变化", "累计变化",
            "变化速率", "日内峰值速率(mm/d)", "编号", "点号", "备注"]
F_HEADER = ["长度(mm)", "宽度(mm)", "本次测试值", "单次变化", "累计变化",
            "变化速率", "日内峰值速率(mm/d)", "点号", "形态", "备注"]

# 三级预警词汇（对齐参考日报：正常 / 黄色(需关注) / 红色(报警)）+ 未判定
LEVELS = ["正常", "黄色(需关注)", "红色(报警)", "未判定"]


# ------------------------------------------------------------------ 列解析
COLUMN_PATTERNS = [
    (re.compile(r"^地下水位-(SW-\d+)-原始值"), "groundwater_level", "地下水位", "E"),
    (re.compile(r"^地表竖向位移-(DBC-\d+)-原始值"), "surface_settlement", "周边地表竖向位移", "E"),
    (re.compile(r"^分层竖向位移-(FC-\d+)-原始值"), "soil_layered_vertical_displacement", "土体分层竖向位移", "E"),
    (re.compile(r"^坑底隆起-(KB-\d+)-原始值"), "basal_heave", "坑底隆起（回弹）", "E"),
    (re.compile(r"^裂缝-(LF-\d+)-宽度-原始值"), "crack_width_surface", "地表裂缝宽度", "F"),
    (re.compile(r"^裂缝-(LF-\d+)-长度-原始值"), None, "地表裂缝长度", "F"),
]


def parse_columns(header):
    """返回 [(col_name, point_id, metric_key, display_name, table_type)]。"""
    out = []
    for col in header:
        if col.strip() in ("时间", "Time", "time"):
            continue
        for pat, mk, disp, tbl in COLUMN_PATTERNS:
            m = pat.match(col.strip())
            if m:
                point_id = m.group(1)
                out.append((col, point_id, mk, disp, tbl))
                break
    return out


# ------------------------------------------------------------------ 阈值
def load_thresholds():
    if not THRESHOLDS_PATH.exists():
        raise FileNotFoundError(f"阈值文件缺失: {THRESHOLDS_PATH}")
    return json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))


def resolve_safety_level(foundation_arg, csv_path):
    if foundation_arg:
        return "一级" if "深" in foundation_arg else "三级"
    name = Path(csv_path).name
    if "深基础" in name:
        return "一级"
    if "浅基础" in name:
        return "三级"
    return None


def select_rule(metric_def, safety_level):
    rules = metric_def.get("rules", [])
    if not rules:
        return None
    for r in rules:
        sl = r.get("safety_level", [])
        if isinstance(sl, list) and safety_level in sl:
            return r
        if sl == "any":
            return r
    # 裂缝按状态回退（默认新增裂缝）
    for r in rules:
        if r.get("crack_state") == ["新增裂缝"]:
            return r
    return rules[0]


def limits_of(rule):
    if rule is None:
        return None, None, None, None
    cm = rule.get("cumulative_mm")
    rm = rule.get("rate_mm_per_day")
    warn_c = cm["min"] if isinstance(cm, dict) else None
    control_c = cm["max"] if isinstance(cm, dict) else None
    warn_r = rm["min"] if isinstance(rm, dict) else None
    control_r = rm["max"] if isinstance(rm, dict) else None
    return warn_c, control_c, warn_r, control_r


def classify(cum, rate, warn_c, control_c, warn_r, control_r,
             consec70_red=False, sudden_jump=False):
    """三级预警 + 8.0.3-3 / 8.0.9 速率增强（A–D）。
    返回 (level, reasons)：
      - 红色(报警)：
          累计≥报警值（表8.0.4/8.0.5累计） 或
          速率≥报警速率（表8.0.4/8.0.5速率规定值，mm/d） 或
          连续3期变化速率≥70%报警速率（GB 50497-2019 8.0.3-3） 或
          位移突然明显增大（GB 50497-2019 8.0.9-1，危险报警）。
      - 黄色(需关注)：累计≥70%报警值 或 速率≥70%报警速率（接近报警的前期关注）。
      - 正常：其余。
      - 未判定：无阈值。
    注：控制值为 GB 强制上限，不在等级判定中另立一级（避免与报警值重复触发红色），
        仅在「备注」中提示「超控制值」状态。
    """
    reasons = []
    if warn_c is None and warn_r is None:
        return "未判定", reasons
    a = abs(cum)
    b = abs(rate) if rate is not None else 0.0
    # —— 红色(报警) ——
    if (warn_c is not None and a >= warn_c) or (warn_r is not None and b >= warn_r):
        reasons.append("累计或速率达报警值")
        return "红色(报警)", reasons
    if consec70_red:
        reasons.append("连续3期变化速率≥70%报警速率(8.0.3-3)")
        return "红色(报警)", reasons
    if sudden_jump:
        reasons.append("位移突然明显增大(8.0.9-1)")
        return "红色(报警)", reasons
    # —— 黄色(需关注) ——
    if (warn_c is not None and a >= 0.7 * warn_c) or (warn_r is not None and b >= 0.7 * warn_r):
        reasons.append("累计或速率达70%报警值(需关注)")
        return "黄色(需关注)", reasons
    return "正常", reasons


# ------------------------------------------------------------------ 时间序列重采样（按监测日）
def _parse_time(v):
    v = (v or "").strip()
    if not v:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def compute_cycle_rates(series):
    """逐期(相邻读数)速率序列，单位 mm/d（A）。
    series: sorted [(datetime, float), ...]
    返回 [(t_mid: datetime, span_days: float, rate_mm_per_day: float), ...]，长度 len-1。
    span<=0 的相邻点跳过；rate = (v1−v0)/Δt_days。
    这是规范附录E/F「变化速率(mm/d)」= (本次−上次)/监测间隔 的逐期展开，
    也是 8.0.3-3「连续3次超过70%」与 8.0.9「突然明显增大」判定的数据基础。
    """
    if len(series) < 2:
        return []
    s = sorted(series, key=lambda x: x[0])
    out = []
    for i in range(1, len(s)):
        dt0, v0 = s[i - 1]
        dt1, v1 = s[i]
        span = (dt1 - dt0).total_seconds() / 86400.0
        if span <= 0:
            continue
        out.append((dt1, span, (v1 - v0) / span))
    return out


def build_daily(series, cycle_rates=None, warn_r=None):
    """series: [(datetime, float)] → 按自然日重采样为日序列（分析每日内变化）。
    在「日内首末差 / 当日时长」的日平均速率之外（本次用户明确要求的日内变化口径），
    额外基于逐期速率序列计算当日内：连续3期≥70%报警速率(consec70_red, 8.0.3-3)、
    突然明显增大(sudden_jump, 8.0.9-1)、日内峰值速率(peak_rate, A–D 增强列)。

    返回 [{"date","cur","prev","baseline","change","cum","rate","span_days",
            "peak_rate","consec70_red","sudden_jump"}]：
      - cur/prev/change/cum/rate/span_days：同前（日内窗口口径）
      - peak_rate      = 当日内相邻读数最大 |速率| (mm/d)，反映瞬时突变（日平均会掩盖）
      - consec70_red  = 当日内是否存在连续≥3期 |速率|≥0.7×报警速率
      - sudden_jump   = 当日内是否存在单期 |速率| 明显突变（≥0.7×报警速率 且 ≥3×稳健速率中位数）
    仅当 warn_r 有效时做阈值相关判定；cycle_rates 为空则峰值/突变为 0/False。
    """
    if not series:
        return []
    series = sorted(series, key=lambda x: x[0])
    baseline = series[0][1]
    by_date = defaultdict(list)
    for dt, v in series:
        by_date[dt.date()].append((dt, v))
    day_cycle = defaultdict(list)
    if cycle_rates:
        for (t_mid, span, r) in cycle_rates:
            day_cycle[t_mid.date()].append((t_mid, span, r))
    out = []
    for d in sorted(by_date):
        day = sorted(by_date[d], key=lambda x: x[0])
        first_t, first_v = day[0]
        last_t, last_v = day[-1]
        span_days = (last_t - first_t).total_seconds() / 86400.0 if len(day) >= 2 else 0.0
        change = last_v - first_v                       # 日内变化量（窗口内）
        rate = (change / span_days) if span_days > 0 else 0.0  # 日内平均速率 mm/d
        cum = last_v - baseline                          # 累计变化量（自基线）
        # 当日内逐期速率分析（A–D）
        cr = day_cycle.get(d, [])
        abs_r = [abs(r) for (_, _, r) in cr]
        peak = max(abs_r) if abs_r else 0.0
        consec70 = False
        jump = False
        if warn_r and warn_r > 0 and abs_r:
            thr = 0.7 * warn_r
            run = best = 0
            for a in abs_r:
                run = run + 1 if a >= thr else 0
                best = max(best, run)
            consec70 = best >= 3
            med = statistics.median(abs_r) if abs_r else 0.0
            for (_, _, r) in cr:
                if abs(r) >= thr and abs(r) >= 3.0 * max(med, 1e-9):
                    jump = True
                    break
        out.append({"date": d, "cur": last_v, "prev": first_v, "baseline": baseline,
                    "change": change, "cum": cum, "rate": rate, "span_days": span_days,
                    "peak_rate": peak, "consec70_red": consec70, "sudden_jump": jump})
    return out


# ------------------------------------------------------------------ RAG
_RAG_CACHE = {}


def query_rag(metric_key, display_name, clause):
    """查 jikeng_norms 标准库，返回证据列表。失败返回 EVIDENCE_NOT_FOUND。"""
    cache_key = (metric_key, clause)
    if cache_key in _RAG_CACHE:
        return _RAG_CACHE[cache_key]
    try:
        import chromadb
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    except Exception as e:  # pragma: no cover
        res = {"status": "EVIDENCE_NOT_FOUND", "reason": "RAG_DEPENDENCY_MISSING",
               "detail": f"{type(e).__name__}: {e}"}
        _RAG_CACHE[cache_key] = res
        return res
    model_path = str(MODEL_DIR) if MODEL_DIR.exists() else "BAAI/bge-small-zh"
    ef = SentenceTransformerEmbeddingFunction(model_name=model_path, device="cpu")
    try:
        client = chromadb.PersistentClient(path=str(DB_DIR))
        coll = client.get_collection(name=COLLECTION, embedding_function=ef)
    except Exception as e:
        res = {"status": "EVIDENCE_NOT_FOUND", "reason": "RAG_COLLECTION_MISSING",
               "detail": f"{type(e).__name__}: {e}"}
        _RAG_CACHE[cache_key] = res
        return res
    q = "为这个句子生成表示以用于检索相关文章：" + f"{display_name} 监测预警值累计值 变化速率 {clause or ''}"
    try:
        r = coll.query(query_texts=[q], n_results=3)
    except Exception as e:
        res = {"status": "EVIDENCE_NOT_FOUND", "reason": "RAG_QUERY_FAILED",
               "detail": f"{type(e).__name__}: {e}"}
        _RAG_CACHE[cache_key] = res
        return res
    hits = []
    for doc, meta, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0]):
        hits.append({
            "score": round(1 - dist, 4),
            "source": meta.get("source", ""),
            "clause": meta.get("clause", ""),
            "category": meta.get("category", ""),
            "content": doc,
        })
    res = {"status": "OK", "hits": hits}
    _RAG_CACHE[cache_key] = res
    return res


# ------------------------------------------------------------------ 备注 / 摘要文本
def _fmt(x, nd=3):
    if x is None:
        return "—"
    if isinstance(x, float):
        if x == int(x):
            return str(int(x))
        return f"{x:.{nd}f}"
    return str(x)


def build_remark(level, warn_c, control_c, cum, ev, canonical_clause, reasons=None, flags=None):
    """生成「备注」列文本：预警等级 / 报警值 / 控制值 / 占报警值% / 超报警值 / 触发原因 /
    速率增强(8.0.3-3 连续超70% / 8.0.9 突变 / 日内峰值速率) / 规范依据(RAG)。"""
    reasons = reasons or []
    flags = flags or {}
    if level == "未判定":
        rag = _brief(ev, canonical_clause)
        base = "预警等级：未判定"
        return f"{base}；{rag}" if rag else base
    a = abs(cum)
    pct = (a / warn_c * 100) if warn_c else 0.0
    over_warn = "是" if (warn_c is not None and a >= warn_c) else "否"
    over_ctrl = "是" if (control_c is not None and a >= control_c) else "否"
    s = (f"预警等级：{level}；报警值：{_fmt(warn_c)} mm；控制值：{_fmt(control_c)} mm；"
         f"占报警值：{pct:.1f}%；超报警值：{over_warn}；超控制值：{over_ctrl}")
    if reasons:
        s += "；触发：" + "、".join(reasons)
    if flags:
        if flags.get("consec70_red"):
            s += "；[8.0.3-3]连续3期速率≥70%报警速率"
        if flags.get("sudden_jump"):
            s += "；[8.0.9-1]位移突然明显增大"
        pk = flags.get("peak_rate")
        if pk is not None:
            s += f"；日内峰值速率：{_fmt(pk)} mm/d(非规范强制字段)"
    rag = _brief(ev, canonical_clause)
    if rag:
        s += f"；{rag}"
    return s


def build_summary_lines(table_label, points_latest, start_date, end_date, last_date):
    """生成「简要分析及判断性结论」文本列表（对齐参考日报 R23-R28）。"""
    n = len(points_latest)
    cnt = Counter(p["level"] for p in points_latest)
    normal = cnt.get("正常", 0)
    yellow = cnt.get("黄色(需关注)", 0)
    red = cnt.get("红色(报警)", 0)
    unk = cnt.get("未判定", 0)
    if red > 0:
        overall = "报警"
    elif yellow > 0:
        overall = "需关注"
    elif unk == n and n > 0:
        overall = "未判定"
    else:
        overall = "正常"
    lines = []
    lines.append(f"· 本附表共 {n} 个测点（{table_label}），监测期 {start_date} ~ {end_date}（末次监测日 {last_date}）。本期综合判定：{overall}。")
    lines.append(f"· 末次监测日统计：正常 {normal} 点、需关注(黄色) {yellow} 点、报警(红色) {red} 点、未判定 {unk} 点。")
    reds = [p for p in points_latest if p["level"] == "红色(报警)"]
    if reds:
        det = "；".join(
            f"{p['point_id']} 累计 {_fmt(p['cumulative'])} / 报警值 {_fmt(p['warn_c'])} / 占 {p['pct']:.1f}%"
            for p in reds)
        lines.append(f"· 红色报警测点（累计量已达/超报警值）：{det}")
    rate_reds = [p for p in points_latest if p["level"] == "红色(报警)" and p.get("rate_alert")]
    if rate_reds:
        det = "；".join(
            f"{p['point_id']} 日内峰值速率 {_fmt(p.get('peak_rate', 0))} mm/d（8.0.3-3连续≥70%报警速率 或 8.0.9位移突变）"
            for p in rate_reds)
        lines.append(f"· 速率预警测点（变化速率达报警值/连续3期≥70%报警速率/突然明显增大）：{det}")
    fast = [p for p in points_latest if p.get("rate") is not None and abs(p["rate"]) >= 2]
    if fast:
        det = "、".join(f"{p['point_id']} {_fmt(abs(p['rate']))}" for p in fast)
        lines.append(f"· 变化速率较大（≥2 单位/天）的测点：{det}，建议核查坑边荷载与降水情况。")
    if red > 0:
        lines.append("结论：存在红色报警测点，累计量已达或超过 GB 50497-2019 表 8.0.4/8.0.5 报警值，"
                     "建议按第 8.0.9 条启动预警程序、加密监测并组织复核。")
    else:
        lines.append("结论：本期未发现红色报警测点，累计量均在 GB 50497-2019 表 8.0.4/8.0.5 报警值以内，"
                     "建议维持常规监测频率。")
    return lines


def _brief(ev, canonical_clause=""):
    """规范依据摘要：权威条款号 + RAG 最佳命中来源与相似度。"""
    if not ev or ev.get("status") != "OK" or not ev.get("hits"):
        return (f"依据{canonical_clause}（RAG证据缺失）" if canonical_clause else "")
    h = ev["hits"][0]
    hit_clause = h.get("clause") or canonical_clause or ""
    prefix = f"依据{canonical_clause}；" if canonical_clause else ""
    return f"{prefix}RAG命中 {h['source']} {hit_clause}（score {h['score']}）"


def _num(point_id):
    digs = re.findall(r"\d+", point_id or "")
    return digs[-1] if digs else point_id


# ------------------------------------------------------------------ 主流程
def evaluate(csv_path, foundation=None, interval_minutes=5, rag_enabled=True, output_dir=None):
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return {"status": "INVALID_INPUT", "reason": "FILE_NOT_FOUND", "detail": str(csv_path)}, 2

    safety_level = resolve_safety_level(foundation, csv_path)
    thresholds = load_thresholds()
    metrics = thresholds.get("metrics", {})

    # 读宽表
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if len(rows) < 2:
        return {"status": "INVALID_INPUT", "reason": "NO_DATA", "detail": f"行数={len(rows)}"}, 2
    header = rows[0]
    data_rows = rows[1:]
    cols = parse_columns(header)
    if not cols:
        return {"status": "INVALID_INPUT", "reason": "NO_MONITORING_COLUMNS",
                "detail": "未在表头中识别到任何监测项列"}, 2

    # 时间列索引
    tidx = next((i for i, h in enumerate(header) if h.strip() in ("时间", "Time", "time")), None)
    if tidx is None:
        return {"status": "DATA_QUALITY", "reason": "NO_TIME_COLUMN", "detail": "缺少时间列"}, 2

    # 解析每列时间序列
    points = {}  # (tbl, point_id) -> {table, point_id, sub:{disp: {metric_key, display_name, series:[(dt,val)]}}}
    all_times = []
    for (col, point_id, mk, disp, tbl) in cols:
        cidx = header.index(col)
        series = []
        for dr in data_rows:
            if cidx >= len(dr):
                continue
            tv = dr[tidx].strip() if tidx < len(dr) else ""
            dt = _parse_time(tv)
            v = dr[cidx].strip()
            if v == "":
                continue
            try:
                val = float(v)
            except ValueError:
                continue
            if dt is None:
                continue
            series.append((dt, val))
            all_times.append(dt)
        if len(series) < 2:
            continue
        key = (tbl, point_id)
        rec = points.setdefault(key, {"table": tbl, "point_id": point_id, "sub": {}})
        rec["sub"][disp] = {"metric_key": mk, "display_name": disp, "series": series}

    if not points:
        return {"status": "DATA_QUALITY", "reason": "NO_VALID_SERIES",
                "detail": "所有监测列均无足够有效数值"}, 2

    start_date = min(all_times).date().isoformat() if all_times else "—"
    end_date = max(all_times).date().isoformat() if all_times else "—"

    # 判定 + 生成附表行
    tableE_rows, tableF_rows = [], []
    eval_points = []
    level_counts = {k: 0 for k in LEVELS}
    e_points_latest, f_points_latest = [], []

    for (tbl, point_id), rec in points.items():
        # 选主监测项：优先有阈值的项，否则第一项
        primary_disp = None
        for d, sub in rec["sub"].items():
            md = metrics.get(sub["metric_key"]) if sub["metric_key"] else None
            if md and md.get("rules"):
                primary_disp = d
                break
        if primary_disp is None:
            primary_disp = next(iter(rec["sub"]))
        psub = rec["sub"][primary_disp]
        mk = psub["metric_key"]
        disp = psub["display_name"]

        # 阈值与 RAG（每测点仅查一次）
        metric_def = metrics.get(mk) if mk else None
        if metric_def and metric_def.get("rules"):
            rule = select_rule(metric_def, safety_level)
            warn_c, control_c, warn_r, control_r = limits_of(rule)
            canonical_clause = rule.get("evidence", {}).get("clause", "")
        else:
            rule = None
            warn_c = control_c = warn_r = control_r = None
            canonical_clause = ""
        ev = query_rag(mk, disp, canonical_clause) if (rag_enabled and mk) else None

        cycle_rates = compute_cycle_rates(psub["series"])
        daily = build_daily(psub["series"], cycle_rates, warn_r)

        if tbl == "E":
            for d in daily:
                lvl, reasons = classify(d["cum"], d["rate"], warn_c, control_c, warn_r, control_r,
                                        d["consec70_red"], d["sudden_jump"])
                remark = build_remark(lvl, warn_c, control_c, d["cum"], ev, canonical_clause,
                                      reasons=reasons, flags=d)
                tableE_rows.append({
                    "初始高程": _fmt(d["baseline"]),
                    "本次高程": _fmt(d["cur"]),
                    "上次高程": _fmt(d["prev"]),
                    "本次变化": _fmt(d["change"]),
                    "累计变化": _fmt(d["cum"]),
                    "变化速率": _fmt(d["rate"]),
                    "日内峰值速率(mm/d)": _fmt(d["peak_rate"]),
                    "编号": _num(point_id),
                    "点号": point_id,
                    "备注": remark,
                })
            last = daily[-1]
            lvl, reasons = classify(last["cum"], last["rate"], warn_c, control_c, warn_r, control_r,
                                    last["consec70_red"], last["sudden_jump"])
            pct = (abs(last["cum"]) / warn_c * 100) if warn_c else 0.0
            level_counts[lvl] += 1
            e_points_latest.append({"point_id": point_id, "metric_key": mk, "display_name": disp,
                                    "level": lvl, "cumulative": last["cum"], "warn_c": warn_c,
                                    "control_c": control_c, "rate": last["rate"], "pct": pct,
                                    "peak_rate": last["peak_rate"],
                                    "rate_alert": last["consec70_red"] or last["sudden_jump"]})
            eval_points.append(_eval_point(point_id, disp, mk, last, warn_c, control_c,
                                           warn_r, control_r, lvl, ev))
        else:  # F 裂缝
            width_sub = rec["sub"].get("地表裂缝宽度")
            length_sub = rec["sub"].get("地表裂缝长度")
            wcycle = compute_cycle_rates(width_sub["series"]) if width_sub else []
            width_daily = build_daily(width_sub["series"], wcycle, warn_r) if width_sub else []
            length_daily = build_daily(length_sub["series"]) if length_sub else []
            len_by_date = {x["date"]: x for x in length_daily}
            for d in width_daily:
                lvl, reasons = classify(d["cum"], d["rate"], warn_c, control_c, warn_r, control_r,
                                        d["consec70_red"], d["sudden_jump"])
                remark = build_remark(lvl, warn_c, control_c, d["cum"], ev, canonical_clause,
                                      reasons=reasons, flags=d)
                ld = len_by_date.get(d["date"])
                tableF_rows.append({
                    "长度(mm)": _fmt(ld["cum"]) if ld else "—",
                    "宽度(mm)": _fmt(d["cur"]),
                    "本次测试值": _fmt(d["cur"]),
                    "单次变化": _fmt(d["change"]),
                    "累计变化": _fmt(d["cum"]),
                    "变化速率": _fmt(d["rate"]),
                    "日内峰值速率(mm/d)": _fmt(d["peak_rate"]),
                    "点号": point_id,
                    "形态": "—",
                    "备注": remark,
                })
            if width_daily:
                last = width_daily[-1]
                lvl, reasons = classify(last["cum"], last["rate"], warn_c, control_c, warn_r, control_r,
                                        last["consec70_red"], last["sudden_jump"])
                pct = (abs(last["cum"]) / warn_c * 100) if warn_c else 0.0
                level_counts[lvl] += 1
                f_points_latest.append({"point_id": point_id, "metric_key": mk, "display_name": "地表裂缝",
                                        "level": lvl, "cumulative": last["cum"], "warn_c": warn_c,
                                        "control_c": control_c, "rate": last["rate"], "pct": pct,
                                        "peak_rate": last["peak_rate"],
                                        "rate_alert": last["consec70_red"] or last["sudden_jump"]})
                eval_points.append(_eval_point(point_id, "地表裂缝", mk, last, warn_c, control_c,
                                               warn_r, control_r, lvl, ev))
            else:
                level_counts["未判定"] += 1
                f_points_latest.append({"point_id": point_id, "metric_key": mk, "display_name": "地表裂缝",
                                        "level": "未判定", "cumulative": None, "warn_c": warn_c,
                                        "control_c": control_c, "rate": None, "pct": 0.0,
                                        "peak_rate": None, "rate_alert": False})
                eval_points.append(_eval_point(point_id, "地表裂缝", mk,
                                               {"baseline": None, "last": None, "last_change": None,
                                                "rate": None, "cumulative": None,
                                                "peak_rate": None, "consec70_red": False, "sudden_jump": False},
                                               warn_c, control_c, warn_r, control_r, "未判定", ev))

    # 简要分析
    last_date = end_date
    e_summary = build_summary_lines("地下水位等", e_points_latest, start_date, end_date, last_date)
    f_summary = build_summary_lines("裂缝", f_points_latest, start_date, end_date, last_date)

    # 写出
    out_dir = Path(output_dir) if output_dir else csv_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_table(out_dir / "附表E_格式化.csv", tableE_rows, E_HEADER)
    _write_table(out_dir / "附表F_格式化.csv", tableF_rows, F_HEADER)
    _write_xlsx(out_dir / "附表E_格式化.xlsx", "附表E_地下水位等监测日报表",
                E_HEADER, tableE_rows, e_summary, start_date, end_date)
    _write_xlsx(out_dir / "附表F_格式化.xlsx", "附表F_裂缝监测日报表",
                F_HEADER, tableF_rows, f_summary, start_date, end_date)

    payload = {
        "status": "OK",
        "meta": {
            "csv_path": str(csv_path),
            "foundation": foundation or ("深基础" if safety_level == "一级" else "浅基础"),
            "safety_level": safety_level,
            "interval_minutes": interval_minutes,
            "rag_enabled": rag_enabled,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "monitoring_period": {"start": start_date, "end": end_date},
            "total_points": len(eval_points),
        },
        "summary": {"level_counts": level_counts,
                    "E_points": len(e_points_latest), "F_points": len(f_points_latest),
                    "E_rows": len(tableE_rows), "F_rows": len(tableF_rows)},
        "analysis": {"附表E": e_summary, "附表F": f_summary},
        "points": eval_points,
    }
    (out_dir / "evaluation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"status": "OK", "output_dir": str(out_dir),
            "level_counts": level_counts,
            "E_points": len(e_points_latest), "F_points": len(f_points_latest),
            "E_rows": len(tableE_rows), "F_rows": len(tableF_rows)}, 0


def _eval_point(point_id, disp, mk, s, warn_c, control_c, warn_r, control_r, lvl, ev):
    # 兼容 daily dict（cum/change/cur）与构造 dict（cumulative/last_change/last）
    cum = s.get("cum") if s.get("cum") is not None else s.get("cumulative")
    last_v = s.get("cur") if s.get("cur") is not None else s.get("last")
    last_chg = s.get("change") if s.get("change") is not None else s.get("last_change")
    rate = s.get("rate")
    p = {
        "point_id": point_id, "metric_key": mk, "display_name": disp,
        "baseline": s.get("baseline"), "last": last_v,
        "last_change": round(last_chg, 4) if last_chg is not None else None,
        "rate_mm_per_day": round(abs(rate), 4) if rate is not None else None,
        "cumulative": round(cum, 4) if cum is not None else None,
        "warn_value_mm": warn_c, "control_value_mm": control_c,
        "warn_rate_mm_per_day": warn_r, "control_rate_mm_per_day": control_r,
        "level": lvl,
    }
    # A–D 速率增强字段
    if s.get("peak_rate") is not None:
        p["peak_rate_mm_per_day"] = round(abs(s["peak_rate"]), 4)
    p["rate_alert"] = {
        "consec70_red_8033": bool(s.get("consec70_red")) if s.get("consec70_red") is not None else False,
        "sudden_jump_809": bool(s.get("sudden_jump")) if s.get("sudden_jump") is not None else False,
    }
    if ev is not None:
        p["rag_evidence"] = ev
    return p


def _write_table(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_xlsx(path, title, header, rows, summary_lines, start_date, end_date):
    """生成对齐真实日报模板的 xlsx：标题块 + 表头 + 数据 + 页脚 + 简要分析。"""
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except Exception:
        return  # 无 openpyxl 时仅产出 CSV，不阻断主流程
    ncol = len(header)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    thin = Side(style="thin", color="BBBBBB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(wrap_text=True, vertical="top")

    def put(row, text, merge=True, bold=False):
        c = ws.cell(row=row, column=1, value=text)
        if merge:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncol)
        c.alignment = wrap
        if bold:
            c.font = openpyxl.styles.Font(bold=True)

    r = 1
    put(r, "第（      ）次"); r += 1
    put(r, "工程名称：＿＿＿＿        报表编号：＿＿＿＿"); r += 1
    put(r, "天气：＿＿＿＿   观测者：＿＿＿＿   计算者：＿＿＿＿   校核者：＿＿＿＿"); r += 1
    put(r, "仪器型号：＿＿＿＿   仪器编号：＿＿＿＿   检定有效期：＿＿＿＿"); r += 1
    put(r, f"本次监测时间：{end_date}        上次监测时间：{start_date}"); r += 1
    hdr_row = r
    for c, h in enumerate(header, 1):
        cell = ws.cell(row=r, column=c, value=h)
        cell.font = openpyxl.styles.Font(bold=True)
        cell.alignment = wrap
        cell.border = border
    r += 1
    data_start = r
    for row in rows:
        for c, h in enumerate(header, 1):
            cell = ws.cell(row=r, column=c, value=row.get(h, ""))
            cell.border = border
            cell.alignment = wrap
        r += 1
    # 页脚
    put(r, "工况描述：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿"); r += 1
    put(r, "简要分析及判断性结论：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿"); r += 1
    put(r, "工程负责人：＿＿＿＿        监测单位：＿＿＿＿"); r += 1
    put(r, "第      页 共      页"); r += 1
    put(r, "简要分析及判断性结论", bold=True); r += 1
    for line in summary_lines:
        put(r, line); r += 1
    # 列宽
    for c in range(1, ncol + 1):
        ws.column_dimensions[get_column_letter(c)].width = 18
    ws.freeze_panes = ws.cell(row=data_start, column=1)
    wb.save(path)


# ------------------------------------------------------------------ self-test
SELF_TEST_CSV = """时间,地下水位-SW-01-原始值(mm),地表竖向位移-DBC-01-原始值(mm),坑底隆起-KB-01-原始值(mm),裂缝-LF-01-宽度-原始值(mm)
2026-10-15 08:00:00,100.0,-1.0,10.0,2.0
2026-10-15 08:05:00,105.0,-2.0,12.0,2.1
2026-10-15 08:10:00,110.0,-3.0,14.0,2.2
2026-10-15 08:15:00,115.0,-4.0,16.0,2.3
"""


def self_test():
    tmp = Path(__file__).parent / "_selftest.csv"
    tmp.write_text(SELF_TEST_CSV, encoding="utf-8")
    rc = evaluate(tmp, foundation="深基础", interval_minutes=5, rag_enabled=False,
                  output_dir=str(tmp.parent / "_selftest_out"))
    tmp.unlink(missing_ok=True)
    print(json.dumps(rc, ensure_ascii=False, indent=2))
    return rc[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=False)
    ap.add_argument("--foundation", default=None)
    ap.add_argument("--interval-minutes", type=int, default=5)
    ap.add_argument("--no-rag", action="store_true")
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())
    if not args.csv:
        print(json.dumps({"status": "INVALID_INPUT", "reason": "MISSING_CSV"}, ensure_ascii=False))
        sys.exit(2)
    result, code = evaluate(args.csv, foundation=args.foundation,
                            interval_minutes=args.interval_minutes,
                            rag_enabled=not args.no_rag, output_dir=args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(code)


if __name__ == "__main__":
    main()
