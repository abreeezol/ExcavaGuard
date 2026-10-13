# -*- coding: utf-8 -*-
"""
gen_daily_report_rag.py — 依据已生成的《GB 50497-2019》附录数据（A~G 任意出现的附录），
调用 RAG 知识库模型检索规范阈值条款，做阈值判定，并生成监测日报(Excel)。

流程：
  1. 加载 convert_wide_to_appendix.py 输出的 result JSON（键为 附表A / 附表B / …，
     每点含 date/point/cum/delta/rate/alarm_cum/level/rule_key/rule_kind/note）。
  2. 调用 RAG 检索引擎(report_core.kb_search)对各个出现的监测项目检索
     GB 50497-2019 表8.0.4/8.0.5 报警值条款 -> 作为规范核对依据(真实模型调用)。
  3. 依各点报警值按 70%/100% 规则判定 正常/需关注/报警(红)（design_ratio 类缺设计值则未判定）。
  4. 生成工作簿：监测日报 / 各附录独立 sheet(附录表式+简要分析) / 超限测点清单。

用法：
  python scripts/gen_daily_report_rag.py
"""
from __future__ import annotations
import os, sys, json, argparse, importlib.util
from datetime import datetime

import appendix_forms as AF

# ----------------------------- 路径 -----------------------------
RAG_SRC = r"D:\weixinliaotian\xwechat_files\wxid_ktocx75p1zgc22_38d9\msg\file\2026-10\jikeng-rag(1)\jikeng-rag\source"
RESULT = r"D:\deep-pit-monitoring-report\examples\附表AB_转换_result.json"
OUT_XLSX = r"D:\deep-pit-monitoring-report\examples\监测日报_附表AB_RAG.xlsx"
OUT_JSON = r"D:\deep-pit-monitoring-report\examples\监测日报_附表AB_RAG_result.json"

# 各附录在日报/超限清单中的简短显示名
SHORT = {"A": "水平位移", "B": "深层水平位移", "C": "围护墙内力等", "D": "支撑轴力等",
         "E": "地下水位等", "F": "裂缝", "G": "巡视检查"}

RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references", "rag_alarm_rules.json")

# ----------------------------- 加载 RAG 检索引擎（可选）-----------------------------
# 真实 RAG 依赖外部 jikeng-rag 项目的 report_core + chroma_db 向量库；本机缺向量库时
# 自动回退到 rag_alarm_rules.json 内嵌的规范出处，保证日报仍可稳定生成且依据可追溯。
report_core = None
RAG_AVAILABLE = False
try:
    spec = importlib.util.spec_from_file_location("report_core", os.path.join(RAG_SRC, "report_core.py"))
    report_core = importlib.util.module_from_spec(spec)
    sys.modules["report_core"] = report_core
    spec.loader.exec_module(report_core)
    RAG_AVAILABLE = True
except Exception:
    RAG_AVAILABLE = False

def _load_rules():
    try:
        return json.load(open(os.path.abspath(RULES_PATH), encoding="utf-8"))
    except Exception:
        return {}
RULES = _load_rules()

def rule_source_of(rule_key):
    """取某测项 rule_key 在规则表中的规范出处，供超限清单'规范依据'列直接引用。"""
    r = (RULES.get("规则") or {}).get(rule_key or "", {}) or {}
    return r.get("source") or "GB 50497-2019 表8.0.4/8.0.5"

def _rule_hits_for_form(form_key, data):
    """回退：按本附表实际出现的测项 rule_key 汇总内嵌规范出处。"""
    rule_keys = set()
    for r in data.get("附表" + form_key, []):
        rk = r.get("rule_key")
        if rk:
            rule_keys.add(rk)
    hits = []
    for rk in sorted(rule_keys):
        rr = (RULES.get("规则") or {}).get(rk, {}) or {}
        src = rr.get("source") or "GB 50497-2019"
        note = rr.get("note") or ""
        hits.append({"score": 1.0, "source": src, "clause": "", "content": (note or src)})
    if not hits:
        name_cn = AF.APPENDIX_FORMS.get(form_key, {}).get("name_cn", "")
        hits = [{"score": 1.0, "source": "GB 50497-2019 表8.0.4/8.0.5", "clause": "", "content": name_cn}]
    return hits

