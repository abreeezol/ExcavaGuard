# -*- coding: utf-8 -*-
"""把解析/判定结果渲染为一份监测数据汇总表(.xlsx)。

输入为 parse_appendix_excel.py(附录表式 Excel 数据)或 compute_metrics.py(CSV 流水数据)
输出的 result.json。表式以 GB 50497-2019 附录 A~G 为基准, 按项目需要做了如下
格式修改(在"汇总"页说明中列明):
  1. 各表增加"预警等级"列(附录表式本身无此列);
  2. 表 B 增加"点号"列(原表式点号在表头, 逐深度分行后需逐行对应);
  3. 超限与待复核信息除写入"备注"列外, 在"汇总"页集中列示。

保留: 预警信息、工况描述、简要分析及判断性结论、编制/审核/签发栏(留空待签)。

用法:
  python render_summary.py --result result.json --analysis 分析意见.json \
      --meta meta.json --out 监测数据汇总表_20261009.xlsx

职责边界:
  - 数值一律原样引用 result.json, 不重算、不改写、不补值。
  - 分析文字由 --analysis 提供; 缺省时引用原表已载内容并标注来源; 均无则留占位, 不代写结论。
  - 编制/审核/签发栏留空, 不代填人名。

依赖: openpyxl
"""
from __future__ import annotations

import argparse
import json
import os
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
from render_report import DEFAULT_FORM_MAP, INSPECT_ITEMS, LEVEL_MARK, pick_form, over_metric  # noqa: E402

BLANK = "＿＿＿＿"

THIN = Side(style="thin", color="999999")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
F_TITLE = Font(bold=True, size=14)
F_HEAD = Font(bold=True, size=10)
F_BODY = Font(size=10)
F_NOTE = Font(size=9, color="666666")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)

LEVEL_FILL = {
    "红色": PatternFill("solid", fgColor="FFC7CE"),
    "橙色": PatternFill("solid", fgColor="FFE0B2"),
    "黄色": PatternFill("solid", fgColor="FFF2CC"),
}
LEVEL_FONT = {"红色": Font(bold=True, size=10, color="9C0006")}

FORM_COLUMNS = {
    "表A": ["点号", "监测项目", "累计位移量(mm)", "本次变化量(mm)", "变化速率(mm/d)", "预警等级", "备注"],
    "表B": ["点号", "深度(m)", "累计位移(mm)", "本次变化量(mm)", "变化速率(mm/d)", "预警等级", "备注"],
    "表C": ["组号", "点号", "深度(m)", "本次测值(kPa)", "上次测值(kPa)", "本次变化(kPa)", "累计变化(kPa)", "预警等级", "备注"],
    "表D": ["组号", "点号", "深度(m)", "本次测值(kN)", "上次测值(kN)", "本次变化(kN)", "累计变化(kN)", "预警等级", "备注"],
    "表E": ["编号", "点号", "监测项目", "初始高程(m)", "本次高程(m)", "上次高程(m)",
            "本次变化量(mm)", "累计变化量(mm)", "变化速率(mm/d)", "预警等级", "备注"],
    "表F": ["点号", "长度-本次测试值(mm)", "长度-单次变化(mm)", "长度-累计变化量(mm)", "长度-变化速率(mm/d)",
            "宽度-本次测试值(mm)", "宽度-单次变化(mm)", "宽度-累计变化量(mm)", "宽度-变化速率(mm/d)",
            "形态", "预警等级", "备注"],
    "表CD": ["组号", "点号", "深度(m)", "本次测值", "上次测值", "本次变化", "累计变化", "预警等级", "备注"],
}


def fmt(v, nd=2):
    if v is None:
        return "—"
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return v


