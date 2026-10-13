# -*- coding: utf-8 -*-
"""生成 GB 50497-2019 附录A(水平/竖向位移)与附录B(深层水平位移)的测试数据样本。
排列形式参考用户提供的盾构实时监控日志(首列时间戳 + 多列监测值 的宽表)。
仅含"累计位移量"一列；采样频率 10 分钟/次；持续 1 周；每表 15 个监测点。
阈值依据 GB 50497-2019 表8.0.4：水平/深层水平位移报警值 一级30mm、二级50mm、三级80mm。
工况映射：深基础工况->一级基坑(报警30mm)，浅基础工况->二级基坑(报警50mm)。
三类：正常(累计<70%报警值)、橙色预警(>=70%且<100%报警值)、红色预警(>=100%报警值)。
"""
import os, random, datetime, openpyxl

OUT = r"D:\deep-pit-monitoring-report\examples\附表AB_测试数据_10分钟_一周.xlsx"

random.seed(20261011)
N = 7 * 24 * 6          # 1008 个采样点（7天 × 每天144次，10分钟一次）
START = datetime.datetime(2026, 10, 5, 0, 0, 0)
STEP = datetime.timedelta(minutes=10)
TIMES = [START + STEP * i for i in range(N)]

# 报警值(mm)：浅基础(二级) 50，深基础(一级) 30  —— 水平位移与深层水平位移同值
ALARM = {"浅": 50.0, "深": 30.0}

def gen_series(target, sigma=0.06):
    """生成一条累计位移量序列，末值精确落在 target(mm)。"""
    base = target / N
    inc = [max(0.0, base + random.gauss(0.0, sigma)) for _ in range(N)]
    cum = []
    s = 0.0
    for x in inc:
        s += x
        cum.append(s)
    drift = cum[-1] - target
    for i in range(N):
        cum[i] -= drift * (i / (N - 1))
    return [round(v, 1) for v in cum]

# (点号, 工况浅/深, 类别正常/橙/红, 占报警值比例frac)
A_POINTS = [
    ("A-SH-01", "浅", "正常", 0.50), ("A-SH-02", "浅", "正常", 0.45),
    ("A-SH-03", "浅", "正常", 0.60), ("A-SH-04", "浅", "橙", 0.80),
    ("A-SH-05", "浅", "橙", 0.88),  ("A-SH-06", "浅", "红", 1.15),
    ("A-SH-07", "浅", "正常", 0.55), ("A-SH-08", "浅", "橙", 0.78),
    ("A-DP-01", "深", "正常", 0.50), ("A-DP-02", "深", "正常", 0.55),
    ("A-DP-03", "深", "正常", 0.62), ("A-DP-04", "深", "橙", 0.82),
    ("A-DP-05", "深", "橙", 0.92),  ("A-DP-06", "深", "红", 1.08),
    ("A-DP-07", "深", "红", 1.20),
]
B_POINTS = [
    ("B-SH-01", "浅", "正常", 0.48), ("B-SH-02", "浅", "正常", 0.52),
    ("B-SH-03", "浅", "橙", 0.82),  ("B-SH-04", "浅", "橙", 0.90),
    ("B-SH-05", "浅", "红", 1.18),  ("B-SH-06", "浅", "正常", 0.58),
    ("B-SH-07", "浅", "红", 1.05),
    ("B-DP-01", "深", "正常", 0.45), ("B-DP-02", "深", "正常", 0.55),
    ("B-DP-03", "深", "正常", 0.60), ("B-DP-04", "深", "橙", 0.80),
    ("B-DP-05", "深", "橙", 0.90),  ("B-DP-06", "深", "红", 1.10),
    ("B-DP-07", "深", "红", 1.25),  ("B-DP-08", "深", "正常", 0.50),
]

def level_of(frac):
    if frac >= 1.0:
        return "红色预警"
    if frac >= 0.7:
        return "橙色预警"
    return "正常(符合规范)"

def build_sheet(wb, title, points, proj):
    ws = wb.create_sheet(title)
    headers = ["日期"] + [f"{pid}(累计位移量mm)" for pid, _, _, _ in points]
    ws.append(headers)
    series = {}
    for pid, cond, cat, frac in points:
        alarm = ALARM[cond]
        series[pid] = gen_series(round(frac * alarm, 1))
    for i, t in enumerate(TIMES):
        row = [t] + [series[pid][i] for pid, _, _, _ in points]
        ws.append(row)
    ws.freeze_panes = "B2"
    # 列宽
    ws.column_dimensions["A"].width = 20
    for c in range(2, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = 16
    return ws, points, series

def build_legend(wb, points, series):
    ws = wb.create_sheet("说明与图例")
    ws.append(["点号", "所属附表", "监测项目", "工况", "预警等级(按数据判定)",
               "报警值(mm)", "末次累计位移(mm)", "占报警值比例(%)", "是否超报警值"])
    for pid, cond, cat, frac in points:
        alarm = ALARM[cond]
        final = series[pid][-1]
        ratio = final / alarm * 100.0
        lvl = level_of(final / alarm)
        over = "是" if final >= alarm else "否"
        proj = "附表B" if pid.startswith("B") else "附表A"
        moni = "水平位移" if proj == "附表A" else "深层水平位移"
        ws.append([pid, proj, moni,
                   "浅基础工况" if cond == "浅" else "深基础工况", lvl,
                   alarm, final, round(ratio, 1), over])
    widths = [12, 10, 14, 14, 18, 12, 16, 16, 14]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

def main():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # 删掉默认空表
    wsA, pa, sa = build_sheet(wb, "附表A_水平位移", A_POINTS, "附表A")
    wsB, pb, sb = build_sheet(wb, "附表B_深层水平位移", B_POINTS, "附表B")
    build_legend(wb, A_POINTS + B_POINTS, {**sa, **sb})
    wb.save(OUT)
    print("SAVED", OUT)
    print("A点:", len(pa), "B点:", len(pb), "行数/表:", N + 1)

if __name__ == "__main__":
    main()
