# -*- coding: utf-8 -*-
"""生成 表E / 表F 基坑监测数据（5 分钟高频，连续 7 天）。

真实性原则（与 GB 50497-2019 一致）：
1. 第一列=时间，精确到分钟；间隔=5 分钟（自动化监测典型采样频率）。
2. 每个监测类别下设多个检测位置；每个位置输出多列：累计值 / 本次变化 / 变化速率 / 报警值 / 预警等级。
3. 累计值 = 项目中段快照 + 7 天平滑漂移 + 日周期(抽水) + 微小噪声（确定性 seed，可复现）。
4. 变化速率 = 本次变化量 / (5/1440 d) = 本次变化量 × 288（mm/d）。
5. 预警等级依据仓库 thresholds_gb50497_2019.json（GB50497-2019 表8.0.4/8.0.5）判定：
   正常 / 黄色(≥70%报警值) / 橙色(≥报警值) / 红色(≥控制值)。
6. 物理方向：地下水位降深、坑底隆起、裂缝发展为正；地表/分层竖向位移（沉降）为负。
"""
import csv, os, random, math, datetime

SEED = 20261009
random.seed(SEED)
OUT = r"C:\Users\xiaolong\WorkBuddy\2026-09-18-10-27-06\基坑监测7天数据"
os.makedirs(OUT, exist_ok=True)

START = datetime.datetime(2026, 10, 9, 8, 0, 0)   # 起测时刻（基坑抽水开始后）
INTERVAL_MIN = 5
N_DAYS = 7
N = N_DAYS * 24 * 60 // INTERVAL_MIN              # = 2016 个时间戳
STEPS_PER_DAY = 24 * 60 // INTERVAL_MIN           # 288
RATE_FACTOR = 1440.0 / INTERVAL_MIN               # = 288，把 5-min 增量换算成 mm/d

def classify(cum, rate, warn_c, control_c, warn_r, control_r):
    """四级判定；warn/control 为 None 时跳过该项判据。累计与速率均取绝对值。"""
    ac, ar = abs(cum), abs(rate)
    if control_c is not None and ac >= control_c:
        return "红色预警", f"累计{ac:.2f}≥控制值{control_c:.0f}"
    if warn_c is not None and ac >= warn_c:
        return "橙色预警", f"累计{ac:.2f}≥报警值{warn_c:.0f}"
    if warn_c is not None and ac >= 0.7 * warn_c:
        return "黄色预警", f"累计{ac:.2f}≥报警值70%({0.7*warn_c:.0f})"
    if control_r is not None and ar >= control_r:
        return "红色预警", f"速率{ar:.2f}≥控制速率{control_r:.0f}"
    if warn_r is not None and ar >= warn_r:
        return "橙色预警", f"速率{ar:.2f}≥报警速率{warn_r:.1f}"
    if warn_r is not None and ar >= 0.7 * warn_r:
        return "黄色预警", f"速率{ar:.2f}≥报警速率70%({0.7*warn_r:.1f})"
    return "正常", "—"

def gen_channel(chan, rng):
    """生成单通道时序，返回 [(累计值, 本次变化, 速率), ...] 每步一条。"""
    base, trend, A, sigma, sign = chan["base"], chan["trend"], chan["A"], chan["sigma"], chan["sign"]
    cum = base
    prev_season = A * math.sin(2 * math.pi * ((START.hour + START.minute / 60.0) - 8) / 24)
    out = []
    for i in range(N):
        t = START + datetime.timedelta(minutes=INTERVAL_MIN * i)
        hour = t.hour + t.minute / 60.0
        season = A * math.sin(2 * math.pi * (hour - 8) / 24)
        season_inc = season - prev_season
        prev_season = season
        drift_inc = trend / N
        noise = rng.gauss(0, sigma)
        delta = drift_inc + season_inc + noise
        cum += delta
        cum_signed = sign * cum
        delta_signed = sign * delta
        rate = delta_signed * RATE_FACTOR
        out.append((cum_signed, delta_signed, rate))
    return out

