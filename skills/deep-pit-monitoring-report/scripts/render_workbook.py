# -*- coding: utf-8 -*-
"""把计算结果渲染为一份「日报式」监测 Excel 工作簿（单文件多 sheet）。

输出严格对应 GB 50497-2019 第 9.0.7 条与附录 A~G 表式；本脚本只做排版，
数值一律原样引用 result.json（由 compute_metrics.py / parse_appendix_excel.py 确定性计算输出），
不重算、不改写、不补值。

工作簿结构（按"监测日报_丰富版.md"形态拆分到 sheet，监测日报置于首个工作表）：
  - Sheet「监测日报」：一、工况描述；二、简要分析及判断性结论；三、待复核事项；
                        四、规范核对依据；五、签署；说明。
  - Sheet「各类监测数据结果汇总」：按附录表式分类的汇总表（含合计行）。
  - Sheet「超限测点清单」：预警信息清单（红/橙/黄排序，含"超限指标"列与判定理由；
                            红预警底部加人工确认提示）。

表单 A~F、表 G 逐表分页不在本工作簿内（日报仅保留数据结果汇总，不展开逐表报表，
与"监测日报_丰富版.md"一致）；如需逐表分页请用 render_summary.py。

用法:
  python render_workbook.py --result result.json --analysis 分析意见.json \
      --meta meta.json --out 监测日报_YYYYMMDD.xlsx

依赖: openpyxl
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    sys.stderr.write("缺少依赖 openpyxl，请先执行: pip install openpyxl\n")
    sys.exit(2)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# render_summary 已导入 render_report，故两者的公共符号都可达
from render_summary import (  # noqa: E402
    BLANK, THIN, BORDER, F_TITLE, F_HEAD, F_BODY, F_NOTE,
    CENTER, LEFT, LEVEL_FILL, LEVEL_FONT, fmt, load_json, meta_get,
)
from render_report import DEFAULT_FORM_MAP, LEVEL_MARK, over_metric, pick_form, summarize_by_form  # noqa: E402

NCOLS_SUMMARY = 10
NCOLS_OVER = 8
NCOLS_DAILY = 8          # 监测日报 sheet 用 8 列做合并排版；逐点判定依据表只占前 4 列


def style_row(ws, r, ncols, fill=None, font=None):
    for cidx in range(1, ncols + 1):
        cell = ws.cell(row=r, column=cidx)
        cell.border = BORDER
        cell.alignment = CENTER
        cell.font = font or F_BODY
        if fill:
            cell.fill = fill


def put_head(ws, r, ncols, text):
    """章节标题（合并整行，左对齐加粗）。返回下一行号。"""
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    c = ws.cell(row=r, column=1, value=text)
    c.font = F_HEAD
    c.alignment = LEFT
    return r + 1


def put_para(ws, r, ncols, text, font=None, note=False):
    """一段可换行文字（合并整行，左对齐）。按字数估算行高。返回下一行号。"""
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    cell = ws.cell(row=r, column=1, value=text)
    cell.font = (font or F_NOTE) if note else (font or F_BODY)
    cell.alignment = LEFT
    per = 56
    lines = max(1, -(-len(text) // per))  # ceil
    ws.row_dimensions[r].height = lines * 16 + 4
    return r + 1


def meta_block(ws, r, ncols, meta, result):
    """表头信息块（工程名称/报表编号/天气/监测时间/来源）。返回下一行号。"""
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    ws.cell(row=r, column=1, value="%s" % meta_get(meta, "工程名称")).font = F_HEAD
    ws.cell(row=r, column=1).alignment = LEFT
    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    ws.cell(row=r, column=1, value="第（%s）次　　报表编号：%s　　天气：%s" % (
        meta.get("序号") or "　", meta_get(meta, "报表编号"), meta_get(meta, "天气"))).font = F_BODY
    ws.cell(row=r, column=1).alignment = LEFT
    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    ws.cell(row=r, column=1, value="本次监测时间：%s　　上次监测时间：%s　　观测者：%s　　计算者：%s　　校核者：%s" % (
        meta_get(meta, "本次监测时间"), meta_get(meta, "上次监测时间"),
        meta_get(meta, "观测者"), meta_get(meta, "计算者"), meta_get(meta, "校核者"))).font = F_BODY
    ws.cell(row=r, column=1).alignment = LEFT
    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    ws.cell(row=r, column=1, value="数据来源：%s；口径：%s" % (
        result.get("数据来源", "项目监测数据文件"), result.get("数据口径", "确定性计算输出"))).font = F_NOTE
    ws.cell(row=r, column=1).alignment = LEFT
    r += 2
    return r


# --------------------------------------------------------------------------
# Sheet 一：各类监测数据结果汇总
# --------------------------------------------------------------------------
def build_summary_sheet(wb, result, meta):
    ws = wb.create_sheet("各类监测数据结果汇总")
    ncols = NCOLS_SUMMARY
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    t = ws.cell(row=1, column=1, value="各类监测数据结果汇总（草稿）")
    t.font = F_TITLE
    t.alignment = CENTER
    r = 2
    r = meta_block(ws, r, ncols, meta, result)
    r = put_head(ws, r, ncols, "各类监测数据结果汇总（按附录表式分类）")

    cols = ["测项（所属表式）", "测点数", "正常", "黄色预警", "橙色预警", "红色预警", "未判定",
            "最大|累计量|", "最大|变化速率|", "单位"]
    for cidx, name in enumerate(cols, start=1):
        cell = ws.cell(row=r, column=cidx, value=name)
        cell.font = F_HEAD
        cell.border = BORDER
        cell.alignment = CENTER
    r += 1
    by_form = {g["表式"]: g for g in (result.get("按表式汇总") or summarize_by_form(result.get("测点结果", [])))}
    for f in ["表A", "表B", "表C", "表D", "表E", "表F"]:
        g = by_form.get(f)
        if not g:
            continue
        vals = ["%s：%s" % (g["表式"], g["测项"]), g["测点数"], g.get("正常", 0), g.get("黄色", 0),
                g.get("橙色", 0), g.get("红色", 0), g.get("未判定", 0),
                fmt(g.get("最大|累计量|")), fmt(g.get("最大|变化速率|")), g.get("单位") or "—"]
        for cidx, v in enumerate(vals, start=1):
            ws.cell(row=r, column=cidx, value=v)
        style_row(ws, r, len(cols))
        if g.get("红色"):
            for cidx in range(1, len(cols) + 1):
                ws.cell(row=r, column=cidx).fill = LEVEL_FILL["红色"]
        r += 1
    st = result.get("统计", {})
    vals = ["合计", result.get("测点数", 0), st.get("正常", 0), st.get("黄色", 0),
            st.get("橙色", 0), st.get("红色", 0), st.get("未判定", 0), "", "", ""]
    for cidx, v in enumerate(vals, start=1):
        ws.cell(row=r, column=cidx, value=v)
    style_row(ws, r, len(cols), font=F_HEAD)
    r += 2

    for cidx, w in enumerate([30, 8, 8, 9, 9, 9, 9, 12, 13, 10], start=1):
        ws.column_dimensions[get_column_letter(cidx)].width = w
    return ws


# --------------------------------------------------------------------------
# Sheet 二：超限测点清单
# --------------------------------------------------------------------------
def build_overlimit_sheet(wb, result, meta):
    ws = wb.create_sheet("超限测点清单")
    ncols = NCOLS_OVER
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    t = ws.cell(row=1, column=1, value="超限测点清单（预警信息，草稿）")
    t.font = F_TITLE
    t.alignment = CENTER
    r = 2
    r = meta_block(ws, r, ncols, meta, result)
    r = put_head(ws, r, ncols, "超限测点清单（预警信息，按等级排序，便于优先核查）")

    # 测点 → 监测项目 映射（超限测点列表只带"表式"，具体测项取自测点结果）
    point_item = {}
    for p in (result.get("测点结果") or []):
        pid = p.get("point_id")
        if not pid:
            continue
        point_item[pid] = p.get("item")
        base = pid.split("@")[0]
        if base:
            point_item.setdefault(base, p.get("item"))

    def item_of(pid):
        return point_item.get(pid) or point_item.get((pid or "").split("@")[0], "—") or "—"

    cols = ["测点", "监测项目", "预警等级", "超限指标", "累计量", "单位", "变化速率", "判定理由"]
    for cidx, name in enumerate(cols, start=1):
        cell = ws.cell(row=r, column=cidx, value=name)
        cell.font = F_HEAD
        cell.border = BORDER
        cell.alignment = CENTER
    r += 1
    order = {"红色": 0, "橙色": 1, "黄色": 2}
    overs = sorted((result.get("超限测点") or []), key=lambda o: order.get((o or {}).get("等级", ""), 9))
    if overs:
        for o in overs:
            o = o or {}
            vals = [o.get("测点", "—"), item_of(o.get("测点", "")), LEVEL_MARK.get(o.get("等级", "未判定"), o.get("等级", "未判定")),
                    over_metric(o.get("理由")),
                    fmt(o.get("累计量")), o.get("单位") or "—", fmt(o.get("变化速率")), o.get("理由", "—")]
            for cidx, v in enumerate(vals, start=1):
                ws.cell(row=r, column=cidx, value=v)
            style_row(ws, r, len(cols), fill=LEVEL_FILL.get(o["等级"]), font=LEVEL_FONT.get(o["等级"]))
            ws.cell(row=r, column=8).alignment = LEFT
            r += 1
        if any(o["等级"] == "红色" for o in overs):
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
            warn = ws.cell(row=r, column=1, value="▲ 存在红色预警测点：预警正式发布与工程处置须经人工确认后按既有责任流程执行，本表不作发布。")
            warn.font = LEVEL_FONT["红色"]
            warn.alignment = LEFT
            r += 1
    else:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
        ws.cell(row=r, column=1, value="本期无测点触发项目配置的报警阈值（阈值未配置而未作判定的见待复核事项）。").font = F_BODY
        ws.cell(row=r, column=1).alignment = LEFT
        r += 1

    for cidx, w in enumerate([10, 16, 12, 12, 12, 8, 12, 60], start=1):
        ws.column_dimensions[get_column_letter(cidx)].width = w
    return ws


# --------------------------------------------------------------------------
# Sheet 监测日报：三~七 + 说明
# --------------------------------------------------------------------------
def build_daily_sheet(wb, result, meta, ana):
    ws = wb.create_sheet("监测日报")
    ncols = NCOLS_DAILY
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    t = ws.cell(row=1, column=1, value="%s 监测日报（草稿）" % meta_get(meta, "工程名称"))
    t.font = F_TITLE
    t.alignment = CENTER
    r = 2
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    ws.cell(row=r, column=1, value="报表格式依据：GB 50497-2019《建筑基坑工程监测技术标准》附录 A~G 表式；"
                                   "本件为系统辅助生成草稿，数值由确定性计算模块输出，须经编制、审核、签发程序后使用。").font = F_NOTE
    ws.cell(row=r, column=1).alignment = LEFT
    ws.row_dimensions[r].height = 32
    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    ws.cell(row=r, column=1, value="报告日期：%s　　报表编号：%s　　参与测点：%d 个　　数据来源：%s" % (
        meta_get(meta, "本次监测时间"), meta_get(meta, "报表编号"),
        len(result.get("测点结果", [])), result.get("数据来源", "项目监测数据导出文件"))).font = F_BODY
    ws.cell(row=r, column=1).alignment = LEFT
    r += 2

    # 一、工况描述
    r = put_head(ws, r, ncols, "一、工况描述")
    cond = ana.get("工况描述") or next(iter((result.get("原表工况描述") or {}).values()), None)
    cond_src = "" if ana.get("工况描述") else ("（原表已载内容，供审核参考）" if cond else "")
    r = put_para(ws, r, ncols, "%s%s" % (cond or "【待填写】", cond_src))
    r += 1

    # 二、简要分析及判断性结论
    r = put_head(ws, r, ncols, "二、简要分析及判断性结论")
    main_text = ana.get("总体分析") or next(iter((result.get("原表分析文字") or {}).values()), None)
    src = "" if ana.get("总体分析") else ("（原表已载内容，供审核参考）" if main_text else "")
    r = put_para(ws, r, ncols, "%s%s" % (main_text or "【待填写：依据已核定计算结果与适用条款撰写】", src))
    if ana.get("结论"):
        r = put_para(ws, r, ncols, "判断性结论：%s" % ana["结论"], font=F_HEAD)
    r += 1

    # 三、待复核事项
    r = put_head(ws, r, ncols, "三、待复核事项")
    pend = result.get("待复核事项", [])
    probs = result.get("数据校核问题", [])
    if pend or probs:
        for p in pend:
            for m in p["事项"]:
                r = put_para(ws, r, ncols, "- %s：%s" % (p["测点"], m))
        for q in probs:
            loc = q.get("位置") or ("第 %s 行" % q.get("行号"))
            r = put_para(ws, r, ncols, "- %s：%s（原始值：%s）→ %s" % (
                loc, q.get("问题"), q.get("原始值"), q.get("处理")))
    else:
        r = put_para(ws, r, ncols, "- 无")
    r += 1

    # 四、规范核对依据
    r = put_head(ws, r, ncols, "四、规范核对依据")
    r = put_para(ws, r, ncols,
                 "- 报告内容：依据 GB 50497-2019《建筑基坑工程监测技术标准》第 9.0.7 条，当日报表应包含天气与工况、"
                 "各测点测试值/单次变化值/变化速率/累计值、巡视检查记录、正常或异常的判断性结论，"
                 "以及达到或超过预警值测点的预警标示及分析建议。")
    forms_present = sorted({p.get("表式") or pick_form(p.get("item", "") or "", DEFAULT_FORM_MAP) for p in (result.get("测点结果") or [])})
    r = put_para(ws, r, ncols,
                 "- 表式：依据 GB 50497-2019 附录 A~G；本期涉及表式：%s。" % "、".join(forms_present))
    sources = sorted({(p.get("判定依据", {}).get("来源") or "未配置，待复核") for p in (result.get("测点结果") or [])})
    r = put_para(ws, r, ncols,
                 "- 预警分级与阈值：依托基坑智守 RAG 知识库（已集成 30 部规范）提取权威报警值，分级规则（正常 <70%% 报警值；"
                 "黄色≥70%% 报警值即“需关注”；红色≥报警值即“报警”）依据 GB 50497-2019 表 8.0.4（基坑及支护结构监测预警值）、"
                 "表 8.0.5（周边环境监测预警值）及项目《监测日报编制细则》第 4 节；控制值与橙色分级不在 RAG 规则表内，未启用。"
                 "位移/沉降/裂缝/水位类按表 8.0.4/8.0.5 绝对值判定；围护墙内力、立柱内力、支撑轴力、锚杆轴力、土压力、孔隙水压力类"
                 "按规范“报警值=设计值×比例”判定，缺设计值时标未判定并注明具体表号。本期阈值来源：%s。"
                 % ("；".join(sources) if sources else "未配置"))
    r += 1

    # 五、签署
    r = put_head(ws, r, ncols, "五、签署")
    r = put_para(ws, r, ncols, "编制：%s　　　　审核：%s　　　　签发：%s（留空待签，不得代填）" % (BLANK, BLANK, BLANK))
    r += 1

    # 说明
    r = put_head(ws, r, ncols, "说明")
    notes = [
        "1. 本报告为监测数据分析与日报编制的辅助材料，由责任人员复核后进入签发、归档流程。",
        "2. 系统仅完成异常识别与提示；正式预警发布与工程处置沿用既有责任流程，红色预警须经人工确认。",
        "3. 项目功能范围限于已有监测数据的处理、辅助分析及日报生成，不涉及现场采集，不替代责任单位出具正式监测报告。",
        "4. 表中“—”表示该字段数据源未提供或该期数据缺失，未作插值填补；标 %s 的表头字段须由填报人补充。" % BLANK,
        "5. 超限与待复核标识写入「超限测点清单」工作表与「三、待复核事项」章节；本汇总表为数据结果汇总，不展开附录表式逐表报表。",
    ]
    for ntext in notes:
        r = put_para(ws, r, ncols, ntext, note=True)

    for cidx in range(1, ncols + 1):
        ws.column_dimensions[get_column_letter(cidx)].width = 15
    return ws


def main():
    ap = argparse.ArgumentParser(description="生成日报式监测 Excel 工作簿（一/二 数据 sheet + 监测日报 sheet）")
    ap.add_argument("--result", required=True)
    ap.add_argument("--analysis", default=None)
    ap.add_argument("--meta", default=None, help="表头字段 JSON; 缺省用 result.json 中的表头信息")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    result = load_json(args.result)
    ana = load_json(args.analysis)
    meta = dict(result.get("表头信息") or {})
    meta.update(load_json(args.meta))

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    build_daily_sheet(wb, result, meta, ana)
    build_summary_sheet(wb, result, meta)
    build_overlimit_sheet(wb, result, meta)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    wb.save(args.out)
    print("监测日报工作簿已生成: %s" % os.path.abspath(args.out))
    print("sheet: %s" % "、".join(ws.title for ws in wb.worksheets))


if __name__ == "__main__":
    main()