def build_evidence(forms, data):
    """阈值依据：优先真实 RAG 检索；不可用时回退到 rag_alarm_rules.json 内嵌规范出处。"""
    ev = {}
    for key, short, _ in forms:
        item_cn = AF.APPENDIX_FORMS[key]["name_cn"]
        q = "建筑基坑工程监测技术标准 GB 50497-2019 表8.0.4 表8.0.5 报警值 %s 累计变化 变化速率 监测预警" % item_cn
        hits = []
        if RAG_AVAILABLE:
            try:
                hits = report_core.kb_search(q, topk=4)
            except Exception:
                hits = []
        if not hits:
            hits = _rule_hits_for_form(key, data)
        ev[short] = hits
    ev["报警值基准"] = [{"score": 1.0, "source": "GB 50497-2019 表8.0.4", "clause": "",
                         "content": "基坑及支护结构监测预警值；内力/轴力/土压力/孔隙水类报警值=设计值×比例（表8.0.4）"}]
    return ev

# ----------------------------- 判定 -----------------------------
def judge(cum, alarm):
    return AF.judge(cum, alarm)

LEVEL_FILL = {"正常": "C6EFCE", "需关注": "FFEB9C", "报警": "FFC7CE", "未判定": "D9D9D9"}
LEVEL_FONT = {"正常": "006100", "需关注": "9C6500", "报警": "9C0006", "未判定": "3F3F3F"}