def load_json(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def meta_get(meta, key):
    v = meta.get(key)
    return str(v) if v not in (None, "") else BLANK


def remark_of(p):
    parts = []
    if p["状态标记"].get("待复核"):
        parts.append("；".join(p["状态标记"]["待复核"]))
    raw_rmk = (p.get("原始数据") or {}).get("备注")
    if raw_rmk:
        parts.append(str(raw_rmk))
    return "；".join(parts) if parts else "—"


def row_values(form, p):
    c = p["计算结果"]
    raw = p.get("原始数据") or {}
    lv = p["判定依据"]["等级"]
    mark = LEVEL_MARK.get(lv, lv)
    rmk = remark_of(p)
    if form == "表A":
        return [p["point_id"], p["item"], fmt(c.get("累计量")), fmt(c.get("本次变化量")),
                fmt(c.get("变化速率")), mark, rmk]
    if form == "表B":
        hole, _, _depth = p["point_id"].partition("@")
        return [hole, fmt(raw.get("深度")), fmt(c.get("累计量")), fmt(c.get("本次变化量")),
                fmt(c.get("变化速率")), mark, rmk]
    if form in ("表C", "表D", "表CD"):
        return [raw.get("组号") or "—", p["point_id"], fmt(raw.get("深度")),
                fmt(raw.get("本次测值")), fmt(raw.get("上次测值")),
                fmt(c.get("本次变化量")), fmt(c.get("累计量")), mark, rmk]
    if form == "表E":
        return [raw.get("编号") or "—", p["point_id"], p["item"],
                fmt(raw.get("初始高程"), 3), fmt(raw.get("本次高程"), 3), fmt(raw.get("上次高程"), 3),
                fmt(c.get("本次变化量")), fmt(c.get("累计量")), fmt(c.get("变化速率")), mark, rmk]
    if form == "表F":
        L, W = raw.get("长度") or {}, raw.get("宽度") or {}
        return [p["point_id"], fmt(L.get("本次"), 1), fmt(L.get("单次变化"), 1), fmt(L.get("累计"), 1), fmt(L.get("速率")),
                fmt(W.get("本次"), 2), fmt(W.get("单次变化"), 2), fmt(W.get("累计"), 2), fmt(W.get("速率")),
                raw.get("形态") or "—", mark, rmk]
    return [p["point_id"], fmt(c.get("累计量")), fmt(c.get("本次变化量")), fmt(c.get("变化速率")), mark, rmk]


def style_row(ws, r, ncols, fill=None, font=None):
    for cidx in range(1, ncols + 1):
        cell = ws.cell(row=r, column=cidx)
        cell.border = BORDER
        cell.alignment = CENTER
        cell.font = font or F_BODY
        if fill:
            cell.fill = fill


def write_header_block(ws, r, form, meta, ncols):
    """附录表式固定表头区。"""
    def put(text):
        nonlocal r
        ws.cell(row=r, column=1, value=text).font = F_BODY
        ws.cell(row=r, column=1).alignment = LEFT
        r += 1
    put("第（%s）次" % (meta.get("序号") or "　"))
    put("工程名称：%s　　　报表编号：%s　　　天气：%s" % (
        meta_get(meta, "工程名称"), meta_get(meta, "报表编号"), meta_get(meta, "天气")))
    if form == "表G":
        put("观测者：%s　　　巡视时间：%s" % (meta_get(meta, "观测者"), meta_get(meta, "本次监测时间")))
    else:
        put("观测者：%s　　　计算者：%s　　　校核者：%s" % (
            meta_get(meta, "观测者"), meta_get(meta, "计算者"), meta_get(meta, "校核者")))
        put("仪器型号：%s　　　仪器编号：%s　　　检定有效期：%s" % (
            meta_get(meta, "仪器型号"), meta_get(meta, "仪器编号"), meta_get(meta, "检定有效期")))
        put("本次监测时间：%s　　　上次监测时间：%s" % (
            meta_get(meta, "本次监测时间"), meta_get(meta, "上次监测时间")))
    return r


def write_tail_block(ws, r, form, meta, ana, result, ncols):
    """表尾: 工况描述 / 简要分析及判断性结论 / 签署栏。文字来源按优先级并标注。"""
    form_ana = (ana.get("表式分析") or {}).get(form, {})
    cond = form_ana.get("工况描述") or ana.get("工况描述")
    cond_src = ""
    if not cond:
        cond = (result.get("原表工况描述") or {}).get(form)
        cond_src = "（原表已载内容，供审核参考）" if cond else ""
    cond = cond or "【待填写】"

    own = bool(form_ana.get("简要分析及判断性结论"))
    main_text = form_ana.get("简要分析及判断性结论") or ana.get("总体分析")
    src = ""
    if own:
        conclusion = form_ana.get("结论") or ana.get("结论")
    elif main_text:
        conclusion = ana.get("结论")
        src = "（本栏沿用总体分析，未提供 %s 专属文字，审核时请按本表测项核对）" % form
    else:
        main_text = (result.get("原表分析文字") or {}).get(form)
        conclusion = ana.get("结论")
        src = "（原表已载内容，供审核参考）" if main_text else ""
    main_text = (main_text or "【待填写：依据已核定计算结果与适用条款撰写】") + src

    def put(text, bold=False, note=None):
        nonlocal r
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
        cell = ws.cell(row=r, column=1, value=text)
        cell.font = F_HEAD if bold else F_BODY
        cell.alignment = LEFT
        r += 1
        if note:
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
            c2 = ws.cell(row=r, column=1, value=note)
            c2.font = F_NOTE
            c2.alignment = LEFT
            r += 1

    put("工况描述：%s%s" % (cond, cond_src))
    put("简要分析及判断性结论：%s" % main_text)
    if conclusion:
        put("判断性结论：%s" % conclusion)
    r += 1
    put("工程负责人：%s　　　　　监测单位：%s　　　　　第 　 页 共 　 页" % (BLANK, BLANK))
    put("编制：%s　　　　　审核：%s　　　　　签发：%s（留空待签，不得代填）" % (BLANK, BLANK, BLANK))
    return r


def build_form_sheet(wb, form, points, meta, ana, result):
    title = DEFAULT_FORM_MAP["forms"].get(form, {}).get("title") or ("表 %s 监测日报报表" % form[-1])
    ws = wb.create_sheet(form)
    ncols = len(FORM_COLUMNS.get(form, FORM_COLUMNS["表A"]))
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    t = ws.cell(row=1, column=1, value="%s（汇总表·格式修改版）" % title)
    t.font = F_TITLE
    t.alignment = CENTER
    r = write_header_block(ws, 2, form, meta, ncols)
    r += 1
    # 主表
    cols = FORM_COLUMNS.get(form, FORM_COLUMNS["表A"])
    for cidx, name in enumerate(cols, start=1):
        cell = ws.cell(row=r, column=cidx, value=name)
        cell.font = F_HEAD
        cell.border = BORDER
        cell.alignment = CENTER
    head_row = r
    r += 1
    for p in points:
        vals = row_values(form, p)
        for cidx, v in enumerate(vals, start=1):
            ws.cell(row=r, column=cidx, value=v)
        lv = p["判定依据"]["等级"]
        style_row(ws, r, len(cols), fill=LEVEL_FILL.get(lv), font=LEVEL_FONT.get(lv))
        r += 1
    ws.freeze_panes = ws.cell(row=head_row + 1, column=1)
    r += 1
    r = write_tail_block(ws, r, form, meta, ana, result, ncols)
    # 列宽
    for cidx, name in enumerate(cols, start=1):
        ws.column_dimensions[get_column_letter(cidx)].width = max(10, min(40, len(str(name)) * 2 + 4))
    ws.column_dimensions[get_column_letter(len(cols))].width = 42  # 备注列加宽
    return ws


def build_inspect_sheet(wb, meta, ana, result):
    ws = wb.create_sheet("表G")
    ncols = 4
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    t = ws.cell(row=1, column=1, value="表 G 巡视检查日报报表（汇总表）")
    t.font = F_TITLE
    t.alignment = CENTER
    r = write_header_block(ws, 2, "表G", meta, ncols)
    r += 1
    for cidx, name in enumerate(["分类", "巡视检查内容", "巡视检查结果", "备注"], start=1):
        cell = ws.cell(row=r, column=cidx, value=name)
        cell.font = F_HEAD
        cell.border = BORDER
        cell.alignment = CENTER
    r += 1
    # 输入 Excel 中的巡视记录优先, 未覆盖项按规范附录 G 清单留空
    given = {}
    for k, v in (result.get("巡视检查记录") or {}).items():
        given[k] = v
    for k, v in (ana.get("巡视检查") or {}).items():
        given.setdefault(k, {"结果": v.get("结果", ""), "备注": v.get("备注", "")})
    for cat, items in INSPECT_ITEMS.items():
        for i, it in enumerate(items):
            g = given.get(it) or {}
            ws.cell(row=r, column=1, value=cat if i == 0 else "")
            ws.cell(row=r, column=2, value=it)
            ws.cell(row=r, column=3, value=g.get("结果", ""))
            ws.cell(row=r, column=4, value=g.get("备注", ""))
            style_row(ws, r, ncols)
            r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    note = ws.cell(row=r, column=1, value="注：巡视检查结论须由现场巡视人员确认；清单按 GB 50497-2019 附录 G，"
                                          "本系统不代填、不推断（第 9.0.7 条第 3 款：当日报表应包括巡视检查的记录）。")
    note.font = F_NOTE
    note.alignment = LEFT
    r += 2
    r = write_tail_block(ws, r, "表G", meta, ana, result, ncols)
    for cidx, w in enumerate([12, 46, 30, 18], start=1):
        ws.column_dimensions[get_column_letter(cidx)].width = w
    return ws


def build_summary_sheet(wb, result, meta, ana):
    ws = wb.create_sheet("汇总", 0)
    ncols = 10
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    t = ws.cell(row=1, column=1, value="%s监测数据汇总表（草稿）" % meta_get(meta, "工程名称"))
    t.font = F_TITLE
    t.alignment = CENTER
    r = 2
    ws.cell(row=r, column=1, value="第（%s）次　　报表编号：%s　　天气：%s" % (
        meta.get("序号") or "　", meta_get(meta, "报表编号"), meta_get(meta, "天气"))).font = F_BODY
    r += 1
    ws.cell(row=r, column=1, value="本次监测时间：%s　　上次监测时间：%s　　观测者：%s　　计算者：%s　　校核者：%s" % (
        meta_get(meta, "本次监测时间"), meta_get(meta, "上次监测时间"),
        meta_get(meta, "观测者"), meta_get(meta, "计算者"), meta_get(meta, "校核者"))).font = F_BODY
    r += 1
    ws.cell(row=r, column=1, value="数据来源：%s；口径：%s" % (
        result.get("数据来源", "项目监测数据文件"), result.get("数据口径", "确定性计算输出"))).font = F_NOTE
    r += 2

    def section(name):
        nonlocal r
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
        c = ws.cell(row=r, column=1, value=name)
        c.font = F_HEAD
        c.alignment = LEFT
        r += 1

    # 1. 按表式汇总
    section("一、各类监测数据结果汇总（按附录表式分类）")
    cols1 = ["测项（所属表式）", "测点数", "正常", "黄色预警", "橙色预警", "红色预警", "未判定",
             "最大|累计量|", "最大|变化速率|", "单位"]
    for cidx, name in enumerate(cols1, start=1):
        cell = ws.cell(row=r, column=cidx, value=name)
        cell.font = F_HEAD
        cell.border = BORDER
        cell.alignment = CENTER
    r += 1
    for g in result.get("按表式汇总", []):
        vals = ["%s：%s" % (g["表式"], g["测项"]), g["测点数"], g.get("正常", 0), g.get("黄色", 0),
                g.get("橙色", 0), g.get("红色", 0), g.get("未判定", 0),
                fmt(g.get("最大|累计量|")), fmt(g.get("最大|变化速率|")), g.get("单位") or "—"]
        for cidx, v in enumerate(vals, start=1):
            ws.cell(row=r, column=cidx, value=v)
        style_row(ws, r, len(cols1))
        if g.get("红色"):
            for cidx in range(1, len(cols1) + 1):
                ws.cell(row=r, column=cidx).fill = LEVEL_FILL["红色"]
        r += 1
    st = result.get("统计", {})
    vals = ["合计", result.get("测点数", 0), st.get("正常", 0), st.get("黄色", 0),
            st.get("橙色", 0), st.get("红色", 0), st.get("未判定", 0), "", "", ""]
    for cidx, v in enumerate(vals, start=1):
        ws.cell(row=r, column=cidx, value=v)
    style_row(ws, r, len(cols1), font=F_HEAD)
    r += 2

    # 2. 超限测点(预警信息)
    section("二、超限测点清单（预警信息，按等级排序，便于优先核查）")
    cols2 = ["测点", "监测项目", "预警等级", "超限指标", "累计量", "单位", "变化速率", "判定理由"]
    for cidx, name in enumerate(cols2, start=1):
        cell = ws.cell(row=r, column=cidx, value=name)
        cell.font = F_HEAD
        cell.border = BORDER
        cell.alignment = CENTER
    r += 1
    # 测点 → 监测项目 映射（超限测点列表只带"表式"，具体测项取自测点结果）
    point_item = {}
    for p in result.get("测点结果", []):
        point_item[p["point_id"]] = p.get("item")
        base = p["point_id"].split("@")[0]
        if base:
            point_item.setdefault(base, p.get("item"))
    def item_of(pid):
        return point_item.get(pid) or point_item.get(pid.split("@")[0], "—") or "—"
    order = {"红色": 0, "橙色": 1, "黄色": 2}
    overs = sorted(result.get("超限测点", []), key=lambda o: order.get(o["等级"], 9))
    if overs:
        for o in overs:
            vals = [o["测点"], item_of(o["测点"]), LEVEL_MARK.get(o["等级"], o["等级"]),
                    over_metric(o.get("理由")),
                    fmt(o.get("累计量")), o.get("单位") or "—", fmt(o.get("变化速率")), o.get("理由", "—")]
            for cidx, v in enumerate(vals, start=1):
                ws.cell(row=r, column=cidx, value=v)
            style_row(ws, r, len(cols2), fill=LEVEL_FILL.get(o["等级"]), font=LEVEL_FONT.get(o["等级"]))
            ws.cell(row=r, column=8).alignment = LEFT
            r += 1
        if any(o["等级"] == "红色" for o in overs):
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
            warn = ws.cell(row=r, column=1, value="▲ 存在红色预警测点：预警正式发布与工程处置须经人工确认后按既有责任流程执行，本表不作发布。")
            warn.font = LEVEL_FONT["红色"]
            warn.alignment = LEFT
            r += 1
    else:
        ws.cell(row=r, column=1, value="本期无测点触发项目配置的报警阈值（阈值未配置而未作判定的见待复核事项）。").font = F_BODY
        r += 1
    r += 1

    # 3. 待复核事项
    section("三、待复核事项")
    pend = result.get("待复核事项", [])
    probs = result.get("数据校核问题", [])
    if pend or probs:
        for p in pend:
            for m in p["事项"]:
                ws.cell(row=r, column=1, value="%s：%s" % (p["测点"], m)).font = F_BODY
                r += 1
        for q in probs:
            loc = q.get("位置") or ("第 %s 行" % q.get("行号"))
            ws.cell(row=r, column=1, value="%s：%s（原始值：%s）→ %s" % (
                loc, q.get("问题"), q.get("原始值"), q.get("处理"))).font = F_BODY
            r += 1
    else:
        ws.cell(row=r, column=1, value="无").font = F_BODY
        r += 1
    r += 1

    # 4. 工况描述 / 5. 简要分析及判断性结论
    section("四、工况描述")
    cond = ana.get("工况描述") or next(iter((result.get("原表工况描述") or {}).values()), None)
    cond_src = "" if ana.get("工况描述") else ("（原表已载内容，供审核参考）" if cond else "")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    ws.cell(row=r, column=1, value="%s%s" % (cond or "【待填写】", cond_src)).font = F_BODY
    ws.cell(row=r, column=1).alignment = LEFT
    r += 2

    section("五、简要分析及判断性结论")
    main_text = ana.get("总体分析") or next(iter((result.get("原表分析文字") or {}).values()), None)
    src = "" if ana.get("总体分析") else ("（原表已载内容，供审核参考）" if main_text else "")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    ws.cell(row=r, column=1, value="%s%s" % (main_text or "【待填写：依据已核定计算结果与适用条款撰写】", src)).font = F_BODY
    ws.cell(row=r, column=1).alignment = LEFT
    r += 1
    if ana.get("结论"):
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
        ws.cell(row=r, column=1, value="判断性结论：%s" % ana["结论"]).font = F_HEAD
        ws.cell(row=r, column=1).alignment = LEFT
        r += 1
    r += 1

    # 6. 签署
    section("六、签署")
    ws.cell(row=r, column=1, value="编制：%s　　　　审核：%s　　　　签发：%s（留空待签，不得代填）" % (
        BLANK, BLANK, BLANK)).font = F_BODY
    r += 2

    # 7. 说明
    section("七、说明")
    notes = [
        "1. 本表为监测数据分析与日报编制的辅助材料，由责任人员复核后进入签发、归档流程，不替代责任单位出具的正式监测报告。",
        "2. 表式以 GB 50497-2019 附录 A~G 为基准，格式修改：①各表增加“预警等级”列；②表 B 增加“点号”列；③超限与待复核信息写入“备注”列并在本页集中列示。",
        "3. 指标值原样引用填报数据或确定性计算输出，系统未重新推算；判定阈值以项目专项监测方案为准，未配置阈值的一律不作判定。",
        "4. 系统仅完成异常识别与提示；红色预警须经人工确认，正式预警发布与工程处置沿用既有责任流程。",
        "5. 表中“—”表示该字段数据源未提供或该期数据缺失，未作插值填补；标 %s 的字段须由填报人补充。" % BLANK,
    ]
    for ntext in notes:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
        c = ws.cell(row=r, column=1, value=ntext)
        c.font = F_NOTE
        c.alignment = LEFT
        r += 1

    for cidx, w in enumerate([30, 8, 8, 9, 9, 9, 9, 12, 13, 10], start=1):
        ws.column_dimensions[get_column_letter(cidx)].width = w
    return ws


def main():
    ap = argparse.ArgumentParser(description="生成监测数据汇总表(xlsx, 附录表式·格式修改版)")
    ap.add_argument("--result", required=True)
    ap.add_argument("--analysis", default=None)
    ap.add_argument("--meta", default=None, help="表头字段 JSON; 缺省用 result.json 中的表头信息")
    ap.add_argument("--form-map", default=None)
    ap.add_argument("--no-form-g", action="store_true", help="不输出表G(巡视检查)sheet")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    result = load_json(args.result)
    ana = load_json(args.analysis)
    meta = dict(result.get("表头信息") or {})
    meta.update(load_json(args.meta))
    form_map = load_json(args.form_map) or DEFAULT_FORM_MAP

    groups = {}
    for p in result.get("测点结果", []):
        form = p.get("表式") or pick_form(p["item"], form_map)
        groups.setdefault(form, []).append(p)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    build_summary_sheet(wb, result, meta, ana)
    for form in [f for f in ["表A", "表B", "表C", "表D", "表CD", "表E", "表F"] if f in groups]:
        build_form_sheet(wb, form, groups[form], meta, ana, result)
    if not args.no_form_g:
        build_inspect_sheet(wb, meta, ana, result)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    wb.save(args.out)
    print("汇总表已生成: %s" % os.path.abspath(args.out))
    print("sheet: %s" % "、".join(ws.title for ws in wb.worksheets))


if __name__ == "__main__":
    main()
