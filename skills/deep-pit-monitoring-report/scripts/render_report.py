# -*- coding: utf-8 -*-
"""把计算结果渲染为监测日报 Markdown 草稿，结构与 render_workbook.py 的日报式 Excel 工作簿严格对应。

文档结构（监测日报置于首节，与 render_workbook.py 三个 sheet 一一对应）：
  - 监测日报：一、工况描述；二、简要分析及判断性结论；三、待复核事项；四、规范核对依据；五、签署；说明。
  - 各类监测数据结果汇总（按附录表式分类，sheet/标题无"一、"序号前缀）。
  - 超限测点清单（预警信息，sheet/标题无"二、"序号前缀）。

数值一律原样引用 result.json，不重算、不改写、不补值；仅保留数据结果汇总，不展开逐表式详细报表。

用法:
  python render_report.py --result result.json --analysis 分析意见.json \
      --meta meta.json --out 监测日报_YYYYMMDD.md
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

# —— 以下符号被 render_summary.py / render_workbook.py 复用，须保留 ——
LEVEL_MARK = {"正常": "正常", "黄色": "黄色预警", "橙色": "橙色预警", "红色": "红色预警", "未判定": "未判定(待复核)"}
BLANK = "＿＿＿＿"

DEFAULT_FORM_MAP = {
    "order": ["表B", "表C", "表D", "表E", "表F", "表A"],
    "rules": {
        "表B": ["深层水平位移", "测斜", "深层位移"],
        "表C": ["内力", "土压力", "孔隙水压力"],
        "表D": ["支撑轴力", "锚杆轴力", "轴力"],
        "表E": ["地下水位", "水位", "地表竖向位移", "地表沉降", "分层竖向位移", "坑底隆起", "隆起"],
        "表F": ["裂缝"],
        "表A": ["水平位移", "竖向位移", "垂直位移", "墙顶", "顶部"],
    },
    "forms": {
        "表A": {"title": "表 A 水平位移、竖向位移监测日报报表", "unit": "mm"},
        "表B": {"title": "表 B 深层水平位移监测日报报表", "unit": "mm"},
        "表C": {"title": "表 C 围护墙内力、立柱内力及土压力、孔隙水压力监测日报报表", "unit": "kPa"},
        "表D": {"title": "表 D 支撑轴力、锚杆轴力监测日报报表", "unit": "kN"},
        "表E": {"title": "表 E 地下水位、地表竖向位移、分层竖向位移、坑底隆起监测日报报表", "unit": "mm"},
        "表F": {"title": "表 F 裂缝监测日报报表", "unit": "mm"},
        "表G": {"title": "表 G 巡视检查日报报表", "unit": ""},
    },
}

INSPECT_ITEMS = {  # 供 render_summary.py 的表 G 渲染复用
    "支护结构": [
        "支护结构成型质量", "冠梁、围檩、支撑的裂缝", "冠梁、围檩（腰梁）的连续性、有无过大变形",
        "围檩（腰梁）与围护桩的密贴性、围檩与支撑的防坠落措施", "锚杆垫板有无松动、变形",
        "立柱有无倾斜、沉陷或隆起", "止水帷幕有无开裂、渗漏水", "基坑有无涌土、流砂、管涌",
        "面层有无开裂、脱落", "其他",
    ],
    "施工工况": [
        "开挖后暴露的岩土体情况与岩土勘察报告有无差异", "基坑开挖分段长度及分层厚度",
        "侧壁开挖暴露面是否及时封闭", "支撑、锚杆是否施工及时",
        "边坡、侧壁及周边地表的排水、截水措施及效果，坑边或坑底有无积水",
        "基坑降水、回灌设施运转情况", "基坑周边地面堆载情况", "爆破后岩体是否出现松动",
        "吊脚桩支护形式时，岩肩处岩体有无开裂、掉块", "其他",
    ],
    "周边环境": [
        "管道破损、泄漏情况", "围护墙后土体有无沉陷、裂缝及滑移", "周边建筑有无出现裂缝、有无发展",
        "周边道路（地面）有无出现新裂缝或沉陷、有无发展", "邻近施工（堆载、开挖、打桩、降水）情况",
        "存在水力联系的邻近水体（湖泊、河流等）的水位变化情况", "其他",
    ],
    "监测设施": [
        "基准点、测点完好状况、保护情况", "监测元件及导线的完好情况、保护情况", "观测工作条件",
    ],
}


def fmt(v, nd=2):
    if v is None:
        return "—"
    try:
        return "%.*f" % (nd, float(v))
    except (TypeError, ValueError):
        return str(v)


def over_metric(reason: str):
    """从判定理由中抽取“是哪一项数据达到预警”(累计量/变化速率/本次变化量)。"""
    if not reason:
        return "—"
    m = re.match(r"(累计量|变化速率|本次变化量)", reason)
    if m:
        return m.group(1)
    if "控制值" in reason:
        return "控制值"
    if "速率限值" in reason:
        return "速率限值"
    return "—"


def meta_get(meta: dict, *keys):
    for k in keys:
        v = meta.get(k)
        if v not in (None, ""):
            return str(v)
    return BLANK


def load_json(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_form(item: str, form_map: dict):
    rules = form_map.get("rules", {})
    for form in form_map.get("order", []):
        for kw in rules.get(form, []):
            if kw and kw in item:
                return form
    return "表A"


def summarize_by_form(points):
    """按附录表式聚合: 测项数、各预警等级计数、最大|累计量|、最大|变化速率|。
    纯标准库实现, 不依赖其他脚本; result.json 已带 按表式汇总 时直接复用。
    全字段防御式取值: 残缺/手改坏的 result.json 也不崩, 缺项回退「—」/「未判定」。"""
    forms = {}
    for r in points:
        r = r or {}
        item = r.get("item") or "未注明监测项目"
        judge = r.get("判定依据") or {}
        calc = r.get("计算结果") or {}
        f = r.get("表式") or pick_form(item, DEFAULT_FORM_MAP)
        g = forms.setdefault(f, {"表式": f, "测项": [], "测点数": 0,
                                 "正常": 0, "黄色": 0, "橙色": 0, "红色": 0, "未判定": 0,
                                 "最大|累计量|": None, "最大|变化速率|": None, "单位": calc.get("单位")})
        if item not in g["测项"]:
            g["测项"].append(item)
        g["测点数"] += 1
        lv = judge.get("等级", "未判定")
        g[lv] = g.get(lv, 0) + 1
        c = calc
        if c.get("累计量") is not None:
            g["最大|累计量|"] = max(g["最大|累计量|"] or 0.0, abs(c["累计量"]))
        if c.get("变化速率") is not None:
            g["最大|变化速率|"] = max(g["最大|变化速率|"] or 0.0, abs(c["变化速率"]))
    out = []
    for f in sorted(forms):
        g = forms[f]
        g["测项"] = "、".join(g["测项"])
        out.append(g)
    return out


# --------------------------------------------------------------------------
# 一、监测日报（首节，与 render_workbook.py 的"监测日报" sheet 对应）
# --------------------------------------------------------------------------
def daily_section(result, meta, ana, L):
    L.append("## 监测日报")
    L.append("")

    # 一、工况描述
    L.append("**一、工况描述**")
    L.append("")
    cond = ana.get("工况描述") or next(iter((result.get("原表工况描述") or {}).values()), None)
    cond_src = "" if ana.get("工况描述") else ("（原表已载内容，供审核参考）" if cond else "")
    L.append(cond or "【待填写】")
    if cond_src:
        L.append(cond_src)
    L.append("")

    # 二、简要分析及判断性结论
    L.append("**二、简要分析及判断性结论**")
    L.append("")
    main_text = ana.get("总体分析") or next(iter((result.get("原表分析文字") or {}).values()), None)
    src = "" if ana.get("总体分析") else ("（原表已载内容，供审核参考）" if main_text else "")
    L.append(main_text or "【待填写：依据已核定计算结果与适用条款撰写】")
    if src:
        L.append(src)
    if ana.get("结论"):
        L.append("")
        L.append("**判断性结论：** %s" % ana["结论"])
    L.append("")

    # 三、待复核事项
    L.append("**三、待复核事项**")
    L.append("")
    pend = result.get("待复核事项", [])
    probs = result.get("数据校核问题", [])
    if pend or probs:
        for p in pend:
            for m in p["事项"]:
                L.append("- %s：%s" % (p["测点"], m))
        for q in probs:
            loc = q.get("位置") or ("第 %s 行" % q.get("行号"))
            L.append("- %s：%s（原始值：%s）→ %s" % (loc, q.get("问题"), q.get("原始值"), q.get("处理")))
    else:
        L.append("- 无")
    L.append("")

    # 四、规范核对依据（仅列规范条款/表式/阈值来源，不展开逐点判定依据表）
    L.append("**四、规范核对依据**")
    L.append("")
    L.append("- 报告内容：依据 GB 50497-2019《建筑基坑工程监测技术标准》第 9.0.7 条，当日报表应包含天气与工况、各测点测试值/单次变化值/变化速率/累计值、巡视检查记录、正常或异常的判断性结论，以及达到或超过预警值测点的预警标示及分析建议。")
    forms_present = sorted({p.get("表式") or pick_form(p.get("item", "") or "", DEFAULT_FORM_MAP) for p in (result.get("测点结果") or [])})
    L.append("- 表式：依据 GB 50497-2019 附录 A~G；本期涉及表式：%s。" % "、".join(forms_present))
    sources = sorted({(p.get("判定依据", {}).get("来源") or "未配置，待复核") for p in (result.get("测点结果") or [])})
    L.append("- 预警分级与阈值：依托基坑智守 RAG 知识库（已集成 30 部规范）提取权威报警值，分级规则（正常 <70%% 报警值；黄色≥70%% 报警值即“需关注”；红色≥报警值即“报警”）依据 GB 50497-2019 表 8.0.4（基坑及支护结构监测预警值）、表 8.0.5（周边环境监测预警值）及项目《监测日报编制细则》第 4 节；控制值与橙色分级不在 RAG 规则表内，未启用。位移/沉降/裂缝/水位类按表 8.0.4/8.0.5 绝对值判定；围护墙内力、立柱内力、支撑轴力、锚杆轴力、土压力、孔隙水压力类按规范“报警值=设计值×比例”判定，缺设计值时标未判定并注明具体表号。本期阈值来源：%s。"
             % ("；".join(sources) if sources else "未配置"))
    L.append("")

    # 五、签署
    L.append("**五、签署**")
    L.append("")
    L.append("编制：%s　　　　审核：%s　　　　签发：%s（留空待签，不得代填）" % (BLANK, BLANK, BLANK))
    L.append("")

    # 说明
    L.append("**说明**")
    L.append("")
    for n in [
        "1. 本报告为监测数据分析与日报编制的辅助材料，由责任人员复核后进入签发、归档流程。",
        "2. 系统仅完成异常识别与提示；正式预警发布与工程处置沿用既有责任流程，红色预警须经人工确认。",
        "3. 项目功能范围限于已有监测数据的处理、辅助分析及日报生成，不涉及现场采集，不替代责任单位出具正式监测报告。",
        "4. 表中“—”表示该字段数据源未提供或该期数据缺失，未作插值填补；标 %s 的表头字段须由填报人补充。" % BLANK,
        "5. 超限与待复核标识写入「超限测点清单」章节与「三、待复核事项」章节；本文档为数据结果汇总，不展开附录表式逐表报表。",
    ]:
        L.append(n)
    L.append("")


# --------------------------------------------------------------------------
# 二、各类监测数据结果汇总（与 render_workbook.py 同名 sheet 对应，标题无序号前缀）
# --------------------------------------------------------------------------
def summary_table_section(result, L):
    L.append("## 各类监测数据结果汇总")
    L.append("")
    L.append("> 按 GB 50497-2019 附录表式分类汇总；含合计行。数值原样引用 result.json。")
    L.append("")
    L.append("| 测项（所属表式） | 测点数 | 正常 | 黄色预警 | 橙色预警 | 红色预警 | 未判定 | 最大｜累计量｜ | 最大｜变化速率｜ | 单位 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    by_form = {g["表式"]: g for g in (result.get("按表式汇总") or summarize_by_form(result.get("测点结果", [])))}
    for f in ["表A", "表B", "表C", "表D", "表E", "表F"]:
        g = by_form.get(f)
        if not g:
            continue
        L.append("| %s：%s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            g["表式"], g["测项"], g["测点数"], g.get("正常", 0), g.get("黄色", 0),
            g.get("橙色", 0), g.get("红色", 0), g.get("未判定", 0),
            fmt(g.get("最大|累计量|")), fmt(g.get("最大|变化速率|")), g.get("单位") or "—"))
    st = result.get("统计", {})
    L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
        "合计", result.get("测点数", 0), st.get("正常", 0), st.get("黄色", 0),
        st.get("橙色", 0), st.get("红色", 0), st.get("未判定", 0), "", "", ""))
    L.append("")


# --------------------------------------------------------------------------
# 三、超限测点清单（与 render_workbook.py 同名 sheet 对应，标题无序号前缀）
# --------------------------------------------------------------------------
def overlimit_section(result, L):
    L.append("## 超限测点清单")
    L.append("")
    L.append('> 预警信息，按红/橙/黄排序，便于优先核查；含"超限指标"列说明是哪一项数据达到预警。')
    L.append("")
    # 测点 → 监测项目 映射（超限测点列表只带"表式"，具体测项取自测点结果）
    point_item = {}
    for p in result.get("测点结果", []):
        point_item[p["point_id"]] = p.get("item")
        base = p["point_id"].split("@")[0]
        if base:
            point_item.setdefault(base, p.get("item"))

    def item_of(pid):
        return point_item.get(pid) or point_item.get(pid.split("@")[0], "—") or "—"

    if result.get("超限测点"):
        L.append("| 测点 | 监测项目 | 预警等级 | 超限指标 | 累计量 | 单位 | 变化速率 | 判定理由 |")
        L.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        order = {"红色": 0, "橙色": 1, "黄色": 2}
        for o in sorted(result["超限测点"], key=lambda x: order.get(x.get("等级", ""), 9)):
            o = o or {}
            L.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                o.get("测点", "—"), item_of(o.get("测点", "")), LEVEL_MARK.get(o.get("等级", "未判定"), o.get("等级", "未判定")),
                over_metric(o.get("理由")),
                fmt(o.get("累计量")), o.get("单位") or "—", fmt(o.get("变化速率")), o.get("理由", "—")))
        if any(o["等级"] == "红色" for o in result["超限测点"]):
            L.append("")
            L.append("> ▲ 存在红色预警测点：预警正式发布与工程处置须经人工确认后按既有责任流程执行，本文不作发布。")
    else:
        L.append("本期无测点触发项目配置的报警阈值（阈值未配置而未作判定的测点见待复核事项）。")
    L.append("")


def main():
    ap = argparse.ArgumentParser(description="渲染监测日报 Markdown 草稿（结构对应日报式 Excel 工作簿）")
    ap.add_argument("--result", required=True)
    ap.add_argument("--analysis", default=None)
    ap.add_argument("--meta", default=None, help="表头字段 JSON; 缺省用 result.json 中的表头信息")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    r = load_json(args.result)
    ana = load_json(args.analysis)
    meta = dict(r.get("表头信息") or {})
    meta.update(load_json(args.meta))

    L = []
    L.append("# %s 监测日报（草稿）" % meta_get(meta, "工程名称"))
    L.append("")
    L.append("> 报表格式依据：GB 50497-2019《建筑基坑工程监测技术标准》附录 A~G 表式；"
             "本件为系统辅助生成草稿，数值由确定性计算模块输出，须经编制、审核、签发程序后使用。")
    L.append("")
    L.append("| 报告日期 | 报表编号 | 参与测点 | 数据来源 |")
    L.append("| --- | --- | --- | --- |")
    L.append("| %s | %s | %d 个 | %s |" % (
        meta_get(meta, "本次监测时间"), meta_get(meta, "报表编号"),
        len(r.get("测点结果", [])), r.get("数据来源", "项目监测数据导出文件")))
    L.append("")

    # 监测日报（首节）→ 各类监测数据结果汇总 → 超限测点清单，与 Excel 工作簿三个 sheet 一一对应
    daily_section(r, meta, ana, L)
    summary_table_section(r, L)
    overlimit_section(r, L)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("监测日报 Markdown 草稿已生成: %s" % os.path.abspath(args.out))


if __name__ == "__main__":
    main()
