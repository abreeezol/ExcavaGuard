# -*- coding: utf-8 -*-
"""生成 7 天基坑监测数据（示例地铁一级基坑，17 测点，表A~表G）。
真实性原则：
1. 累计变化量 = 项目中段快照 + 7 天平滑随机游走（确定性 seed，可复现）。
2. 变化速率 = 当日变化量 / 1d（1 次/d 监测频率，表7.0.3 一级底板后≤7d=1次/d）。
3. 预警等级依据仓库 thresholds_gb50497_2019.json（GB50497-2019 表8.0.4/8.0.5）判定。
4. 物理方向：沉降/水位下降为负，水平位移/隆起/轴力为正。
"""
import csv, os, random, datetime

SEED = 20261009
random.seed(SEED)
OUT = r"C:\Users\xiaolong\WorkBuddy\2026-09-18-10-27-06\基坑监测7天数据"
os.makedirs(OUT, exist_ok=True)

START_DATE = datetime.date(2026, 10, 9)   # 连续7天
N_DAYS = 7
REPORT_START = 58                         # 报表次数（延续项目计数）

def daterow(i):
    d = START_DATE + datetime.timedelta(days=i)
    return d.strftime("%Y-%m-%d"), REPORT_START + i

def classify(cum, rate, warn_c, control_c, warn_r, control_r):
    """四级判定：正常 / 黄色(≥70%报警值) / 橙色(≥报警值) / 红色(≥控制值)。
    warn/control 为 None 时跳过该项判据。累计与速率均取绝对值比较。"""
    ac = abs(cum); ar = abs(rate)
    # 累计判据（优先）
    if control_c and ac >= control_c:
        return "红色预警", f"累计{ac:.2f}≥控制值{control_c:.0f}"
    if warn_c and ac >= warn_c:
        return "橙色预警", f"累计{ac:.2f}≥报警值{warn_c:.0f}"
    if warn_c and ac >= 0.7*warn_c:
        return "黄色预警", f"累计{ac:.2f}≥报警值70%({0.7*warn_c:.0f})"
    # 速率判据
    if control_r and ar >= control_r:
        return "红色预警", f"速率{ar:.2f}≥控制速率{control_r:.0f}"
    if warn_r and ar >= warn_r:
        return "橙色预警", f"速率{ar:.2f}≥报警速率{warn_r:.1f}"
    if warn_r and ar >= 0.7*warn_r:
        return "黄色预警", f"速率{ar:.2f}≥报警速率70%({0.7*warn_r:.1f})"
    return "正常", "—"

# 测点定义：(表, 点号, 监测项目, 单位, 起始累计, 日增量均值, 日增量标准差,
#           报警累计warn_c, 控制累计control_c, 报警速率warn_r, 控制速率control_r)
# warn/control=None 表示该维度无规范绝对值判据（如土压力取设计比值、深层水平未给速率）
POINTS = [
    # 表A 墙顶水平位移（7点）一级: 报警值25 / 控制值30 / 速率报警2.5 / 控制3.0
    ("A","ZQS-01","墙顶水平位移","mm", 9, 1.3,0.5, 25,30, 2.5,3.0),
    ("A","ZQS-02","墙顶水平位移","mm",12, 1.4,0.5, 25,30, 2.5,3.0),
    ("A","ZQS-03","墙顶水平位移","mm",15, 1.6,0.6, 25,30, 2.5,3.0),
    ("A","ZQS-04","墙顶水平位移","mm",33, 2.4,0.8, 25,30, 2.5,3.0),  # 起始已超控制值→红
    ("A","ZQS-05","墙顶水平位移","mm", 7, 1.0,0.4, 25,30, 2.5,3.0),
    ("A","ZQS-06","墙顶水平位移","mm",10, 1.3,0.5, 25,30, 2.5,3.0),
    ("A","ZQS-07","墙顶水平位移","mm",14, 1.5,0.6, 25,30, 2.5,3.0),
    # 表B 深层水平位移（4点）一级: 报警值40 / 控制值50 / 速率未给
    ("B","CX-01@0.5m","深层水平位移","mm",14, 0.9,0.4, 40,50, None,None),
    ("B","CX-01@2m","深层水平位移","mm",12, 0.8,0.4, 40,50, None,None),
    ("B","CX-01@4m","深层水平位移","mm", 9, 0.7,0.3, 40,50, None,None),
    ("B","CX-02@0.5m","深层水平位移","mm",16, 0.9,0.4, 40,50, None,None),
    # 表C 土压力（1点，kPa，规范未给绝对值报警→仅正常）
    ("C","TP-01","围护墙侧向土压力","kPa",38, 0.6,0.3, None,None, None,None),
    # 表D 支撑轴力（1点，kN）报警值3000 / 控制值3500
    ("D","ZL-01","支撑轴力","kN",2810, 32,12, 3000,3500, None,None),
    # 表E 地下水位+地表竖向位移（3点）
    ("E","SW-01","地下水位","mm",-1650,-60,18, 1500,2000, 400,500),
    ("E","DBC-01","地表竖向位移","mm",-14,-1.6,0.6, 25,35, 2.5,3.0),
    ("E","DBC-02","地表竖向位移","mm",-19,-2.2,0.8, 25,35, 2.5,3.0),
    # 表F 裂缝宽度（1点，mm）既有裂缝报警1.5 / 控制3.0 / 速率0.2/0.25
    ("F","LF-01","周边地表裂缝(宽度)","mm",1.10,0.06,0.03, 1.5,3.0, 0.2,0.25),
]

