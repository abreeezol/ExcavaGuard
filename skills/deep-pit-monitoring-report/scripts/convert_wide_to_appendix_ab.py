# -*- coding: utf-8 -*-
"""convert_wide_to_appendix.py（通用版，覆盖附录 A~G）

把"不符合 GB 50497-2019 附录表式"的宽表监测数据
（首列时间戳 + 各测点"累计量"列，仅含累计量，10 分钟/次级高频采样）
按规范要求**总结整理**为附录 A~G 各自的监测日报表格式，并输出一个 Excel 工作簿。

转换口径（确定性，由脚本计算，不手工推算）：
  * 累计变化   = 当日末次采样的累计值（即当日末的累计量）
  * 本次变化量 = 当日末次累计 − 前一日末次累计（首日为 当日末 − 当日首）
  * 变化速率   = 本次变化量 / 报告间隔天数（间隔按前后两次采样日期差计算，通常为 1d）
  * 预警等级   = 按 RAG 报警值规则表（GB 50497-2019 表 8.0.4 / 表 8.0.5）对"累计量占报警值比例"判定：
                正常 < 70%；黄色(需关注) 70%~100%；红色(报警) ≥ 100%
                absolute 类取规范绝对值；design_ratio 类（内力/轴力/土压力/孔隙水）报警值=设计值×比例，
                缺设计值标「未判定」并注明表号（不再写"需专项监测方案确认"）

宽表 -> 附录归属：点号首字母 A~G；或 sheet 名含 深层/内力/轴力/水位/裂缝/巡视 等关键词。

输出：
  * 一个 xlsx 工作簿：每个实际出现的附录一个「附表X_…监测日报表」sheet + 「处理与判定说明」sheet
  * 可选 --out-json 输出计算结果 JSON（每个数字均来自本脚本计算，可追溯）

依赖：openpyxl（pip install openpyxl）；附录模板见 appendix_forms.py（本目录）
"""
import argparse, json, os, datetime, re
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import appendix_forms as AF

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ---- 列名解析 ----
def parse_point_id(header):
    h = (header or "").strip()
    if not h:
        return None
    h = re.sub(r"[\(（].*?[\)）]", "", h).strip()
    if not h:
        return None
    return h


def is_datetime(v):
    return isinstance(v, (datetime.datetime, datetime.date))


def load_wide_points(path):
    """扫描工作簿所有 sheet，找出宽表（含时间列 + 多个数值列），
    返回 {point_id: [(datetime, value), ...]} 与 {point_id: 附录代号}。"""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    series, form_of = {}, {}
    for ws in wb.worksheets:
        data = list(ws.iter_rows(values_only=True))
        if not data:
            continue
        header = data[0]
        if not header:
            continue
        ncols = len(header)
        sample = data[1:9]
        if not sample:
            continue
        time_col = None
        num_cols = []
        for c in range(ncols):
            vals = [r[c] for r in sample if r is not None and c < len(r)]
            if vals and sum(1 for v in vals if is_datetime(v)) >= max(1, len(vals) * 0.6):
                time_col = c
                break
        if time_col is None:
            continue
        for c in range(ncols):
            if c == time_col:
                continue
            vals = [r[c] for r in sample if r is not None and c < len(r)]
            if vals and sum(1 for v in vals if isinstance(v, (int, float))) >= max(1, len(vals) * 0.6):
                num_cols.append(c)
        if not num_cols:
            continue
        for c in num_cols:
            pid = parse_point_id(header[c])
            if not pid:
                continue
            form = AF.resolve_form(pid, ws.title)
            if pid not in series:
                series[pid] = []
                form_of[pid] = form
            for r in data[1:]:
                if c < len(r) and is_datetime(r[time_col]) and isinstance(r[c], (int, float)):
                    series[pid].append((r[time_col], float(r[c])))
    for pid in series:
        series[pid].sort(key=lambda x: x[0])
    return series, form_of