# ============ 表E 监测类别与检测位置 ============
# 字段: cat, pid, channels[{label,sign,unit,base,trend,A,sigma,warn_c,control_c,warn_r,control_r,alarm}]
E_POSITIONS = [
    # —— 地下水位（降深，正）报警值 1500/2000，速率报警 350/500（GB50497 表8.0.5）——
    # SW-01 由正常→黄→橙→红（末段越过控制值2000）；SW-02/03 未达报警值
    {"cat": "地下水位", "pid": "SW-01", "channels": [
        {"label": "累计降深", "sign": 1, "unit": "mm", "base": 900, "trend": 1120, "A": 15, "sigma": 0.03,
         "warn_c": 1500, "control_c": 2000, "warn_r": 350, "control_r": 500, "alarm": "1500/2000"}]},
    {"cat": "地下水位", "pid": "SW-02", "channels": [
        {"label": "累计降深", "sign": 1, "unit": "mm", "base": 500, "trend": 420, "A": 15, "sigma": 0.03,
         "warn_c": 1500, "control_c": 2000, "warn_r": 350, "control_r": 500, "alarm": "1500/2000"}]},
    {"cat": "地下水位", "pid": "SW-03", "channels": [
        {"label": "累计降深", "sign": 1, "unit": "mm", "base": 250, "trend": 200, "A": 15, "sigma": 0.03,
         "warn_c": 1500, "control_c": 2000, "warn_r": 350, "control_r": 500, "alarm": "1500/2000"}]},
    # —— 地表竖向位移（沉降，负）报警值 25/35，速率 2/3（GB50497 表8.0.4 一级）——
    # DBC-02 末段越橙；DBC-01 末段越黄；DBC-03 全程正常
    {"cat": "地表竖向位移", "pid": "DBC-01", "channels": [
        {"label": "累计位移", "sign": -1, "unit": "mm", "base": 8, "trend": 12, "A": 0.1, "sigma": 0.001,
         "warn_c": 25, "control_c": 35, "warn_r": 2, "control_r": 3, "alarm": "25/35"}]},
    {"cat": "地表竖向位移", "pid": "DBC-02", "channels": [
        {"label": "累计位移", "sign": -1, "unit": "mm", "base": 15, "trend": 15, "A": 0.1, "sigma": 0.001,
         "warn_c": 25, "control_c": 35, "warn_r": 2, "control_r": 3, "alarm": "25/35"}]},
    {"cat": "地表竖向位移", "pid": "DBC-03", "channels": [
        {"label": "累计位移", "sign": -1, "unit": "mm", "base": 5, "trend": 8, "A": 0.1, "sigma": 0.001,
         "warn_c": 25, "control_c": 35, "warn_r": 2, "control_r": 3, "alarm": "25/35"}]},
    # —— 分层竖向位移（沉降，负）GB50497 未给阈值 → 报警值"待设计确认" ——
    {"cat": "分层竖向位移", "pid": "FC-01", "channels": [
        {"label": "累计位移", "sign": -1, "unit": "mm", "base": 4, "trend": 6, "A": 0.1, "sigma": 0.001,
         "warn_c": None, "control_c": None, "warn_r": None, "control_r": None, "alarm": "待设计确认"}]},
    {"cat": "分层竖向位移", "pid": "FC-02", "channels": [
        {"label": "累计位移", "sign": -1, "unit": "mm", "base": 3, "trend": 5, "A": 0.1, "sigma": 0.001,
         "warn_c": None, "control_c": None, "warn_r": None, "control_r": None, "alarm": "待设计确认"}]},
    # —— 坑底隆起（回弹，正）报警值 30/60，速率 4/10（GB50497 表8.0.4，不分等级）——
    {"cat": "坑底隆起", "pid": "KB-01", "channels": [
        {"label": "累计隆起", "sign": 1, "unit": "mm", "base": 20, "trend": 15, "A": 0.3, "sigma": 0.003,
         "warn_c": 30, "control_c": 60, "warn_r": 4, "control_r": 10, "alarm": "30/60"}]},
    {"cat": "坑底隆起", "pid": "KB-02", "channels": [
        {"label": "累计隆起", "sign": 1, "unit": "mm", "base": 10, "trend": 12, "A": 0.3, "sigma": 0.003,
         "warn_c": 30, "control_c": 60, "warn_r": 4, "control_r": 10, "alarm": "30/60"}]},
]

