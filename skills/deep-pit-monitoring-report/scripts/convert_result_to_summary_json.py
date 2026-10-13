# -*- coding: utf-8 -*-
"""把 convert_wide_to_appendix_ab.py 产出的「附表A~F 时间序列」result.json
转换为 render_summary.py 所需的「测点结果 + 按表式汇总 + 统计 + 超限测点 +
表头信息」结构，使宽表累计数据也能走"汇总页 + 附录 A~G 逐表分页"汇总表流程。

转换口径（确定性，与 convert 一致）：
- 取每个测点末次监测日的记录作为"本次"值；
- convert 三级判定(正常/需关注/报警) 映射为 render_summary 四级(正常/黄色/红色)，
  橙色列恒为 0（需关注≈黄色预警 70%~报警值，报警≈红色预警 ≥报警值）；
  缺设计值的 design_ratio 类标"未判定"，并入待复核事项；
- C/D/E/F 的"本次测值/上次测值/高程"等原始值宽表未提供，标"—"，
  仅累计变化/本次变化/变化速率由累计序列推算（与 convert 口径一致）。

依赖：标准库。
"""
from __future__ import annotations
import argparse
import json

FORM_OF = {"附表A": "表A", "附表B": "表B", "附表C": "表C",
           "附表D": "表D", "附表E": "表E", "附表F": "表F"}
LEVEL_MAP = {"正常": "正常", "需关注": "黄色", "报警": "红色", "未判定": "未判定"}
UNIT = {"表A": "mm", "表B": "mm", "表C": "kPa", "表D": "kN", "表E": "mm", "表F": "mm"}


def build_raw(form, delta, cum, rate):
    if form in ("表C", "表D"):
        return {"组号": "—", "深度": "—", "本次测值": "—", "上次测值": "—"}
    if form == "表E":
        return {"编号": "—", "初始高程": "—", "本次高程": "—", "上次高程": "—"}
    if form == "表F":
        return {"长度": {}, "宽度": {"本次": None, "单次变化": delta, "累计": cum, "速率": rate}, "形态": "—"}
    return {}


def main():
    ap = argparse.ArgumentParser(description="convert result(附表序列) → render_summary 输入")
    ap.add_argument("--result", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    src = json.load(open(args.result, "r", encoding="utf-8"))

    points = []
    by_form = {}
    stat = {"正常": 0, "黄色": 0, "橙色": 0, "红色": 0, "未判定": 0}
    over = []
    pend = []
    last_date = None
    prev_date = None

    for key, rows in src.items():
        if not key.startswith("附表") or not isinstance(rows, list):
            continue
        form = FORM_OF.get(key)
        if not form:
            continue
        latest = {}
        for r in rows:
            pid = r.get("point")
            if pid is None:
                continue
            if pid not in latest or r["date"] > latest[pid]["date"]:
                latest[pid] = r
            if last_date is None or r["date"] > last_date:
                last_date = r["date"]
        dates = sorted({r["date"] for r in rows})
        if len(dates) >= 2:
            prev_date = dates[-2]

        for pid, r in latest.items():
            lv = LEVEL_MAP.get(r.get("level"), r.get("level"))
            cum = r.get("cum")
            delta = r.get("delta")
            rate = r.get("rate")
            rec = {
                "point_id": pid,
                "item": r.get("rule_key") or form,
                "表式": form,
                "计算结果": {"累计量": cum, "本次变化量": delta, "变化速率": rate},
                "原始数据": build_raw(form, delta, cum, rate),
                "判定依据": {"等级": lv},
                "状态标记": {"待复核": []},
            }
            if r.get("level") == "未判定":
                msg = "未判定：缺设计值，按 GB 50497-2019 表 8.0.4 该测项报警值=设计值×比例，需项目专项监测方案补充后重判"
                rec["状态标记"]["待复核"].append(msg)
                pend.append({"测点": pid, "事项": [msg]})
            points.append(rec)
            by_form.setdefault(form, []).append(rec)
            stat[lv] = stat.get(lv, 0) + 1
            if lv in ("黄色", "红色"):
                over.append({"测点": pid, "等级": lv, "理由": r.get("note", ""),
                             "累计量": cum, "单位": UNIT[form], "变化速率": rate})

    summary_forms = []
    for form, recs in by_form.items():
        s = {"正常": 0, "黄色": 0, "橙色": 0, "红色": 0, "未判定": 0}
        max_cum = None
        max_rate = None
        for r in recs:
            lv = r["判定依据"]["等级"]
            s[lv] = s.get(lv, 0) + 1
            c = r["计算结果"]["累计量"]
            rt = r["计算结果"]["变化速率"]
            if c is not None:
                max_cum = c if max_cum is None else max(max_cum, c)
            if rt is not None:
                max_rate = rt if max_rate is None else max(max_rate, rt)
        summary_forms.append({
            "表式": form, "测项": recs[0]["item"], "测点数": len(recs),
            **s, "最大|累计量|": max_cum, "最大|变化速率|": max_rate, "单位": UNIT[form],
        })

    meta = {"工程名称": "待填", "报表编号": "待填", "天气": "待填",
            "观测者": "待填", "计算者": "待填", "校核者": "待填",
            "仪器型号": "待填", "仪器编号": "待填", "检定有效期": "待填",
            "本次监测时间": last_date or "待填", "上次监测时间": prev_date or "待填", "序号": "待填"}

    out = {
        "数据来源": src.get("说明", "项目监测数据（宽表累计序列）"),
        "数据口径": "确定性计算输出（累计序列推算；C/D/E/F 的本次测值/高程等原始值宽表未提供，标 —）",
        "表头信息": meta,
        "测点结果": points,
        "按表式汇总": summary_forms,
        "统计": stat,
        "超限测点": over,
        "待复核事项": pend,
        "原表工况描述": {},
        "原表分析文字": {},
    }
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("adapter: %d 测点, 附表=%s, 统计=%s" % (len(points), list(by_form.keys()), stat))


if __name__ == "__main__":
    main()