# ---- 每日汇总 ----
def daily_summary(series):
    if not series:
        return []
    by_day = {}
    for ts, v in series:
        d = ts.date() if isinstance(ts, datetime.datetime) else ts
        by_day[d] = (ts, v)
    days = sorted(by_day.keys())
    out, prev_end = [], None
    for i, d in enumerate(days):
        ts_end, cum_end = by_day[d]
        if prev_end is None:
            first_of_day = next(v for t, v in series if (t.date() if isinstance(t, datetime.datetime) else t) == d)
            base = first_of_day
            base_ts = next(t for t, v in series if (t.date() if isinstance(t, datetime.datetime) else t) == d)
            delta = cum_end - base
            ddays = max(((ts_end - base_ts).total_seconds() / 86400.0), 1e-9)
        else:
            base = prev_end
            base_ts = prev_ts
            delta = cum_end - base
            ddays = max(((ts_end - base_ts).total_seconds() / 86400.0), 1e-9)
        rate = delta / ddays
        out.append((d, cum_end, base, delta, rate))
        prev_end, prev_ts = cum_end, ts_end
    return out


def load_rules(path):
    if not path or not os.path.exists(path):
        return None
    return json.load(open(path, "r", encoding="utf-8"))


# ---- Excel 渲染（基于 appendix_forms 模板）----
def write_form_sheet(wb, form_key, meta, rows):
    f = AF.APPENDIX_FORMS[form_key]
    ws = wb.create_sheet(f["sheet_title"])
    thin = Side(style="thin", color="B0B0B0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center")
    width = len(f["columns"])

    # 表头块
    for i, line in enumerate(f["header_lines"], start=1):
        ws.cell(row=i, column=1, value=line)
        if width > 1:
            ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=width)
    hrow = len(f["header_lines"]) + 1
    for j, c in enumerate(f["columns"], start=1):
        cell = ws.cell(row=hrow, column=j, value=c)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.fill = PatternFill("solid", fgColor="DDEBF7")
        cell.border = border
    # 数据行
    r = hrow + 1
    for rec in rows:
        vals = AF.render_row(form_key, rec, f["unit"])
        for j, v in enumerate(vals, start=1):
            cell = ws.cell(row=r, column=j, value=v)
            cell.border = border
            if j == 1:
                cell.alignment = center
        # 备注列（最后一列）等级底色
        ncell = ws.cell(row=r, column=width)
        lvl = rec.get("level", "正常")
        ncell.fill = PatternFill("solid", fgColor=AF.LEVEL_FILL.get(lvl, "FFFFFF"))
        ncell.font = Font(color=AF.LEVEL_FONT.get(lvl, "000000"), bold=(lvl in ("报警", "未判定")))
        r += 1
    # 表尾
    for i, line in enumerate(f["footer_lines"], start=1):
        ws.cell(row=r + i, column=1, value=line)
        if width > 1:
            ws.merge_cells(start_row=r + i, start_column=1, end_row=r + i, end_column=width)
    # 列宽（通用：首列+末列宽，中间均分）
    ws.column_dimensions["A"].width = 14
    for col in "BCDEFGHI":
        if col <= openpyxl.utils.get_column_letter(width):
            ws.column_dimensions[col].width = 14
    ws.column_dimensions[openpyxl.utils.get_column_letter(width)].width = 46
    ws.freeze_panes = ws.cell(row=hrow + 1, column=1)
    return ws


