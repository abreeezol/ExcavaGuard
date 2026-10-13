# -*- coding: utf-8 -*-
"""构造附录 C~F 的最小宽表测试样本（仅累计量列），用于验证 convert 的附录模板渲染
与 design_ratio 报警值计算/未判定逻辑。非真实工程数据，纯结构验证。"""
import os, datetime
import openpyxl

OUT = r"D:\deep-pit-monitoring-report\examples\附表CDEF_测试数据.xlsx"
base = datetime.datetime(2026, 10, 5, 0, 0, 0)

# 点号前缀 -> (测项, 单位, 各日末累计量序列, 是否 design_ratio)
points = [
    ("CN-01", "围护墙内力", [700.0, 750.0, 820.0]),   # 设计值1000 -> 报警800，末日超
    ("CN-02", "围护墙内力", [300.0, 360.0, 410.0]),   # <- 50%
    ("CL-01", "立柱内力",   [500.0, 560.0, 610.0]),   # 设计值800 -> 报警640
    ("CT-01", "土压力",     [120.0, 150.0, 180.0]),   # 设计值220 -> 报警176
    ("CK-01", "孔隙水压力", [90.0, 110.0, 130.0]),    # 设计值160 -> 报警112(一级70%)
    ("DN-01", "支撑轴力",   [1500.0, 1550.0, 1620.0]),# 设计值2000 -> 报警1600，末日超
    ("DM-01", "锚杆轴力",   [900.0, 1000.0, 1080.0]), # 设计值1500 -> 报警1050(一级70%)
    ("EW-01", "地下水位",   [800.0, 1200.0, 1500.0]), # absolute 1000~2000mm
    ("ES-01", "地表竖向位移", [15.0, 22.0, 28.0]),    # absolute 20~30mm，末日超
    ("EB-01", "坑底隆起",   [20.0, 30.0, 40.0]),      # absolute 25~35mm(一级)，末日超
    ("F-01",  "裂缝",       [0.15, 0.21, 0.27]),      # absolute 0.2~0.25mm，末日超
    ("F-02",  "裂缝",       [0.10, 0.12, 0.14]),      # 正常
]

# design_ratio 类设计值
DESIGN = {"CN-01": 1000, "CN-02": 1000, "CL-01": 800, "CT-01": 220, "CK-01": 160,
          "DN-01": 2000, "DM-01": 1500}

days = 3
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "监测数据"
header = ["日期"] + [p[0] for p in points]
ws.append(header)
for d in range(days):
    row = [base + datetime.timedelta(days=d, hours=8 * (d % 1))]
    for p in points:
        # 当天用一个采样点即可（daily_summary 取每日末）
        row.append(p[2][d])
    ws.append(row)
wb.save(OUT)

# 同时写出 design 映射 JSON，供 --point-design 使用
import json
with open(os.path.splitext(OUT)[0] + "_design.json", "w", encoding="utf-8") as f:
    json.dump(DESIGN, f, ensure_ascii=False, indent=2)
print("SAVED", OUT, "点数", len(points))
