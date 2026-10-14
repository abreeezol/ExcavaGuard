# -*- coding: utf-8 -*-
"""深基坑监测指标确定性计算。

用法:
  python compute_metrics.py --data 监测数据.csv --config 阈值配置.json \
      --date 2026-09-28 --out result.json

职责边界:
  - 只做确定性计算与规则判定: 累计量 / 本次变化量 / 变化速率 / 阈值分级 / 缺失与粗差识别。
  - 不做原因分析、不写分析文字、不补阈值、不插值填补缺失值。
  - 每个测点输出 "原始数据-计算结果-判定依据-状态标记" 四段, 供日报逐项追溯。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATE_KEYS = ("观测日期", "日期", "date", "观测时间")
POINT_KEYS = ("测点编号", "点号", "测点", "point_id", "point")
ITEM_KEYS = ("监测项目", "监测项目", "项目", "item", "测项")
VALUE_KEYS = ("观测值", "本次观测值", "累计量", "value", "读数")
INITIAL_KEYS = ("初始值", "初始读数", "initial")
UNIT_KEYS = ("单位", "unit")
SIGN_KEYS = ("方向", "正负号", "sign")

UNIT_TO_MM = {
    "mm": 1.0, "毫米": 1.0,
    "cm": 10.0, "厘米": 10.0,
    "": 1.0,
}
# 米(m)不自动换算: 水位、标高类测项本就以 m 计, 换算成 mm 会与阈值单位错位。
# 遇到 m 一律保留原值与原单位, 并在校核问题中提示确认与阈值单位一致。
KEEP_UNITS = {"m": "m", "米": "m", "kpa": "kPa", "kn": "kN", "kn·m": "kN·m", "kn*m": "kN·m"}

LEVEL_ORDER = ["正常", "黄色", "橙色", "红色", "未判定"]


def pick(row: dict, keys):
    for k in keys:
        if k in row and str(row[k]).strip() not in ("", "-", "None", "null"):
            return str(row[k]).strip()
    return None


def parse_date(text: str):
    if not text:
        return None
    text = text.strip().replace("/", "-").replace(".", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def to_float(text):
    if text is None:
        return None
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def load_rows(path: str):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def norm_records(rows):
    """归一: 测点映射 / 单位换算为 mm / 日期清洗。保留原始值。"""
    records = []
    problems = []
    unit_noted = set()  # 单位提示按(测点, 单位)去重, 避免每行刷屏
    for idx, row in enumerate(rows, start=2):  # 表头算第 1 行
        point = pick(row, POINT_KEYS)
        item = pick(row, ITEM_KEYS) or "未注明监测项目"
        raw_date = pick(row, DATE_KEYS)
        date = parse_date(raw_date)
        unit_raw = pick(row, UNIT_KEYS) or ""
        unit = unit_raw.lower().strip()
        keep = KEEP_UNITS.get(unit)
        factor = UNIT_TO_MM.get(unit)
        if keep:
            factor = 1.0
            note = "单位为 m，按原值处理未换算为 mm" if keep == "m" else "单位为 %s，非位移量，按原值处理" % keep
            key = (point, keep)
            if key not in unit_noted:
                unit_noted.add(key)
                problems.append({"行号": idx, "问题": "%s（测点 %s）" % (note, point), "原始值": unit_raw,
                                 "处理": "该测点保留原值与原单位，须确认阈值单位与其一致，否则标记待复核"})
        elif factor is None:
            problems.append({"行号": idx, "问题": "单位无法识别", "原始值": unit_raw, "处理": "按 mm 处理并标记待复核"})
            factor = 1.0
        raw_value = pick(row, VALUE_KEYS)
        value = to_float(raw_value)
        if value is not None:
            value = value * factor
        initial = to_float(pick(row, INITIAL_KEYS))
        if initial is not None:
            initial = initial * factor
        sign_raw = pick(row, SIGN_KEYS)
        sign = 1.0
        if sign_raw in ("-1", "-", "负", "反向"):
            sign = -1.0

        if not point:
            problems.append({"行号": idx, "问题": "缺少测点编号", "原始值": "", "处理": "整行标记待复核, 不参与计算"})
            continue
        if date is None:
            problems.append({"行号": idx, "问题": "日期格式异常", "原始值": raw_date, "处理": "该条不参与变化量计算, 标记待复核"})
        if value is None:
            problems.append({"行号": idx, "问题": "观测值缺失或非数值", "原始值": raw_value or "(空)", "处理": "保留空值, 标记待复核, 不插值"})

        records.append({
            "row": idx, "point_id": point, "item": item,
            "date_text": raw_date, "date": date,
            "raw_value": raw_value, "raw_unit": unit_raw,
            "unit_label": keep or "mm",
            "value": value, "initial": initial, "sign": sign,
        })
    return records, problems


def get_threshold(cfg: dict, item: str, point_id: str):
    """测点级配置优先于项目级, 再退回默认。缺阈值 -> 返回 None 供标记待复核。"""
    for scope in (cfg.get("points", {}).get(point_id), cfg.get("items", {}).get(item), cfg.get("defaults", {})):
        if scope and (scope.get("alarm") is not None or scope.get("control") is not None):
            return {
                "alarm": to_float(scope.get("alarm")),
                "control": to_float(scope.get("control")),
                "rate_alarm": to_float(scope.get("rate_alarm")),
                "source": scope.get("source") or "未注明依据来源",
                "scope": "测点级" if scope is cfg.get("points", {}).get(point_id) else ("项目级" if scope is cfg.get("items", {}).get(item) else "默认"),
            }
    return None


def classify(cum, rate, th, levels, unit="mm"):
    """按项目规则分级。阈值缺失一律返回未判定, 不猜阈值。unit 用于判定理由, 避免把 m/kN/kPa 写成 mm。"""
    if th is None or th.get("alarm") is None:
        return "未判定", "阈值未配置, 不作判定"
    yellow = float(levels.get("yellow_ratio", 0.7))
    alarm = th["alarm"]
    control = th.get("control")
    rate_alarm = th.get("rate_alarm")

    reasons = []
    level = "正常"
    if cum is not None:
        a = abs(cum)
        if control is not None and a >= control:
            level = "红色"
            reasons.append("累计量 %.2f %s 达到/超过控制值 %.2f %s" % (a, unit, control, unit))
        elif a >= alarm:
            level = "橙色"
            reasons.append("累计量 %.2f %s 达到/超过报警值 %.2f %s" % (a, unit, alarm, unit))
        elif a >= alarm * yellow:
            level = "黄色"
            reasons.append("累计量 %.2f %s 达到报警值的 %.0f%%(%.2f %s)" % (a, unit, yellow * 100, alarm * yellow, unit))
    if rate is not None and rate_alarm is not None and abs(rate) >= rate_alarm:
        if level in ("正常", "黄色"):
            level = "橙色"
        reasons.append("变化速率 %.2f %s/d 达到/超过速率限值 %.2f %s/d" % (abs(rate), unit, rate_alarm, unit))
    if not reasons:
        reasons.append("未触发项目配置的报警阈值")
    return level, "；".join(reasons)


def analyze(records, cfg, target_date):
    levels = cfg.get("levels", {})
    sigma = float(cfg.get("gross_error_sigma", 3.0))
    min_abs = float(cfg.get("gross_error_min_abs", 2.0))
    ratio = float(cfg.get("gross_error_ratio", 3.0))

    by_point = {}
    for r in records:
        by_point.setdefault(r["point_id"], []).append(r)

    results = []
    for point_id, group in sorted(by_point.items()):
        bad_date = [r for r in group if r["date"] is None]
        recs = sorted([r for r in group if r["date"]], key=lambda x: x["date"])
        if not recs:
            dated = [r for r in by_point[point_id]]
            first = dated[0]
            results.append({
                "point_id": point_id, "item": first["item"],
                "原始数据": {"观测值": first["raw_value"], "单位": first["raw_unit"], "日期": first["date_text"]},
                "计算结果": {"累计量": None, "本次变化量": None, "变化速率": None, "间隔": None},
                "判定依据": {"阈值": None, "来源": None, "判定理由": "日期全部异常, 无法计算变化量"},
                "状态标记": {"等级": "未判定", "待复核": ["日期格式异常, 需核对原始记录"]},
            })
            continue

        item = recs[-1]["item"]
        # 只保留目标日期及之前的记录
        if target_date:
            recs = [r for r in recs if r["date"].date() <= target_date] or recs
        cur = recs[-1]
        prev = recs[-2] if len(recs) >= 2 else None

        def cum_of(r):
            if r["value"] is None:
                return None
            if r["initial"] is not None:
                return (r["value"] - r["initial"]) * r["sign"]
            return r["value"] * r["sign"]

        cum = cum_of(cur)
        cum_prev = cum_of(prev) if prev else None
        delta = None if (cum is None or cum_prev is None) else cum - cum_prev
        interval = None
        rate = None
        if prev and cur["date"] and prev["date"]:
            days = (cur["date"] - prev["date"]).total_seconds() / 86400.0
            interval = round(days, 3)
            if days > 0 and delta is not None:
                rate = delta / days

        unit = cur.get("unit_label", "mm")
        flags = []
        if bad_date:
            flags.append("该测点有 %d 条记录日期格式异常(%s)未参与计算, 需核对原始记录" % (
                len(bad_date), "；".join(str(r["date_text"]) for r in bad_date[:2])))
        if cur["value"] is None:
            flags.append("本次观测值缺失, 暂停该测点判定, 需补充或复核原始记录")
        if delta is not None:
            # 只统计本次之前的历史变化量, 不能把本次变化量混进标准差, 否则粗差会把自身抬高的离散度掩盖掉
            hist = []
            for a, b in zip(recs[:-2], recs[1:-1]):
                ca, cb = cum_of(a), cum_of(b)
                if ca is not None and cb is not None:
                    hist.append(cb - ca)
            if len(hist) >= 3:
                sd = statistics.pstdev(hist)
                mean_abs = statistics.fmean([abs(h) for h in hist])
                # 双重门槛: 既要偏离历史离散度, 也要超过历史平均变化幅度的 ratio 倍(或最小绝对值)。
                # 仅用标准差会把"变化稳步加快"的真实趋势误判为粗差。
                abs_gate = max(min_abs, ratio * mean_abs)
                if sd > 1e-9 and abs(delta) > sigma * sd and abs(delta) > abs_gate:
                    flags.append("本次变化量 %.2f 超过历史波动的 %.1f 倍标准差且大于 %.2f(历史平均变化幅度 %.2f 的 %.1f 倍), 疑似粗差, 保留原始值待复核"
                                 % (abs(delta), sigma, abs_gate, mean_abs, ratio))
        if prev is None and cum is not None:
            flags.append("首期观测, 无历史值, 变化量与速率暂缺")

        th = get_threshold(cfg, item, point_id)
        if cur["value"] is None:
            level, reason = "未判定", "本次观测值缺失, 暂停该测点判定, 需补充或复核原始记录后重算"
        else:
            level, reason = classify(cum, rate, th, levels, unit)
        if th is None:
            flags.append("阈值未配置, 不作超限判定, 需项目专项监测方案确认")

        results.append({
            "point_id": point_id,
            "item": item,
            "原始数据": {
                "观测日期": cur["date_text"],
                "观测值": cur["raw_value"],
                "单位": cur["raw_unit"],
                "初始值": recs[-1].get("initial"),
                "上一期日期": prev["date_text"] if prev else None,
                "上一期观测值": prev["raw_value"] if prev else None,
                "CSV行号": cur["row"],
            },
            "计算结果": {
                "累计量": None if cum is None else round(cum, 3),
                "本次变化量": None if delta is None else round(delta, 3),
                "变化速率": None if rate is None else round(rate, 3),
                "间隔天数": interval,
                "单位": unit,
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

    over = [r for r in results if r["判定依据"]["等级"] in ("黄色", "橙色", "红色")]
    pending = [r for r in results if r["状态标记"]["待复核"] or r["判定依据"]["等级"] == "未判定"]
    red = [r for r in results if r["判定依据"]["等级"] == "红色"]

    return {
        "报告日期": target_date.isoformat() if target_date else None,
        "测点数": len(results),
        "统计": {
            "正常": sum(1 for r in results if r["判定依据"]["等级"] == "正常"),
            "黄色": sum(1 for r in results if r["判定依据"]["等级"] == "黄色"),
            "橙色": sum(1 for r in results if r["判定依据"]["等级"] == "橙色"),
            "红色": len(red),
            "未判定": sum(1 for r in results if r["判定依据"]["等级"] == "未判定"),
        },
        "测点结果": results,
        "超限测点": [{"测点": r["point_id"], "等级": r["判定依据"]["等级"], "累计量": r["计算结果"]["累计量"],
                      "变化速率": r["计算结果"]["变化速率"], "理由": r["判定依据"]["判定理由"]} for r in over],
        "待复核事项": [{"测点": r["point_id"], "事项": r["状态标记"]["待复核"]} for r in pending],
        "数据校核问题": [],
    }


def main():
    ap = argparse.ArgumentParser(description="深基坑监测指标确定性计算")
    ap.add_argument("--data", required=True, help="监测数据 CSV 路径")
    ap.add_argument("--config", required=True, help="阈值配置 JSON 路径")
    ap.add_argument("--date", default=None, help="报告日期 YYYY-MM-DD, 缺省取各测点最新一期")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    rows = load_rows(args.data)
    records, problems = norm_records(rows)
    target = parse_date(args.date) if args.date else None
    target_date = target.date() if target else None

    out = analyze(records, cfg, target_date)
    out["数据校核问题"] = problems
    out["说明"] = "数值由本脚本确定性计算; 阈值与分级须以项目专项监测方案为准; 未配置阈值一律不作判定。"

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("测点数 %d | 超限 %d | 待复核 %d | 红色预警 %d" % (
        out["测点数"], len(out["超限测点"]), len(out["待复核事项"]), out["统计"]["红色"]))
    print("输出: %s" % os.path.abspath(args.out))


if __name__ == "__main__":
    main()
