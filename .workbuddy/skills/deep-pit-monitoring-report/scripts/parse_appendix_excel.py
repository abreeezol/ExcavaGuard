# -*- coding: utf-8 -*-
"""解析按 GB 50497-2019 附录 A~G 表式整理、集中在一个 Excel 文件中的监测数据。

用法:
  python parse_appendix_excel.py --excel 监测数据.xlsx --config 阈值配置.json \
      --date 2026-10-09 --out result.json

职责边界:
  - 只做解析、确定性校核与分级判定: 识别各 sheet / 表块对应的附录表式,
    原样读取累计量/本次变化量/变化速率(不重新推算指标), 做表内一致性校核
    (如 高程差 vs 变化量), 按项目阈值配置分级。
  - 不做原因分析、不写分析文字、不补阈值、不插值填补缺失值。
  - 原表中已载的工况描述/简要分析文字原样带出并标注来源, 供审核人员参考,
    不视为系统结论。
  - 输出结构与 compute_metrics.py 的 result.json 兼容, 并附加表式与表头信息。

依赖: openpyxl (pip install openpyxl)
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
except ImportError:
    sys.stderr.write("缺少依赖 openpyxl，请先执行: pip install openpyxl\n")
    sys.exit(2)

# 复用既有计算模块的分级与阈值逻辑, 保持判定口径唯一
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compute_metrics import classify, get_threshold, to_float  # noqa: E402

LEVEL_ORDER = ["正常", "黄色", "橙色", "红色", "未判定"]

# 各表式默认测项名与单位(列头括号单位优先, 此处为兜底)
FORM_INFO = {
    "表A": {"item": "水平/竖向位移", "unit": "mm"},
    "表B": {"item": "深层水平位移", "unit": "mm"},
    "表C": {"item": "围护墙/立柱内力及土压力、孔隙水压力", "unit": "kPa"},
    "表D": {"item": "支撑/锚杆轴力", "unit": "kN"},
    "表E": {"item": "地下水位/竖向位移/坑底隆起", "unit": "mm"},
    "表F": {"item": "裂缝", "unit": "mm"},
    "表G": {"item": "巡视检查", "unit": ""},
}

# 表头区字段(附录表式固定表头)
META_KEYS = ["工程名称", "报表编号", "天气", "观测者", "计算者", "校核者",
             "仪器型号", "仪器编号", "检定有效期", "本次监测时间", "上次监测时间"]

# 数据区终止标志(表尾固定内容)
TAIL_MARKS = ("工况描述", "简要分析", "判断性结论", "工程负责人", "监测单位", "第 　 页", "第 页 共")


def cell_text(v):
    if v is None:
        return ""
    return str(v).strip()


def norm_header(text):
    """列名归一: 去括号、空白与连字符, 用于特征匹配。"""
    t = re.sub(r"[（(].*?[)）]", "", cell_text(text))
    return re.sub(r"[\s\-—–_]+", "", t)


def header_unit(text):
    m = re.search(r"[（(]([^)）]+)[)）]", cell_text(text))
    return m.group(1).strip() if m else None


def detect_form(headers):
    """按列名特征识别附录表式。headers 为归一后的列名列表。"""
    joined = "|".join(headers)
    s = set(headers)
    if any("巡视检查内容" in h for h in s):
        return "表G"
    if "形态" in s and ("长度" in joined or "宽度" in joined or "本次测试值" in joined):
        return "表F"
    if "初始高程" in joined:
        return "表E"
    if "组号" in s or ("本次测值" in joined and "累计变化" in joined):
        return "表CD"  # C/D 待定, 由单位或标题区分
    if any(h.startswith("深度") for h in s) and "累计位移" in joined.replace("量", ""):
        return "表B"
    if "点号" in s and "累计位移" in joined.replace("量", ""):
        return "表A"
    return None


def split_form_cd(headers_raw, sheet_title):
    """表C/表D 区分: 优先列头单位, 其次标题关键字。"""
    joined = "|".join(cell_text(h) for h in headers_raw)
    title = sheet_title or ""
    if "kN" in joined or "轴力" in title:
        return "表D"
    if "kPa" in joined or "内力" in title or "土压力" in title or "孔隙水压力" in title:
        return "表C"
    return "表CD"  # 无法区分时保留标记, 交给待复核


# 各表式列名 -> 标准字段 的匹配规则(归一列名包含匹配, 按优先级)
COLUMN_RULES = {
    "表A": [("点号", "point_id"), ("累计位移", "累计量"), ("本次变化", "本次变化量"),
            ("变化速率", "变化速率"), ("监测项目", "item"), ("备注", "备注")],
    "表B": [("深度", "深度"), ("累计位移", "累计量"), ("本次变化", "本次变化量"),
            ("变化速率", "变化速率"), ("备注", "备注")],
    "表CD": [("组号", "组号"), ("点号", "point_id"), ("深度", "深度"), ("本次测值", "本次测值"),
             ("上次测值", "上次测值"), ("本次变化", "本次变化量"), ("累计变化", "累计量"),
             ("监测项目", "item"), ("备注", "备注")],
    "表E": [("编号", "编号"), ("点号", "point_id"), ("初始高程", "初始高程"), ("本次高程", "本次高程"),
            ("上次高程", "上次高程"), ("本次变化", "本次变化量"), ("累计变化", "累计量"),
            ("变化速率", "变化速率"), ("监测项目", "item"), ("备注", "备注")],
    "表F": [("点号", "point_id"), ("形态", "形态"), ("备注", "备注")],
    "表G": [("分类", "分类"), ("巡视检查内容", "内容"), ("巡视检查结果", "结果"), ("备注", "备注")],
}

# 表F 长度/宽度分项列(归一列名 -> 字段)
F_SUBCOLS = {
    "长度本次测试值": "长度_本次", "长度单次变化": "长度_单次变化",
    "长度累计变化": "长度_累计", "长度变化速率": "长度_速率",
    "宽度本次测试值": "宽度_本次", "宽度单次变化": "宽度_单次变化",
    "宽度累计变化": "宽度_累计", "宽度变化速率": "宽度_速率",
}


def map_columns(headers_raw, form):
    """返回 {字段: 列下标} 与 {字段: 单位}。"""
    rules = COLUMN_RULES["表CD" if form in ("表C", "表D", "表CD") else form]
    col_map, units = {}, {}
    for i, h in enumerate(headers_raw):
        nh = norm_header(h)
        if not nh:
            continue
        u = header_unit(h)
        for key, field in rules:
            if key in nh and field not in col_map:
                col_map[field] = i
                if u:
                    units[field] = u
                break
        else:
            if form == "表F":
                for key, field in F_SUBCOLS.items():
                    if key in nh:
                        col_map[field] = i
                        if u:
                            units[field] = u
                        break
    return col_map, units


def parse_meta_block(rows):
    """从表头区行提取固定表头字段(合并单元格按左上角取值)。"""
    meta = {}
    pat = re.compile(r"(%s)\s*[：:]\s*([^|]*)" % "|".join(META_KEYS))
    seq = None
    for row in rows:
        texts = [cell_text(c) for c in row if cell_text(c)]
        line = "|".join(texts)
        m = re.search(r"第[（(]\s*(.*?)\s*[)）]\s*次", line)
        if m and m.group(1):
            seq = m.group(1)
        for m in pat.finditer(line):
            k, v = m.group(1), m.group(2).strip(" |")
            if v and k not in meta:
                meta[k] = v
    if seq:
        meta["序号"] = seq
    return meta


def row_is_tail(row):
    line = "|".join(cell_text(c) for c in row if cell_text(c))
    return any(mark in line for mark in TAIL_MARKS)


def extract_tail_text(rows):
    """提取表尾 工况描述 / 简要分析及判断性结论 原文(若有)。"""
    cond, anal = [], []
    mode = None
    for row in rows:
        texts = [cell_text(c) for c in row if cell_text(c)]
        line = " ".join(texts)
        if not line:
            continue
        if "工况描述" in line:
            mode = "cond"
            cond.append(re.sub(r"^.*?工况描述\s*[：:]\s*", "", line))
            continue
        if "简要分析" in line or "判断性结论" in line:
            mode = "anal"
            anal.append(re.sub(r"^.*?(简要分析及?判断性结论|判断性结论)\s*[：:]\s*", "", line))
            continue
        if any(k in line for k in ("工程负责人", "监测单位", "第 　 页", "第 页 共")):
            mode = None
            continue
        if mode == "cond":
            cond.append(line)
        elif mode == "anal":
            anal.append(line)
    return "\n".join(t for t in cond if t), "\n".join(t for t in anal if t)


def close(a, b, tol=0.02):
    if a is None or b is None:
        return True
    return abs(a - b) <= max(tol, abs(b) * 0.005)


def check_consistency(form, vals, flags, sheet, excel_row):
    """表内一致性校核: 只做确定性比较, 不改写任何数值。"""
    loc = "sheet「%s」第 %d 行" % (sheet, excel_row)
    if form in ("表C", "表D", "表CD"):
        cur, prev, delta = vals.get("本次测值"), vals.get("上次测值"), vals.get("本次变化量")
        if cur is not None and prev is not None and delta is not None:
            if not close(cur - prev, delta):
                flags.append("本次变化 %s 与 测值差(本次-上次) %s 不一致(%s), 需核对原始记录"
                             % (round(delta, 3), round(cur - prev, 3), loc))
    if form == "表E":
        hc, hp, h0 = vals.get("本次高程"), vals.get("上次高程"), vals.get("初始高程")
        delta, cum = vals.get("本次变化量"), vals.get("累计量")
        # 高程单位为 m, 变化量栏目为 mm, 差值换算后比较
        if hc is not None and hp is not None and delta is not None:
            if not close((hc - hp) * 1000.0, delta, tol=0.5) and not close((hp - hc) * 1000.0, delta, tol=0.5):
                flags.append("本次变化量 %s mm 与 高程差 %.3g mm 不一致(%s), 需核对原始记录" % (delta, abs(hc - hp) * 1000.0, loc))
        if hc is not None and h0 is not None and cum is not None:
            if not close((hc - h0) * 1000.0, cum, tol=0.5) and not close((h0 - hc) * 1000.0, cum, tol=0.5):
                flags.append("累计变化量 %s mm 与 高程差 %.3g mm 不一致(%s), 需核对原始记录" % (cum, abs(hc - h0) * 1000.0, loc))
    if form == "表F":
        for dim in ("长度", "宽度"):
            cur, delta = vals.get("%s_本次" % dim), vals.get("%s_单次变化" % dim)
            cum, rate = vals.get("%s_累计" % dim), vals.get("%s_速率" % dim)
            if cur is not None and delta is not None and cum is not None and rate is not None:
                pass  # 单项均存在即可, 表F 无上期值列, 不做交叉校核


def val_of(row, col_map, units, field, sheet, excel_row, flags, want_num=True):
    idx = col_map.get(field)
    if idx is None:
        return None
    raw_v = cell_text(row[idx]) if idx < len(row) else ""
    if raw_v in ("", "—", "-", "/", "— —"):
        return None
    if not want_num:
        return raw_v
    v = to_float(raw_v)
    if v is None:
        flags.append("字段「%s」非数值(原始值 %s, sheet「%s」第 %d 行), 按缺失处理待复核" % (field, raw_v, sheet, excel_row))
    return v


def parse_sheet(ws, cfg, levels, problems):
    """解析单个 sheet: 可能含一张或多张表。返回 (测点结果列表, 表头meta, 工况, 分析, 巡视记录)。"""
    results, meta_all, cond_text, anal_text, inspect = [], {}, "", "", {}
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    i = 0
    n = len(rows)
    while i < n:
        headers_raw = rows[i]
        headers = [norm_header(h) for h in headers_raw]
        form = detect_form([h for h in headers if h])
        if form is None:
            i += 1
            continue
        # 找表头区: 向上回溯到上一个空行或非表头内容
        head_start = i
        while head_start > 0 and any(cell_text(c) for c in rows[head_start - 1]):
            prev_headers = [norm_header(h) for h in rows[head_start - 1] if norm_header(h)]
            if detect_form(prev_headers) is not None:
                break
            head_start -= 1
        sheet_title = None
        for r in rows[head_start:i]:
            t = " ".join(cell_text(c) for c in r if cell_text(c))
            if re.search(r"表\s*[A-GＡ-Ｇa-g]", t) and ("日报" in t or "报表" in t or "监测" in t):
                sheet_title = t
        if form == "表CD":
            form = split_form_cd(headers_raw, sheet_title or ws.title)
        meta = parse_meta_block(rows[head_start:i])
        for k, v in meta.items():
            meta_all.setdefault(k, v)

        col_map, units = map_columns(headers_raw, form)
        # 数据区
        j = i + 1
        data_end = j
        while data_end < n:
            row = rows[data_end]
            if row_is_tail(row):
                break
            if not any(cell_text(c) for c in row):
                break
            data_end += 1
        data_rows = rows[j:data_end]
        tail_rows = rows[data_end:]
        c1, a1 = extract_tail_text(tail_rows)
        cond_text = cond_text or c1
        anal_text = anal_text or a1

        if form == "表G":
            last_cat = ""
            for k, row in enumerate(data_rows):
                cat = val_of(row, col_map, units, "分类", ws.title, j + k + 1, [], want_num=False)
                content = val_of(row, col_map, units, "内容", ws.title, j + k + 1, [], want_num=False)
                res = val_of(row, col_map, units, "结果", ws.title, j + k + 1, [], want_num=False)
                rmk = val_of(row, col_map, units, "备注", ws.title, j + k + 1, [], want_num=False)
                if cat:
                    last_cat = cat
                if content:
                    inspect[content] = {"分类": last_cat, "结果": res or "", "备注": rmk or ""}
            i = data_end
            continue

        for k, row in enumerate(data_rows):
            excel_row = j + k + 1
            flags = []
            vals = {}
            for field in ("累计量", "本次变化量", "变化速率", "深度", "本次测值", "上次测值",
                          "初始高程", "本次高程", "上次高程",
                          "长度_本次", "长度_单次变化", "长度_累计", "长度_速率",
                          "宽度_本次", "宽度_单次变化", "宽度_累计", "宽度_速率"):
                vals[field] = val_of(row, col_map, units, field, ws.title, excel_row, flags)
            point = val_of(row, col_map, units, "point_id", ws.title, excel_row, [], want_num=False)
            item = val_of(row, col_map, units, "item", ws.title, excel_row, [], want_num=False)
            remark_raw = val_of(row, col_map, units, "备注", ws.title, excel_row, [], want_num=False)
            group_no = val_of(row, col_map, units, "组号", ws.title, excel_row, [], want_num=False)
            serial = val_of(row, col_map, units, "编号", ws.title, excel_row, [], want_num=False)
            shape = val_of(row, col_map, units, "形态", ws.title, excel_row, [], want_num=False)

            if form == "表B" and not point:
                # 表B 无点号列: 孔号取标题/sheet名, 点号 = 孔号@深度
                hole = None
                t = sheet_title or ws.title
                m = re.search(r"([A-Za-z]+[-_]?\d+|[\u4e00-\u9fa5]{1,4}\d+号?孔)", t)
                hole = m.group(1) if m else ws.title
                depth_txt = val_of(row, col_map, units, "深度", ws.title, excel_row, [], want_num=False)
                point = "%s@%sm" % (hole, depth_txt if depth_txt else "?")
                if vals.get("深度") is None:
                    flags.append("深度缺失或非数值(sheet「%s」第 %d 行), 待复核" % (ws.title, excel_row))
            if not point:
                problems.append({"位置": "sheet「%s」第 %d 行" % (ws.title, excel_row),
                                 "问题": "缺少点号", "原始值": "", "处理": "整行标记待复核, 不参与判定"})
                continue

            form_eff = form if form != "表CD" else "表CD"
            info = FORM_INFO.get(form_eff, FORM_INFO.get("表A"))
            unit = units.get("累计量") or units.get("本次测值") or units.get("长度_累计") or info["unit"]
            item_name = item or info["item"]
            if form_eff == "表CD":
                flags.append("表C/表D 仅凭列头无法区分(sheet「%s」), 请确认该表测项类别与单位(kPa/kN)" % ws.title)

            # 主指标缺失检查
            cum, delta, rate = vals.get("累计量"), vals.get("本次变化量"), vals.get("变化速率")
            if form_eff == "表F":
                # 裂缝按宽度为主判定指标, 长度为辅
                cum = vals.get("宽度_累计")
                delta = vals.get("宽度_单次变化")
                rate = vals.get("宽度_速率")
                if cum is None and vals.get("长度_累计") is not None:
                    flags.append("宽度累计变化缺失, 暂以长度指标参考, 需核对原始记录")
                    cum = vals.get("长度_累计")
                    delta = vals.get("长度_单次变化")
                    rate = vals.get("长度_速率")
            if cum is None and delta is None and rate is None:
                flags.append("累计量/本次变化量/变化速率全部缺失, 暂停该点判定, 需补充或复核原始记录")

            check_consistency(form_eff, vals, flags, ws.title, excel_row)

            th = get_threshold(cfg, item_name, point)
            if cum is None and delta is None and rate is None:
                level, reason = "未判定", "指标全部缺失, 暂停判定"
            else:
                level, reason = classify(cum, rate, th, levels, unit)
            if th is None:
                flags.append("阈值未配置, 不作超限判定, 需项目专项监测方案确认")

            results.append({
                "point_id": point,
                "item": item_name,
                "表式": form_eff,
                "原始数据": {
                    "Excel定位": "sheet「%s」第 %d 行" % (ws.title, excel_row),
                    "组号": group_no, "编号": serial, "深度": vals.get("深度"),
                    "本次测值": vals.get("本次测值"), "上次测值": vals.get("上次测值"),
                    "初始高程": vals.get("初始高程"), "本次高程": vals.get("本次高程"), "上次高程": vals.get("上次高程"),
                    "形态": shape, "备注": remark_raw,
                    "长度": {"本次": vals.get("长度_本次"), "单次变化": vals.get("长度_单次变化"),
                             "累计": vals.get("长度_累计"), "速率": vals.get("长度_速率")},
                    "宽度": {"本次": vals.get("宽度_本次"), "单次变化": vals.get("宽度_单次变化"),
                             "累计": vals.get("宽度_累计"), "速率": vals.get("宽度_速率")},
                    "单位": unit,
                },
                "计算结果": {
                    "累计量": None if cum is None else round(cum, 3),
                    "本次变化量": None if delta is None else round(delta, 3),
                    "变化速率": None if rate is None else round(rate, 3),
                    "间隔天数": None,
                    "单位": unit,
                    "口径": "原样引用附录表式填报值, 未重新推算",
                },
                "判定依据": {
                    "等级": level,
                    "阈值": None if th is None else {
                        "报警值": th["alarm"], "控制值": th["control"], "速率限值": th["rate_alarm"],
                        "作用域": th["scope"],
                    },
                    "来源": None if th is None else th["source"],
                    "判定理由": reason,
                },
                "状态标记": {"等级": level, "待复核": flags},
            })
        i = data_end
    return results, meta_all, cond_text, anal_text, inspect


def summarize_by_form(results):
    forms = {}
    for r in results:
        r = r or {}
        f = r.get("表式", "未识别")
        calc = r.get("计算结果") or {}
        g = forms.setdefault(f, {"表式": f, "测项": [], "测点数": 0,
                                 "正常": 0, "黄色": 0, "橙色": 0, "红色": 0, "未判定": 0,
                                 "最大|累计量|": None, "最大|变化速率|": None, "单位": calc.get("单位")})
        item = r.get("item") or "未注明监测项目"
        if item not in g["测项"]:
            g["测项"].append(item)
        g["测点数"] += 1
        lv = (r.get("判定依据") or {}).get("等级", "未判定")
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


def main():
    ap = argparse.ArgumentParser(description="解析附录 A~G 表式的监测数据 Excel")
    ap.add_argument("--excel", required=True, help="按附录 A~G 表式整理的 Excel 文件(.xlsx)")
    ap.add_argument("--config", required=True, help="阈值配置 JSON 路径")
    ap.add_argument("--date", default=None, help="报告日期 YYYY-MM-DD(仅记录, 数据期别以表内为准)")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    levels = cfg.get("levels", {})

    wb = openpyxl.load_workbook(args.excel, data_only=True)
    all_results, meta_all, problems = [], {}, []
    cond_by_form, anal_by_form, inspect_all = {}, {}, {}
    for ws in wb.worksheets:
        results, meta, cond, anal, inspect = parse_sheet(ws, cfg, levels, problems)
        for r in results:
            cond_by_form.setdefault(r.get("表式", ""), cond)
            anal_by_form.setdefault(r.get("表式", ""), anal)
        if inspect:
            inspect_all.update(inspect)
        for k, v in meta.items():
            meta_all.setdefault(k, v)
        all_results.extend(results)

    over = [r for r in all_results if r["判定依据"]["等级"] in ("黄色", "橙色", "红色")]
    pending = [r for r in all_results if r["状态标记"]["待复核"] or r["判定依据"]["等级"] == "未判定"]

    out = {
        "报告日期": args.date,
        "数据来源": os.path.basename(args.excel),
        "数据口径": "按 GB 50497-2019 附录 A~G 表式填报值原样引用; 累计量/变化量/速率未重新推算",
        "表头信息": meta_all,
        "测点数": len(all_results),
        "统计": {
            "正常": sum(1 for r in all_results if r["判定依据"]["等级"] == "正常"),
            "黄色": sum(1 for r in all_results if r["判定依据"]["等级"] == "黄色"),
            "橙色": sum(1 for r in all_results if r["判定依据"]["等级"] == "橙色"),
            "红色": sum(1 for r in all_results if r["判定依据"]["等级"] == "红色"),
            "未判定": sum(1 for r in all_results if r["判定依据"]["等级"] == "未判定"),
        },
        "按表式汇总": summarize_by_form(all_results),
        "测点结果": all_results,
        "超限测点": [{"测点": r["point_id"], "等级": r["判定依据"]["等级"], "表式": r.get("表式"),
                      "累计量": r["计算结果"]["累计量"], "变化速率": r["计算结果"]["变化速率"],
                      "单位": r["计算结果"].get("单位"), "理由": r["判定依据"]["判定理由"]} for r in over],
        "待复核事项": [{"测点": r["point_id"], "事项": r["状态标记"]["待复核"]} for r in pending],
        "数据校核问题": problems,
        "原表工况描述": {k: v for k, v in cond_by_form.items() if v},
        "原表分析文字": {k: v for k, v in anal_by_form.items() if v},
        "巡视检查记录": inspect_all,
        "说明": "指标值原样引用附录表式填报数据, 系统只做一致性校核与分级判定; "
                "阈值与分级须以项目专项监测方案为准; 未配置阈值一律不作判定。",
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("sheet数 %d | 测点(行)数 %d | 超限 %d | 待复核 %d | 红色预警 %d" % (
        len(wb.worksheets), out["测点数"], len(out["超限测点"]), len(out["待复核事项"]), out["统计"]["红色"]))
    print("表式分布: %s" % "、".join("%s(%d)" % (g["表式"], g["测点数"]) for g in out["按表式汇总"]))
    print("输出: %s" % os.path.abspath(args.out))


if __name__ == "__main__":
    main()