def write_notes_sheet(wb, level, rules_src, point_alarm_used, point_design_used, stats, forms_present):
    ws = wb.create_sheet("处理与判定说明")
    lines = [
        ("输入数据形态", ""),
        ("", "原始数据为「宽表」：首列为时间戳，其余每列一个测点的「累计量」；采样频率 10 分钟/次，持续 1 周；仅含累计量，不含本次变化量/变化速率/上次测值。不符合 GB 50497-2019 附录表式。"),
        ("本次生成的附录表式", "、".join(AF.APPENDIX_FORMS[k]["sheet_title"] for k in forms_present)),
        ("转换与计算方法（由脚本确定性计算，非手工推算）", ""),
        ("", "1) 累计变化 = 当日末次采样的累计值；"),
        ("", "2) 本次变化量 = 当日末次累计 − 前一日末次累计（首日为 当日末 − 当日首）；"),
        ("", "3) 变化速率 = 本次变化量 / 报告间隔天数（间隔取前后两次采样日期差，通常为 1d）；"),
        ("", "4) 上述三项均由 convert_wide_to_appendix.py 计算，原始数据中无此三项（内力/轴力类「本次测值/上次测值」亦由累计序列端点推算，注明于备注）。"),
        ("阈值与预警判定依据", ""),
        ("", "阈值/报警值来源：%s（GB 50497-2019 表 8.0.4 / 表 8.0.5；依托基坑智守 RAG 知识库 30 部规范）。" % rules_src),
        ("", "所选基坑安全等级：%s。" % level),
        ("", "预警等级划分（按累计量占报警值比例）：正常 < 70%；黄色(需关注) 70%~100%；红色(报警) ≥ 100%。"),
        ("", "absolute 类取规范绝对值；design_ratio 类（围护墙内力/立柱内力/土压力/孔隙水/支撑轴力/锚杆轴力）报警值=设计值×比例，缺设计值标「未判定」并注明表号，不写「需专项监测方案确认」。"),
        ("各附表预警统计（按末日累计量判定）", ""),
    ]
    for k in forms_present:
        s = stats[k]
        lines.append(("  %s" % AF.APPENDIX_FORMS[k]["sheet_title"],
                      "共 %d 点：正常 %d / 黄色(需关注) %d / 红色(报警) %d / 未判定 %d"
                      % (s["total"], s["正常"], s["需关注"], s["报警"], s["未判定"])))
    if point_alarm_used:
        lines.append(("点号→累计报警值(mm)映射", ""))
        for kk, vv in point_alarm_used.items():
            lines.append(("  %s" % kk, "%s mm" % vv))
    if point_design_used:
        lines.append(("点号→设计值(供 design_ratio 报警值计算)映射", ""))
        for kk, vv in point_design_used.items():
            lines.append(("  %s" % kk, "%s" % vv))
    lines.append(("声明", ""))
    lines.append(("", "1) 本次变化量/变化速率由累计序列推算，非原始测值，正式报表须核对原始记录后采用；"))
    lines.append(("", "2) 红色(报警) 仅作识别与提示，正式发布与处置按既有责任流程由人工确认；"))
    lines.append(("", "3) 表头工程名称/观测者/仪器编号/检定有效期等字段留空待填，未编造；签署栏待签；本报告辅助材料，须经审核签发。"))

    r = 1
    for a, b in lines:
        ca = ws.cell(row=r, column=1, value=a)
        cb = ws.cell(row=r, column=2, value=b)
        if b == "" and a:
            ca.font = Font(bold=True)
        cb.alignment = Alignment(wrap_text=True, vertical="top")
        r += 1
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 92
    return ws


