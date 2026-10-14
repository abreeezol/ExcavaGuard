# -*- coding: utf-8 -*-
"""日报自检辅助：核验报告数值是否全部来自确定性计算结果。

用法:
  python validate_report.py --report 监测日报_20261009.md --result result.json \
      --config thresholds.json [--out 自检结果.md]

检查项:
  1. 表格中"纯数值单元格"必须能在 result.json / 阈值配置中找到同值字段(2 位小数比对)。
     备注、判定理由等文字单元格不参与数值比对, 避免把文字里的数字误判为数据。
  2. 同一测点在各表中出现的行, 必须同时包含该测点的累计量与本次变化量(以计算结果为锚)。
  3. 全文"数值+单位"形式的数据是否落在允许集合内; 未命中的列出供人工判定
     (工况描述中的非测点数字, 如"分段长度约 20 m", 属正常例外)。
不检查: 文字表述是否合理、规范条款引用是否准确——需人工核对。
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

POINT_RE = re.compile(r"^[A-Za-z]{1,6}[-_－]?\d{1,4}[A-Za-z]?$")
PURE_NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
QTY_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(mm/d|mm|m|kN|kPa)")


def norm(x):
    try:
        f = float(x)
        if f != f:
            return None
        return "%.2f" % round(f, 2)
    except (TypeError, ValueError):
        return None


def norm_abs(x):
    try:
        return "%.2f" % round(abs(float(x)), 2)
    except (TypeError, ValueError):
        return None


def build_allowed(result: dict, cfg: dict):
    """允许出现的数值集合(含绝对值变体), 用于判定"是否存在凭空的数字"。"""
    allowed = set()
    interval_days = set()

    def add(v):
        for f in (norm(v), norm_abs(v)):
            if f is not None:
                allowed.add(f)

    for p in result.get("测点结果", []):
        c = p["计算结果"]
        for k in ("累计量", "本次变化量", "变化速率"):
            add(c.get(k))
        add(c.get("间隔天数"))
        interval_days.add(norm(c.get("间隔天数")))
        for k in ("观测值", "上一期观测值", "初始值"):
            add(p["原始数据"].get(k))
        # 附录表式 Excel 输入: 测值/高程/深度/裂缝分项同样属可追溯的原始填报值
        for k in ("本次测值", "上次测值", "初始高程", "本次高程", "上次高程", "深度"):
            add(p["原始数据"].get(k))
        for dim in ("长度", "宽度"):
            sub = p["原始数据"].get(dim) or {}
            for k in ("本次", "单次变化", "累计", "速率"):
                add(sub.get(k))

    ratio = float((cfg.get("levels") or {}).get("yellow_ratio", 0.7))
    for scope in list(cfg.get("items", {}).values()) + list(cfg.get("points", {}).values()):
        if not scope:
            continue
        for k in ("alarm", "control", "rate_alarm"):
            add(scope.get(k))
        alarm = scope.get("alarm")
        if alarm is not None:
            add(float(alarm) * ratio)  # 判定理由中的"报警值的 70%(xx)"派生值

    for v in list((cfg.get("levels") or {}).values()):
        add(v)
    for k in ("gross_error_sigma", "gross_error_ratio", "gross_error_min_abs"):
        add(cfg.get(k))

    # 计数类小整数(序号、测点数、页数、巡视条目数等)
    for i in range(0, 100):
        allowed.add(norm(i))
    return allowed, interval_days


def parse_rows(text: str):
    """返回 [(上下文, 测点号, [纯数值单元格])]。"""
    rows = []
    context = ""
    for line in text.splitlines():
        if line.startswith("## "):
            context = line[3:].strip()
        elif line.startswith("# "):
            context = "标题"
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") or c == "" for c in cells):
            continue
        point = next((c for c in cells if POINT_RE.match(c)), None)
        if not point:
            continue
        nums = [c for c in cells if PURE_NUM_RE.match(c)]
        rows.append((context, point, nums))
    return rows


def main():
    ap = argparse.ArgumentParser(description="日报数值一致性自检")
    ap.add_argument("--report", required=True)
    ap.add_argument("--result", required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    text = open(args.report, "r", encoding="utf-8").read()
    result = json.load(open(args.result, "r", encoding="utf-8"))
    cfg = json.load(open(args.config, "r", encoding="utf-8")) if args.config else {}

    allowed, interval_days = build_allowed(result, cfg)
    point_vals = {}
    for p in result.get("测点结果", []):
        c = p["计算结果"]
        point_vals[p["point_id"]] = {
            "累计量": norm(c.get("累计量")),
            "本次变化量": norm(c.get("本次变化量")),
        }

    rows = parse_rows(text)
    problems, checked_cells = [], 0
    # 表B 多孔格式的孔号前缀(如 CX-01) -> 按行内深度数值定位具体测点
    depth_by_point = {p["point_id"]: p["原始数据"].get("深度") for p in result.get("测点结果", []) if p.get("原始数据")}
    hole_prefixes = {}
    for pid in point_vals:
        if "@" in pid:
            hole_prefixes.setdefault(pid.split("@")[0], []).append(pid)
    for context, point, nums in rows:
        resolved = point
        if resolved not in point_vals and resolved in hole_prefixes:
            # 表B 行内深度为首列数值; 先按首数值定位, 无法唯一定位再放宽到行内任意数值
            norm_nums = [norm(n) for n in nums]
            cands = [pid for pid in hole_prefixes[resolved]
                     if depth_by_point.get(pid) is not None and norm(depth_by_point[pid]) in norm_nums[:1]]
            if len(cands) != 1:
                cands = [pid for pid in hole_prefixes[resolved]
                         if depth_by_point.get(pid) is not None and norm(depth_by_point[pid]) in norm_nums]
            if len(cands) == 1:
                resolved = cands[0]
        if resolved not in point_vals:
            problems.append("%s：出现未知测点 %s（计算结果中无此测点）" % (context, point))
            continue
        for n in nums:
            checked_cells += 1
            if norm(n) not in allowed and norm_abs(n) not in allowed:
                problems.append("%s：测点 %s 出现数值 %s，不在计算结果或阈值配置中" % (context, resolved, n))
        # 锚点检查只针对报表本体(表 A~F 与附表); “集中标识”表本身不含本次变化量列
        if context.startswith("表") or context.startswith("附表"):
            anchor = [v for v in point_vals[resolved].values() if v is not None]
            for v in anchor:
                if v not in [norm(n) for n in nums] and norm_abs(v) not in [norm_abs(n) for n in nums]:
                    problems.append("%s：测点 %s 的行内缺少计算结果中的 %s（累计量/本次变化量须与计算结果一致）" % (context, resolved, v))

    # 全文"数值+单位"检查：去掉已解析的数据行, 只看文字部分
    body = text
    for _, point, _ in rows:
        body = body.replace(point, "")
    outside = sorted({m.group(0) for m in QTY_RE.finditer(body)
                      if norm(m.group(1)) not in allowed and norm_abs(m.group(1)) not in allowed})

    lines = ["# 日报数值自检结果", "",
             "- 报告：`%s`" % os.path.basename(args.report),
             "- 解析表格数据行：%d 行；核验纯数值单元格：%d 个" % (len(rows), checked_cells), "",
             "## 1. 表格数值一致性", ""]
    if problems:
        lines += ["发现 %d 处问题：" % len(problems), ""] + ["- %s" % p for p in problems]
    else:
        lines.append("**通过**：表格中出现的数据均可在计算结果或阈值配置中找到同值字段；每个测点行的累计量、本次变化量与计算结果一致。")
    lines += ["", "## 2. 全文“数值+单位”人工确认清单", ""]
    if outside:
        lines.append("以下数字不在计算结果/阈值集合内，须人工判定是否为工况描述等处的非测点数字：")
        lines.append("")
        lines += ["- %s" % o for o in outside]
    else:
        lines.append("**通过**：全文未出现计算结果与阈值之外的“数值+单位”组合。")
    lines.append("")

    report = "\n".join(lines)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        open(args.out, "w", encoding="utf-8").write(report)
    print(report)


if __name__ == "__main__":
    main()