# 把测点按表分组
TABLES = {}
for p in POINTS:
    TABLES.setdefault(p[0], []).append(p)

def gen_point(p):
    tbl, pid, item, unit, start, mu, sigma, warn_c, control_c, warn_r, control_r = p
    rows = []
    cum = start
    for i in range(N_DAYS):
        date, rep = daterow(i)
        delta = random.gauss(mu, sigma)
        # 深层/水位的日增量取绝对值再定向
        if item in ("地下水位",):
            delta = -abs(delta)            # 水位持续下降
        elif item in ("地表竖向位移",):
            delta = -abs(delta)            # 地表沉降为负
        elif item == "围护墙侧向土压力":
            delta = abs(delta)
        # 累计更新
        prev = cum
        cum = prev + delta
        rate = delta  # 1次/d → 速率=单次变化量
        lvl, reason = classify(cum, rate, warn_c, control_c, warn_r, control_r)
        rows.append({
            "日期": date, "报表次数": f"第{rep}次",
            "点号": pid, "监测项目": item, "单位": unit,
            "上次累计": round(prev,2), "本次累计": round(cum,2),
            "本次变化量": round(delta,2), "变化速率": round(rate,2),
            "预警等级": lvl, "备注": reason,
        })
    return rows

HEADERS = ["日期","报表次数","点号","监测项目","单位","上次累计","本次累计","本次变化量","变化速率","预警等级","备注"]

for tbl, plist in TABLES.items():
    allrows = []
    for p in plist:
        allrows.extend(gen_point(p))
    # 按日期排序
    allrows.sort(key=lambda r:(r["日期"], r["点号"]))
    fn = os.path.join(OUT, f"表{tbl}_监测数据_7天.csv")
    with open(fn, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS)
        w.writeheader()
        w.writerows(allrows)
    print(f"写入 {fn}: {len(allrows)} 行 ({len(plist)} 测点 x {N_DAYS} 天)")

# 表G 巡视检查（定性，非时序数值）——每天一组检查
G_CATS = [
    ("支护结构","支护结构成型质量","良好"),
    ("支护结构","冠梁、围檩、支撑裂缝","未发现新增裂缝"),
    ("支护结构","基坑有无涌土、流砂、管涌","未见"),
    ("施工工况","开挖分段长度及分层厚度","分段约20m，分层约3m，符合方案"),
    ("施工工况","基坑周边地面堆载","东侧堆载超限，已通知整改"),
    ("周边环境","周边道路有无新裂缝或沉陷","东侧人行道新增细裂缝1条，已布设LF-01"),
    ("监测设施","基准点、测点完好状况","ZQS-05保护盖损坏，已报修"),
]
grows = []
for i in range(N_DAYS):
    date, rep = daterow(i)
    for cat, content, res in G_CATS:
        grows.append({"日期":date,"报表次数":f"第{rep}次","分类":cat,
                      "巡视检查内容":content,"巡视检查结果":res,"备注":"—"})
fn = os.path.join(OUT, "表G_巡视检查_7天.csv")
with open(fn, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["日期","报表次数","分类","巡视检查内容","巡视检查结果","备注"])
    w.writeheader(); w.writerows(grows)
print(f"写入 {fn}: {len(grows)} 行")

print("\n生成完成。输出目录:", OUT)