# ---- 主流程 ----
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", nargs="+", required=True,
                    help="宽表输入 xlsx（首列时间，其余为各点累计量）；"
                         "可同时传入多个文件，按点号合并后输出到同一个工作簿（各附录仍各自成 sheet）")
    ap.add_argument("--rules", default=os.path.join(SCRIPT_DIR, "..", "references", "rag_alarm_rules.json"))
    ap.add_argument("--level", type=int, default=1, choices=[1, 2, 3], help="基坑安全等级（默认一级）")
    ap.add_argument("--point-alarm", default=None, help="可选 JSON：点号->累计报警值(mm)，覆盖 absolute 类 RAG 取值")
    ap.add_argument("--point-rate", default=None, help="可选 JSON：点号->速率报警值")
    ap.add_argument("--point-design", default=None, help="可选 JSON：点号->设计值，供 design_ratio 类(内力/轴力/土压力/孔隙水)计算报警值")
    ap.add_argument("--out", required=True, help="输出 xlsx 路径")
    ap.add_argument("--out-json", default=None, help="可选：输出计算结果 JSON 路径")
    args = ap.parse_args()

    point_alarm = json.load(open(args.point_alarm, encoding="utf-8")) if args.point_alarm else None
    point_rate = json.load(open(args.point_rate, encoding="utf-8")) if args.point_rate else None
    point_design = json.load(open(args.point_design, encoding="utf-8")) if args.point_design else None
    rules = load_rules(args.rules)
    rules_obj = (rules or {}).get("规则", {})
    rules_src = (rules or {}).get("来源说明", "RAG 报警值规则表（GB 50497-2019 表 8.0.4/8.0.5）")
    if isinstance(rules_src, str) and len(rules_src) > 60:
        rules_src = "RAG 报警值规则表（GB 50497-2019 表 8.0.4/8.0.5，依托基坑智守 RAG 知识库 30 部规范）"

    # 支持多份宽表：按点号合并（同一点号以样本更多的人为准），
    # 使附录 A~F 即使来自不同数据文件也输出到同一个工作簿的不同 sheet
    series, form_of = {}, {}
    for path in args.excel:
        s, f = load_wide_points(path)
        for pid, vals in s.items():
            if pid not in series or len(vals) > len(series[pid]):
                series[pid] = vals
                form_of[pid] = f[pid]
    if not series:
        raise SystemExit("未在输入文件中识别到宽表监测数据（需含时间列 + 数值列）")

    rows_by_form = {}
    stats = {}
    json_out = {"说明": "由 convert_wide_to_appendix.py 生成；数值均由累计序列确定性计算"}

    for pid in sorted(series.keys()):
        form_key = form_of[pid]
        rule_key = AF.resolve_rule_key(form_key, pid)
        rule = rules_obj.get(rule_key) if rule_key else None
        design = (point_design or {}).get(pid) if point_design else None
        # 报警值
        if (point_alarm or {}).get(pid) is not None:
            alarm_cum, anote = (point_alarm[pid]), ""
            rule_kind = "absolute"
        else:
            alarm_cum, anote = AF.compute_alarm(rule, args.level, design)
            rule_kind = (rule or {}).get("type", "absolute")
        al_rate = None
        if (point_rate or {}).get(pid) is not None:
            al_rate = point_rate[pid]

        daily = daily_summary(series[pid])
        form_rows = rows_by_form.setdefault(form_key, [])
        if form_key not in stats:
            stats[form_key] = {"total": 0, "正常": 0, "需关注": 0, "报警": 0, "未判定": 0}
        jkey = "附表%s" % form_key
        json_out.setdefault(jkey, [])

        for (d, cum, base, delta, rate) in daily:
            lvl, ratio = AF.judge(cum, alarm_cum)
            extra = anote if lvl == "未判定" else ""
            note = AF.level_note(lvl, alarm_cum, ratio, unit=AF.APPENDIX_FORMS[form_key]["unit"], extra=extra)
            if al_rate is not None:
                note += "；变化速率 %.2f /报警 %.0f" % (rate, al_rate)
            rec = {"date": d.isoformat() if hasattr(d, "isoformat") else str(d),
                   "point": pid, "cum": cum, "delta": delta, "rate": rate, "base": base,
                   "level": lvl, "ratio": ratio, "alarm_cum": alarm_cum,
                   "rule_key": rule_key, "rule_kind": rule_kind, "note": note}
            form_rows.append(rec)
            json_out[jkey].append(rec)
        # 末日统计
        if daily:
            lvl, _ = AF.judge(daily[-1][1], alarm_cum)
            stats[form_key]["total"] += 1
            if lvl in stats[form_key]:
                stats[form_key][lvl] += 1
            else:
                stats[form_key]["未判定"] += 1

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    forms_present = [k for k in AF.all_keys() if rows_by_form.get(k)]
    for k in forms_present:
        write_form_sheet(wb, k, {}, rows_by_form[k])
    write_notes_sheet(wb, "%d 级" % args.level, rules_src, point_alarm or {}, point_design or {}, stats, forms_present)
    wb.save(args.out)
    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as fh:
            json.dump(json_out, fh, ensure_ascii=False, indent=2)
    print("SAVED", args.out)
    print("各附录点数:", {k: len(v) for k, v in rows_by_form.items()})
    print("统计", json.dumps({k: stats[k] for k in forms_present}, ensure_ascii=False))


if __name__ == "__main__":
    main()