# ============ 表F 裂缝（地表裂缝，含长度+宽度子项）============
# 宽度报警值 10/15（GB50497 表8.0.5 地表裂缝既有）；长度无规范阈值。
F_POSITIONS = [
    {"cat": "裂缝", "pid": "LF-01", "channels": [
        {"label": "长度累计", "sign": 1, "unit": "mm", "base": 120, "trend": 30, "A": 0.3, "sigma": 0.005,
         "warn_c": None, "control_c": None, "warn_r": None, "control_r": None, "alarm": "待设计确认"},
        {"label": "宽度累计", "sign": 1, "unit": "mm", "base": 8, "trend": 5, "A": 0.03, "sigma": 0.001,
         "warn_c": 10, "control_c": 15, "warn_r": None, "control_r": None, "alarm": "10/15"}]},
    {"cat": "裂缝", "pid": "LF-02", "channels": [
        {"label": "长度累计", "sign": 1, "unit": "mm", "base": 80, "trend": 20, "A": 0.3, "sigma": 0.005,
         "warn_c": None, "control_c": None, "warn_r": None, "control_r": None, "alarm": "待设计确认"},
        {"label": "宽度累计", "sign": 1, "unit": "mm", "base": 4, "trend": 4, "A": 0.03, "sigma": 0.001,
         "warn_c": 10, "control_c": 15, "warn_r": None, "control_r": None, "alarm": "10/15"}]},
    {"cat": "裂缝", "pid": "LF-03", "channels": [
        {"label": "长度累计", "sign": 1, "unit": "mm", "base": 150, "trend": 25, "A": 0.3, "sigma": 0.005,
         "warn_c": None, "control_c": None, "warn_r": None, "control_r": None, "alarm": "待设计确认"},
        {"label": "宽度累计", "sign": 1, "unit": "mm", "base": 12, "trend": 6, "A": 0.03, "sigma": 0.001,
         "warn_c": 10, "control_c": 15, "warn_r": None, "control_r": None, "alarm": "10/15"}]},
]

def build_table(positions):
    """返回 (表头列表, 行列表)。"""
    rng = random.Random(SEED)
    # 预生成每个位置每个通道的时序
    series = {}   # (pos_idx, ch_idx) -> list of (cum, delta, rate)
    for pi, pos in enumerate(positions):
        for ci, ch in enumerate(pos["channels"]):
            series[(pi, ci)] = gen_channel(ch, rng)
    # 表头
    headers = ["时间"]
    ch_meta = []   # (列前缀, ch)
    for pi, pos in enumerate(positions):
        prefix = f"{pos['cat']}-{pos['pid']}"
        for ci, ch in enumerate(pos["channels"]):
            col_prefix = f"{prefix}-{ch['label']}"
            headers += [
                f"{col_prefix}-累计值(mm)",
                f"{col_prefix}-本次变化(mm)",
                f"{col_prefix}-变化速率(mm/d)",
                f"{col_prefix}-报警值",
                f"{col_prefix}-预警等级",
            ]
            ch_meta.append((col_prefix, ch))
    # 行
    rows = []
    for i in range(N):
        t = START + datetime.timedelta(minutes=INTERVAL_MIN * i)
        row = {"时间": t.strftime("%Y-%m-%d %H:%M:%S")}
        for (pi, ci), (col_prefix, ch) in zip(series.keys(), ch_meta):
            cum, delta, rate = series[(pi, ci)][i]
            lvl, reason = classify(cum, rate, ch["warn_c"], ch["control_c"], ch["warn_r"], ch["control_r"])
            row[f"{col_prefix}-累计值(mm)"] = f"{cum:.2f}"
            row[f"{col_prefix}-本次变化(mm)"] = f"{delta:.3f}"
            row[f"{col_prefix}-变化速率(mm/d)"] = f"{rate:.2f}"
            row[f"{col_prefix}-报警值"] = ch["alarm"]
            row[f"{col_prefix}-预警等级"] = lvl
        rows.append(row)
    return headers, rows

for tag, positions in [("E", E_POSITIONS), ("F", F_POSITIONS)]:
    headers, rows = build_table(positions)
    fn = os.path.join(OUT, f"表{tag}_监测数据_7天.csv")
    with open(fn, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)
    # 统计预警分布
    from collections import Counter
    cnt = Counter()
    for r in rows:
        for h in headers:
            if h.endswith("预警等级"):
                cnt[r[h]] += 1
    print(f"写入 表{tag}: {fn}")
    print(f"  行数={len(rows)}  列数={len(headers)}  预警分布={dict(cnt)}")

print("\n生成完成。输出目录:", OUT)