# ----------------------------- 主流程 -----------------------------
def main():
    global RESULT, OUT_XLSX, OUT_JSON
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", default=RESULT, help="convert 输出的 result JSON 路径")
    ap.add_argument("--out", default=OUT_XLSX, help="输出日报 xlsx 路径")
    ap.add_argument("--out-json", default=OUT_JSON, help="输出判定 JSON 路径")
    ap.add_argument("--md", action="store_true",
                    help="同时导出两份 Markdown：仅『监测日报』封面 sheet 一份 + 其余 sheet（附表及清单）一份")
    ap.add_argument("--md-cover", default=None, help="封面 Markdown 输出路径（默认 <stem>_封面.md）")
    ap.add_argument("--md-rest", default=None, help="附表及清单 Markdown 输出路径（默认 <stem>_附表及清单.md）")
    args = ap.parse_args()
    RESULT, OUT_XLSX, OUT_JSON = args.result, args.out, args.out_json

    data = json.load(open(RESULT, encoding="utf-8"))
    # 动态识别出现的附录
    forms = [(k[-1], SHORT.get(k[-1], k), AF.APPENDIX_FORMS.get(k[-1], {}).get("sheet_title", k))
             for k in data.keys() if k.startswith("附表")]
    forms = [f for f in forms if f[0] in AF.APPENDIX_FORMS]
    if not forms:
        raise SystemExit("result JSON 中未发现 附表A~附表G 数据")
    forms.sort(key=lambda x: x[0])

    rag_ev = build_evidence(forms, data)
    print("=== 阈值依据（%s）===" % ("真实 RAG 检索" if RAG_AVAILABLE else "rag_alarm_rules.json 内嵌规范出处（RAG 向量库未就位）"))
    for item, hits in rag_ev.items():
        print(f"[{item}] 命中 {len(hits)} 条")
        for h in hits:
            print(f"   score {h['score']:.3f} | {h['source']} | 条款 {h['clause'] or '-'}")

    all_dates = [r["date"] for key, _, _ in forms for r in data.get("附表" + key, [])]
    latest_date = max(all_dates) if all_dates else "—"
    out = {"生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "数据来源": os.path.basename(RESULT), "末次监测日期": latest_date,
           "RAG依据": {k: [{"score": h["score"], "source": h["source"], "clause": h["clause"], "content": h["content"]} for h in v] for k, v in rag_ev.items()},
           "各类监测数据结果汇总": {}, "超限测点清单": [], "统计": {}}

    stats = {f[1]: {"正常": 0, "需关注": 0, "报警": 0, "未判定": 0} for f in forms}
    over_list = []

    for key, short, sheet_cn in forms:
        rows = data.get("附表" + key, [])
        pts = {}
        for r in rows:
            pts.setdefault(r["point"], []).append(r)
        summary_rows = []
        for pid, recs in pts.items():
            recs.sort(key=lambda x: x["date"])
            last = recs[-1]
            lvl, ratio = judge(last["cum"], last["alarm_cum"])
            stats[short][lvl] += 1
            summary_rows.append({**last, "level": lvl, "ratio": ratio})
            if lvl in ("需关注", "报警"):
                over_list.append({
                    "测点": pid, "监测项目": short, "末次监测日期": last["date"],
                    "末次累计量": last["cum"], "单位": AF.APPENDIX_FORMS[key]["unit"],
                    "报警值": last["alarm_cum"], "占报警值(%)": ratio,
                    "变化速率": round(last["rate"], 2), "预警等级": lvl,
                    "规范依据": rule_source_of(last.get("rule_key")),
                })
        out["各类监测数据结果汇总"]["附表" + key] = {
            "监测项目": short, "末日汇总": summary_rows,
            "全序列天数": len(next(iter(pts.values()))) if pts else 0,
        }
    out["超限测点清单"] = over_list
    out["统计"] = stats

    any_alarm = any(s["报警"] > 0 for s in stats.values())
    any_watch = any(s["需关注"] > 0 for s in stats.values())
    overall = "报警" if any_alarm else ("需关注" if any_watch else "正常")
    out["综合判定"] = overall
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # ----------------------------- 写 Excel -----------------------------
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    wb = openpyxl.Workbook()
    thin = Side(style="thin", color="B0B0B0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    hdr_fill = PatternFill("solid", fgColor="4472C4")
    hdr_font = Font(bold=True, color="FFFFFF")
    title_font = Font(bold=True, size=14, color="1F3864")
    sec_font = Font(bold=True, size=11, color="1F3864")
    wrap = Alignment(wrap_text=True, vertical="top")
    center = Alignment(horizontal="center", vertical="center")

    def style_header(ws, row, ncol):
        for c in range(1, ncol + 1):
            cell = ws.cell(row=row, column=c)
            cell.fill = hdr_fill; cell.font = hdr_font; cell.alignment = center; cell.border = border

    # ===== Sheet 1: 监测日报 =====
    ws = wb.active
    ws.title = "监测日报"
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 92
    title_items = "、".join(f"{short}" for _, short, _ in forms)
    ws["A1"] = "监测日报（基坑监测 · RAG 阈值判定 · 含 %s）" % title_items
    ws["A1"].font = title_font
    ws.merge_cells("A1:B1")

    meta = [("工程名称", "（示例数据，待填）"), ("监测日期", latest_date),
            ("基坑安全等级", "一级/二级/三级，按测点与 design_ratio 设计值映射"),
            ("天气", "（待填）"), ("当日施工工况", "（示例数据，模拟土方开挖阶段；实际工况待补充）")]
    r = 3
    for k, v in meta:
        ws.cell(r, 1, k).font = Font(bold=True)
        ws.cell(r, 2, v).alignment = wrap
        r += 1

    r += 1
    ws.cell(r, 1, "一、工况描述").font = sec_font; r += 1
    ws.cell(r, 1, "内容"); ws.cell(r, 2, "说明")
    ws.cell(r, 1).font = Font(bold=True); ws.cell(r, 2).font = Font(bold=True); r += 1
    ws.cell(r, 1, "开挖/施工进展"); ws.cell(r, 2, "示例数据模拟连续监测期，10 分钟级高频采样；实际工况请以施工日志为准。").alignment = wrap; r += 1
    ws.cell(r, 1, "监测范围"); ws.cell(r, 2, "本次生成附录：%s。" % "、".join(AF.APPENDIX_FORMS[k]["sheet_title"] for k, _, _ in forms)).alignment = wrap; r += 1

    r += 1
    ws.cell(r, 1, "二、简要分析及判断性结论").font = sec_font; r += 1
    lines = [f"本期综合判定：{overall}。"]
    for short, st in stats.items():
        lines.append(f"· {short}：正常 {st['正常']} 点、需关注 {st['需关注']} 点、报警 {st['报警']} 点、未判定 {st['未判定']} 点。")
    if any_alarm:
        lines.append("存在红色报警测点，累计量已达或超过规范报警值，建议按 GB 50497-2019 第 8.0.9 条启动预警程序、加密监测并组织复核。")
    elif any_watch:
        lines.append("存在黄色需关注测点（累计≥70%报警值），建议提高监测频率并加强巡视。")
    else:
        lines.append("各测点累计量与变化速率均处于报警值 70% 以内，未见异常。")
    for ln in lines:
        ws.cell(r, 1, "·"); ws.cell(r, 2, ln).alignment = wrap; r += 1

    r += 1
    ws.cell(r, 1, "三、待复核事项").font = sec_font; r += 1
    todos = []
    if any_alarm:
        todos.append("红色报警测点须由责任工程师人工复核并签字确认（本报告仅作识别，未替代责任判定）。")
    red_rate = [o for o in over_list if isinstance(o["变化速率"], (int, float)) and o["变化速率"] >= 2.0 and o["预警等级"] != "报警"]
    if red_rate:
        todos.append("部分测点变化速率≥2（单位/天），达到速率关注阈值，建议核查坑边荷载与降水。")
    if any(k == "B" for k, _, _ in forms):
        todos.append("附录B 深层水平位移原始数据未含分层深度，日报深度列以“—”表示，须核对原始测斜记录后补充分层值。")
    if any(k in ("C", "D") for k, _, _ in forms):
        todos.append("附录C/D 内力、轴力类为 design_ratio 口径，报警值=设计值×比例；若缺设计值相关测点标“未判定”，须补设计值后重判。")
    todos.append("红色/黄色预警结论最终须由建设、监理、施工单位按责任流程确认后方可发布。")
    for t in todos:
        ws.cell(r, 1, "□"); ws.cell(r, 2, t).alignment = wrap; r += 1

    r += 1
    ws.cell(r, 1, "四、规范核对依据（%s）" % ("RAG 知识库检索" if RAG_AVAILABLE else "rag_alarm_rules.json 内嵌规范出处")).font = sec_font; r += 1
    if not RAG_AVAILABLE:
        ws.cell(r, 1, "说明"); ws.cell(r, 2, "本机 RAG 向量库未就位，以下规范依据取自 rag_alarm_rules.json 内嵌的 GB 50497-2019 表8.0.4/8.0.5 出处，与阈值判定口径一致；接入向量库后将自动切换为真实条款检索。").alignment = wrap; r += 1
    ws.cell(r, 1, "检索主题"); ws.cell(r, 2, "检索到的规范条款（来源 / 条款 / 摘录）")
    ws.cell(r, 1).font = Font(bold=True); ws.cell(r, 2).font = Font(bold=True); r += 1
    for short, hits in rag_ev.items():
        parts = ["《%s》条款 %s（相关度 %.2f）：%s" % (h["source"], h["clause"] or "-", h["score"], h["content"][:140]) for h in hits]
        ws.cell(r, 1, short).alignment = wrap
        ws.cell(r, 2, "\n".join(parts)).alignment = wrap
        r += 1
    ws.cell(r, 1, "判定口径"); ws.cell(r, 2, "累计量占比：正常 < 70% 报警值；需关注（黄）70%~100%；报警（红）≥ 100% 报警值。报警值取自 GB 50497-2019 表8.0.4/8.0.5；内力/轴力类为设计值×比例。").alignment = wrap; r += 1

    r += 1
    ws.cell(r, 1, "五、签署").font = sec_font; r += 1
    for role in ["测试人", "计算人", "校核人", "审核人", "项目负责人"]:
        ws.cell(r, 1, role); ws.cell(r, 2, "________________"); r += 1

    # ===== 各附录独立 sheet（附录表式 + 简要分析及判断性结论）=====
    def form_analysis(ws, rr, form_key, short, rows, latest_date):
        f = AF.APPENDIX_FORMS[form_key]
        pts = {}
        for x in rows:
            pts.setdefault(x["point"], []).append(x)
        last_recs = []
        for pid, recs in pts.items():
            recs.sort(key=lambda z: z["date"])
            last_recs.append(recs[-1])
        dates = [r["date"] for r in rows]
        n = len(last_recs)
        n_normal = n_watch = n_alarm = n_und = 0
        alarm_pts, watch_pts, fast_pts = [], [], []
        for rec in last_recs:
            lvl, ratio = judge(rec["cum"], rec["alarm_cum"])
            pid = rec["point"]
            if lvl == "正常":
                n_normal += 1
            elif lvl == "需关注":
                n_watch += 1; watch_pts.append((pid, rec["cum"], ratio))
            elif lvl == "报警":
                n_alarm += 1; alarm_pts.append((pid, rec["cum"], rec["alarm_cum"], ratio))
            else:
                n_und += 1
            if isinstance(rec.get("rate"), (int, float)) and rec["rate"] >= 2.0:
                fast_pts.append((pid, round(rec["rate"], 2)))
        fo = "报警" if n_alarm else ("需关注" if n_watch else ("正常" if n_und == 0 else "需关注"))

        ws.cell(rr, 1, "简要分析及判断性结论").font = sec_font
        rr += 1
        ls = []
        ls.append("· 本附表共 %d 个测点（%s），监测期 %s ~ %s（末次监测日 %s）。本期综合判定：%s。" % (
            n, short, min(dates), max(dates), latest_date, fo))
        ls.append("· 末次监测日统计：正常 %d 点、需关注(黄色) %d 点、报警(红色) %d 点、未判定 %d 点。" % (n_normal, n_watch, n_alarm, n_und))
        if alarm_pts:
            ls.append("· 红色报警测点（累计量已达/超报警值）：" + "；".join(
                "%s 累计 %.1f / 报警值 %s / 占 %s%%" % (p, c, ("%.0f" % a) if a else "未配置", r) for p, c, a, r in alarm_pts))
        if watch_pts:
            ls.append("· 需关注(黄色)测点（累计≥报警值 70%）：" + "；".join(
                "%s 累计 %.1f / 占 %s%%" % (p, c, r) for p, c, r in watch_pts))
        if fast_pts:
            if form_key in ("C", "D"):
                hint = "建议核查内力/轴力变化速率"
            elif form_key == "F":
                hint = "建议核查裂缝发展速率"
            else:
                hint = "建议核查坑边荷载与降水情况"
            ls.append("· 变化速率较大（≥2 单位/天）的测点：%s，%s。" % ("、".join("%s %.2f" % (p, rt) for p, rt in fast_pts), hint))
        if n_und:
            ls.append("· 未判定测点：内力/轴力/土压力/孔隙水类报警值=设计值×比例（表8.0.4），缺设计值无法量化，须补设计值后重判。")
        if fo == "报警":
            conc = "结论：存在红色报警测点，累计量已达或超过 GB 50497-2019 表 8.0.4/8.0.5 报警值，建议按第 8.0.9 条启动预警程序、加密监测并组织复核。"
        elif fo == "需关注":
            conc = "结论：各测点累计量未超报警值，但已达报警值 70% 以上，建议提高监测频率并加强巡视。"
        else:
            conc = "结论：各测点累计量与变化速率均处于报警值 70% 以内，未见异常。"
        if form_key == "B":
            conc += "注：本附表为深层水平位移，原始数据未含分层深度，深度列以占位符表示，须核对原始测斜记录后补充分层值。"
        ls.append(conc)
        width = len(f["columns"])
        for ln in ls:
            c = ws.cell(rr, 1, ln); c.alignment = wrap
            ws.merge_cells(start_row=rr, start_column=1, end_row=rr, end_column=width)
            rr += 1
        return rr

    for key, short, sheet_cn in forms:
        f = AF.APPENDIX_FORMS[key]
        ws2 = wb.create_sheet(sheet_cn)
        width = len(f["columns"])
        for i, line in enumerate(f["header_lines"], start=1):
            ws2.cell(row=i, column=1, value=line)
            if width > 1:
                ws2.merge_cells(start_row=i, start_column=1, end_row=i, end_column=width)
        hrow = len(f["header_lines"]) + 1
        for j, c in enumerate(f["columns"], start=1):
            cell = ws2.cell(row=hrow, column=j, value=c)
            cell.font = Font(bold=True); cell.alignment = center
            cell.fill = PatternFill("solid", fgColor="DDEBF7"); cell.border = border
        rr = hrow + 1
        for rec in data.get("附表" + key, []):
            vals = AF.render_row(key, rec, f["unit"])
            for j, v in enumerate(vals, start=1):
                ws2.cell(row=rr, column=j, value=v).border = border
            ncell = ws2.cell(row=rr, column=width)
            lvl = rec.get("level", "正常")
            ncell.fill = PatternFill("solid", fgColor=AF.LEVEL_FILL.get(lvl, "FFFFFF"))
            ncell.font = Font(color=AF.LEVEL_FONT.get(lvl, "000000"), bold=(lvl in ("报警", "未判定")))
            rr += 1
        # 表尾
        fr = rr + 1
        for i, line in enumerate(f["footer_lines"], start=1):
            ws2.cell(row=fr + i, column=1, value=line)
            if width > 1:
                ws2.merge_cells(start_row=fr + i, start_column=1, end_row=fr + i, end_column=width)
        # 简要分析（表尾之后）
        form_analysis(ws2, fr + len(f["footer_lines"]) + 2, key, short, data.get("附表" + key, []), latest_date)
        ws2.column_dimensions["A"].width = 14
        for col in "BCDEFGHI":
            if col <= openpyxl.utils.get_column_letter(width):
                ws2.column_dimensions[col].width = 14
        ws2.column_dimensions[openpyxl.utils.get_column_letter(width)].width = 46
        ws2.freeze_panes = ws2.cell(row=hrow + 1, column=1)

    # ===== 超限测点清单 =====
    ws3 = wb.create_sheet("超限测点清单")
    ocols = ["测点", "监测项目", "末次监测日期", "末次累计量", "单位", "报警值", "占报警值(%)", "变化速率", "预警等级", "规范依据"]
    for i, h in enumerate(ocols, 1):
        ws3.cell(1, i, h)
    style_header(ws3, 1, len(ocols))
    ws3.column_dimensions["A"].width = 12
    ws3.column_dimensions["B"].width = 14
    ws3.column_dimensions["C"].width = 14
    ws3.column_dimensions["I"].width = 40
    if not over_list:
        ws3.cell(2, 1, "本期无超限（需关注/报警）测点。")
    else:
        for o in over_list:
            rr = ws3.max_row + 1
            for i, k in enumerate(ocols, 1):
                cell = ws3.cell(rr, i, o[k]); cell.border = border
                if k == "预警等级":
                    lvl = o[k]
                    cell.fill = PatternFill("solid", fgColor=LEVEL_FILL[lvl])
                    cell.font = Font(color=LEVEL_FONT[lvl], bold=True); cell.alignment = center
                if k == "规范依据":
                    cell.alignment = wrap
    wb.save(OUT_XLSX)
    print(f"\n已生成：{OUT_XLSX}")
    print(f"综合判定：{overall}；统计：{stats}")

    if getattr(args, "md", False):
        import export_daily_report_md as EXP_MD
        EXP_MD.export(OUT_XLSX, cover_sheet="监测日报",
                      out_cover=args.md_cover, out_rest=args.md_rest)

if __name__ == "__main__":
    main()
