# -*- coding: utf-8 -*-
"""rejudge_by_rag.py — 用 RAG 知识库报警值规则表重判监测结果。

与 RAG 流程（jikeng-rag/source/report_core.py 之 DEFAULT_ALARM_RULES，源自
GB 50497-2019 第 8.2/8.3 条）整合：把一份已算好数值的 result.json 的“判定依据”
整体替换为 RAG 规范下的阈值与报警判定，**不重算数值、不补阈值**。

判定规则（三级，与 RAG 一致）：
  正常   : 累计量/变化速率 < 0.70 × 报警值
  黄色(需关注): 0.70 ~ 1.00 × 报警值
  红色(报警)  : ≥ 1.00 × 报警值
  未判定 : 无可比数值，或 RAG 规则表未覆盖该测项（须专项方案补充）

颜色映射：需关注→黄色，报警→红色，正常/未判定 不变。橙色不在 RAG 规则内，不产出。

用法:
  python rejudge_by_rag.py --result result.json \
      --rules references/rag_alarm_rules.json \
      --level 一级 --out result_rag.json
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

RAG_SOURCE = "RAG 知识库（GB 50497-2019 表8.0.4/8.0.5 等 30 部规范）"
RAG_UNCOVERED = "RAG 知识库（GB 50497-2019 表8.0.4/8.0.5 等规范）未载该测项量化报警值，按规范无法判定"

# 内力/轴力/土压力/孔隙水类在 result.计算结果 中可能携带的设计值字段名
DESIGN_FIELDS = ["设计值", "墙身弯矩设计值", "构件承载能力设计值", "轴力设计值",
                "极限抗拔承载力", "土压力设计值", "计算水压力", "内力设计值"]


def load_json(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def to_rule_unit(value, data_unit, rule_unit):
    """把数据数值换算到规则单位（mm）。地下水位以 m 计时 ×1000。"""
    if value is None:
        return None
    if rule_unit == "mm" and data_unit in ("m", "m/d"):
        return value * 1000.0
    return float(value)


def judge(item: str, cum, rate, rule: dict, level: str, cc: dict):
    """返回 (等级, 报警值, 速率限值, 判定理由)。无规则时返回 None 表示未覆盖。"""
    if not rule:
        return None
    src = rule.get("source", RAG_SOURCE)
    lvl_key = "level1" if level in ("一级", "1", "l1", "level1") else (
        "level3" if level in ("三级", "3", "l3") else "level2")
    lim = rule.get(lvl_key) or rule.get("level1")

    # ---- 设计值比例类（内力/轴力/土压力/孔隙水）----
    if rule.get("type") == "design_ratio":
        pct = (lim or {}).get("pct") or rule.get("design_pct", {}).get(level, 80)
        design_val = None
        for k in DESIGN_FIELDS:
            if k in cc and cc[k] is not None:
                try:
                    design_val = float(cc[k])
                    break
                except (TypeError, ValueError):
                    design_val = None
        if design_val is None:
            reason = ("%s 规定该测项报警值=设计值的 %d%%（%s）；本次数据未提供设计值，"
                      "按规范无法量化判定，待补充设计值后重判" % (src, pct, rule.get("design_field", "设计值")))
            return ("未判定", None, None, reason)
        alarm = design_val * pct / 100.0
        if cum is None:
            return ("未判定", alarm, None,
                    "无可比数值（累计量缺失），按规范暂停判定；设计值报警值=%.2f" % alarm)
        rc = abs(cum) / alarm if alarm else 0
        if rc >= 1.0:
            ln, tag = "红色", "报警"
        elif rc >= 0.7:
            ln, tag = "黄色", "需关注"
        else:
            ln, tag = "正常", "正常"
        reason = "（%s）累计量 %.2f 占设计值报警值(%.0f%%×%.2f=%.2f) 的 %.0f%%" % (
            tag, abs(cum), pct, design_val, alarm, rc * 100)
        return (ln, alarm, None, reason)

    # ---- 绝对值类（位移/沉降/裂缝/水位）----
    cum_rng = lim.get("cum")
    rate_rng = lim.get("rate")
    rule_unit = rule.get("unit", "mm")
    data_unit = cc.get("单位")
    cum_lim = max(cum_rng) if cum_rng else None
    rate_lim = max(rate_rng) if rate_rng else None

    cum_r = to_rule_unit(cum, data_unit, rule_unit) if cum is not None else None
    rate_r = to_rule_unit(rate, data_unit, rule_unit) if rate is not None else None

    ratios = []
    parts = []
    if cum_r is not None and cum_lim:
        rc = abs(cum_r) / cum_lim
        ratios.append(rc)
        parts.append("累计量 %.2f %s 占报警值 %.2f %s 的 %.0f%%" % (
            abs(cum_r), rule_unit, cum_lim, rule_unit, rc * 100))
    if rate_r is not None and rate_lim:
        rr = abs(rate_r) / rate_lim
        ratios.append(rr)
        parts.append("变化速率 %.2f %s/d 占速率限值 %.2f %s/d 的 %.0f%%" % (
            abs(rate_r), rule_unit, rate_lim, rule_unit, rr * 100))

    if not ratios:
        return ("未判定", cum_lim, rate_lim,
                "%s 未提供可比数值（累计量/变化速率均缺失），按规范暂停判定" % src)

    mx = max(ratios)
    if mx >= 1.0:
        level_name = "红色"
        tag = "报警"
    elif mx >= 0.7:
        level_name = "黄色"
        tag = "需关注"
    else:
        level_name = "正常"
        tag = "正常"
    reason = "（%s）" % tag + "；".join(parts)
    return (level_name, cum_lim, rate_lim, reason)


def summarize_by_form(points):
    forms = {}
    for r in points:
        f = r.get("表式") or "未识别"
        g = forms.setdefault(f, {"表式": f, "测项": [], "测点数": 0,
                                 "正常": 0, "黄色": 0, "橙色": 0, "红色": 0, "未判定": 0,
                                 "最大|累计量|": None, "最大|变化速率|": None, "单位": r.get("计算结果", {}).get("单位")})
        it = r.get("item")
        if it and it not in g["测项"]:
            g["测项"].append(it)
        g["测点数"] += 1
        lv = r.get("判定依据", {}).get("等级", "未判定")
        g[lv] = g.get(lv, 0) + 1
        c = r.get("计算结果", {})
        cu = c.get("累计量")
        if cu is not None:
            g["最大|累计量|"] = max(g["最大|累计量|"] or 0.0, abs(cu))
        rt = c.get("变化速率")
        if rt is not None:
            g["最大|变化速率|"] = max(g["最大|变化速率|"] or 0.0, abs(rt))
    out = []
    for f in sorted(forms):
        g = forms[f]
        g["测项"] = "、".join(g["测项"])
        out.append(g)
    return out


def main():
    ap = argparse.ArgumentParser(description="按 RAG 规范重判监测结果")
    ap.add_argument("--result", required=True, help="已算数值的 result.json")
    ap.add_argument("--rules", required=True, help="rag_alarm_rules.json")
    ap.add_argument("--level", default="一级", help="基坑安全等级：一级/二级")
    ap.add_argument("--out", required=True, help="输出 result_rag.json")
    args = ap.parse_args()

    res = load_json(args.result)
    rules_doc = load_json(args.rules)
    rules = rules_doc.get("规则", {})
    mapping = rules_doc.get("测项映射", {})

    points = res.get("测点结果", [])
    new_points = []
    for p in points:
        item = p.get("item", "")
        rag_item = mapping.get(item, item)
        rule = rules.get(rag_item)
        cc = p.get("计算结果", {})
        cum = cc.get("累计量")
        rate = cc.get("变化速率")

        if not rule:
            level = "未判定"
            alarm = None
            rate_lim = None
            reason = RAG_UNCOVERED
            src = "RAG 未覆盖"
        else:
            j = judge(item, cum, rate, rule, args.level, cc)
            level, alarm, rate_lim, reason = j
            src = rule.get("source", RAG_SOURCE)

        new_jud = {
            "等级": level,
            "阈值": (None if alarm is None else {
                "报警值": alarm,
                "控制值": None,
                "速率限值": rate_lim,
                "作用域": "规范级(RAG)",
            }),
            "来源": src,
            "判定理由": reason,
        }
        np_ = dict(p)
        np_["判定依据"] = new_jud
        np_["状态标记"] = {"等级": level, "待复核": p.get("状态标记", {}).get("待复核", [])}
        new_points.append(np_)

    stat = {"正常": 0, "黄色": 0, "橙色": 0, "红色": 0, "未判定": 0}
    for p in new_points:
        stat[p["判定依据"]["等级"]] = stat.get(p["判定依据"]["等级"], 0) + 1

    over = [p for p in new_points if p["判定依据"]["等级"] in ("黄色", "红色")]
    order = {"红色": 0, "黄色": 1}
    over_sorted = sorted(over, key=lambda x: order.get(x["判定依据"]["等级"], 9))
    over_list = [{"测点": p["point_id"], "等级": p["判定依据"]["等级"],
                  "累计量": p["计算结果"].get("累计量"),
                  "变化速率": p["计算结果"].get("变化速率"),
                  "理由": p["判定依据"]["判定理由"]} for p in over_sorted]

    pending = []
    for p in new_points:
        sm_items = p["状态标记"]["待复核"] or []
        # 剔除上游遗留的“需项目专项监测方案确认”等过时表述，统一改走规范口径
        sm_items = [x for x in sm_items if "专项监测方案" not in x]
        if p["判定依据"]["等级"] == "未判定":
            sm_items = sm_items + [p["判定依据"]["判定理由"]]
        if sm_items:
            pending.append({"测点": p["point_id"], "事项": sm_items})

    out = dict(res)
    out["测点结果"] = new_points
    out["统计"] = stat
    out["超限测点"] = over_list
    out["待复核事项"] = pending
    out["按表式汇总"] = summarize_by_form(new_points)
    out["数据口径"] = "数值原样引用原始 result.json；判定依据整体按 RAG 知识库报警值规则表（GB 50497-2019 表8.0.4/8.0.5 等 30 部规范）重判，不重算数值、不补阈值。"
    out["阈值来源"] = rules_doc.get("来源说明", "")
    out["安全等级"] = args.level

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("安全等级=%s | 正常=%d 黄色=%d 橙色=%d 红色=%d 未判定=%d | 超限=%d 待复核=%d"
          % (args.level, stat["正常"], stat["黄色"], stat["橙色"], stat["红色"], stat["未判定"],
             len(over_list), len(pending)))
    print("输出: %s" % os.path.abspath(args.out))


if __name__ == "__main__":
    main()
