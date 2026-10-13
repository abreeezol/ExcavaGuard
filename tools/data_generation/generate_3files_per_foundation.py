# -*- coding: utf-8 -*-
"""基坑监测数据集（每基础 3 文件版）：浅基础/深基础 各 3 个合并文件。

结构要求（用户指令「每个深浅都需要3个文件」）：
  - 浅基础：正常 / 中等预警 / 明显预警  → 3 个文件
  - 深基础：正常 / 中等预警 / 明显预警  → 3 个文件
  - 每个文件 = 一个工况的「表E + 表F」全部参数与测点（合并在同一张表），仅保留原始监测值。

设计原则：
1. 第一列=时间，精确到分钟；间隔=5 分钟；连续 7 天（2016 行）。
2. 仅输出「原始监测值」（单次采集的累计变形读数），不输出累计/本次变化/变化速率/报警值/预警等级
   ——派生量后续由 skill 计算。
3. 列顺序：时间 | 表E[地下水位8/地表竖向位移8/分层竖向位移6/坑底隆起6] | 表F[裂缝8长度+宽度8]。
4. 严重程度：
   - 正常：所有测点变形量均 < 70% 报警值（且速率 < 报警速率），完全合规。
   - 中等预警：含若干「橙色」测点（累计≥报警值且<控制值），无红色。
   - 明显预警：含若干「红色」测点（累计≥控制值）。
5. 每类参数 5–10 个测点（地下水位8 / 地表竖向位移8 / 分层竖向位移6 / 坑底隆起6 / 裂缝8）。
6. 物理方向：地下水位降深、坑底隆起、裂缝发展为正；地表/分层竖向位移（沉降）为负。
7. 固定随机种子，可复现；异常测点编号随文件变化，避免模型记忆位置。

输出目录：基坑监测7天数据/多工况/
  - 基坑监测_浅基础_正常_7天.csv / 基坑监测_浅基础_中等预警_7天.csv / 基坑监测_浅基础_明显预警_7天.csv
  - 基坑监测_深基础_正常_7天.csv / 基坑监测_深基础_中等预警_7天.csv / 基坑监测_深基础_明显预警_7天.csv
  - 数据集清单_3文件_manifest.json（每文件阈值集 + 异常测点 + 预期最严重等级）
"""
import csv, os, random, math, json, datetime, hashlib

OUT = r"C:\Users\xiaolong\WorkBuddy\2026-09-18-10-27-06\基坑监测7天数据\多工况"
os.makedirs(OUT, exist_ok=True)

INTERVAL_MIN = 5
N_DAYS = 7
N = N_DAYS * 24 * 60 // INTERVAL_MIN          # 2016
RATE_FACTOR = 1440.0 / INTERVAL_MIN           # 288（把 5-min 增量换算 mm/d）

# —— 各工况报警阈值（GB 50497-2019 表 8.0.4 / 8.0.5）——
TH = {
    "shallow": {  # 三级基坑（浅基础）：阈值更宽松（数值更大）
        "地下水位":      dict(warn_c=1500, control_c=2000, warn_r=350, control_r=500),
        "地表竖向位移":  dict(warn_c=45,   control_c=55,   warn_r=2,   control_r=3),
        "分层竖向位移":  dict(warn_c=None,  control_c=None,  warn_r=None, control_r=None),
        "坑底隆起":      dict(warn_c=30,   control_c=60,   warn_r=4,   control_r=10),
        "裂缝宽度":      dict(warn_c=10,   control_c=15,   warn_r=None, control_r=None),
        "裂缝长度":      dict(warn_c=None,  control_c=None,  warn_r=None, control_r=None),
    },
    "deep": {  # 一级基坑（深基础）：阈值更严（数值更小）
        "地下水位":      dict(warn_c=1500, control_c=2000, warn_r=350, control_r=500),
        "地表竖向位移":  dict(warn_c=25,   control_c=35,   warn_r=2,   control_r=3),
        "分层竖向位移":  dict(warn_c=None,  control_c=None,  warn_r=None, control_r=None),
        "坑底隆起":      dict(warn_c=30,   control_c=60,   warn_r=4,   control_r=10),
        "裂缝宽度":      dict(warn_c=10,   control_c=15,   warn_r=None, control_r=None),
        "裂缝长度":      dict(warn_c=None,  control_c=None,  warn_r=None, control_r=None),
    },
}

# —— 测点定义：每类 5–10 个 ——
E_POINTS = {
    "地下水位":     [f"SW-{i:02d}" for i in range(1, 9)],   # 8
    "地表竖向位移": [f"DBC-{i:02d}" for i in range(1, 9)],  # 8
    "分层竖向位移": [f"FC-{i:02d}" for i in range(1, 7)],   # 6
    "坑底隆起":     [f"KB-{i:02d}" for i in range(1, 7)],   # 6
}
F_POINTS = [f"LF-{i:02d}" for i in range(1, 9)]            # 8（裂缝，含长度+宽度）

# —— 异常测点目标累计变形量（endpoint 累计值，mm）——
ANOM = {
    "moderate": {"地下水位": 1700, "坑底隆起": 42, "裂缝宽度": 12},   # 地表在中等档保持正常，避免速率误红
    "obvious":  {"地下水位": 2050, "坑底隆起": 62, "裂缝宽度": 16,
                 "地表竖向位移": {"deep": -38, "shallow": -58}},
}


def init_offset(cat, rng):
    """起测时刻已有的初始变形（监测开始时通常已有少量变形）。"""
    if cat == "地下水位":     return rng.uniform(80, 250)
    if cat == "地表竖向位移": return rng.uniform(-5, -1)
    if cat == "分层竖向位移": return rng.uniform(-4, -1)
    if cat == "坑底隆起":     return rng.uniform(2, 8)
    if cat == "裂缝宽度":     return rng.uniform(1, 4)
    if cat == "裂缝长度":     return rng.uniform(30, 90)
    return 0.0


def normal_tc(cat, foundation, rng):
    """背景（合规）测点的 7 天总变形量（小，确保累计<70%报警值且速率<报警速率）。

    5 分钟采样下 速率=Δ×288，噪声被放大约 288 倍；地表竖向位移/坑底隆起的报警速率
    仅 2~4 mm/d，极紧。因此背景点必须用小变形量 + 平缓动力学，避免被噪声/日周期
    误判为橙色。异常点单独赋予越界目标累计量。
    """
    if cat == "地下水位":     return rng.uniform(150, 400)
    if cat == "地表竖向位移":
        return rng.uniform(-8, -3) if foundation == "deep" else rng.uniform(-9, -4)
    if cat == "分层竖向位移": return rng.uniform(2, 6)
    if cat == "坑底隆起":     return rng.uniform(6, 12)
    if cat == "裂缝宽度":     return rng.uniform(2, 4)
    if cat == "裂缝长度":     return rng.uniform(30, 90)
    return 0.0


# —— 平缓动力学：所有测点共用（背景与异常均用），保证背景点速率不误判 ——
# A=日周期振幅；sigma=高斯噪声（刻意很小，避免 5-min 速率被放大误报）
DYN = {
    "地下水位":     (8.0,  0.03),
    "地表竖向位移": (0.02, 0.0001),
    "分层竖向位移": (0.01, 0.0001),
    "坑底隆起":     (0.05, 0.0002),
    "裂缝宽度":     (0.02, 0.0001),
    "裂缝长度":     (0.50, 0.005),
}


def gen_series(init, total_change, A, sigma, seed):
    rng = random.Random(seed)
    raw = []
    for i in range(N):
        frac = i / (N - 1)
        trend = total_change * frac                      # 线性累计（平滑）
        daily = A * math.sin(2 * math.pi * (i * INTERVAL_MIN / 1440.0))
        noise = rng.gauss(0, sigma)
        raw.append(init + trend + daily + noise)
    off = raw[0] - init                                  # 使 t=0 时变形=0（累计从起测起算）
    return [v - off for v in raw]


def classify_series(raw, th):
    """按标准判定整条序列的最严重等级（供 manifest 标注，不写入数据）。"""
    rank = {"正常": 0, "黄色": 1, "橙色": 2, "红色": 3}
    worst = "正常"
    for i in range(N):
        cum = raw[i] - raw[0]
        rate = (raw[i] - raw[i - 1]) * RATE_FACTOR if i > 0 else 0.0
        lvl = _level_of(cum, rate, th)
        if rank[lvl] > rank[worst]:
            worst = lvl
    return worst


def _level_of(cum, rate, th):
    if th["warn_c"] is None:
        return "正常"
    ac, ar = abs(cum), abs(rate)
    if th["control_c"] is not None and ac >= th["control_c"]:
        return "红色"
    if (th["warn_c"] is not None and ac >= th["warn_c"]) or \
       (th["warn_r"] is not None and ar >= th["warn_r"]):
        return "橙色"
    if ac >= 0.7 * th["warn_c"]:
        return "黄色"
    return "正常"


def seed_for(*parts):
    h = hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return int(h[:12], 16)


# —— 每基础 3 个场景：正常 / 中等预警 / 明显预警 ——
SCENARIOS = [
    ("normal",   "正常"),
    ("moderate", "中等预警"),
    ("obvious",  "明显预警"),
]

BASE_DATE = datetime.datetime(2026, 10, 9, 8, 0, 0)
manifest = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "spec": {"interval_min": INTERVAL_MIN, "n_days": N_DAYS, "rows": N,
                     "thresholds": TH,
                     "points": {"E": E_POINTS, "F": F_POINTS}},
            "files": []}

for foundation in ("shallow", "deep"):
    fcn = "浅基础" if foundation == "shallow" else "深基础"
    for severity, sev_cn in SCENARIOS:
        start = BASE_DATE + datetime.timedelta(days=2 * len(manifest["files"]))
        tag = f"{fcn}_{sev_cn}"

        # 选异常测点编号（随文件随机，避免记忆位置）
        rng_sel = random.Random(seed_for(foundation, severity, "sel"))
        anomalies = {}  # cat -> point_id
        if severity in ("moderate", "obvious"):
            for cat in ("地下水位", "坑底隆起", "裂缝宽度"):
                pts = E_POINTS[cat] if cat in E_POINTS else F_POINTS
                anomalies[cat] = rng_sel.choice(pts)
            if severity == "obvious":
                anomalies["地表竖向位移"] = rng_sel.choice(E_POINTS["地表竖向位移"])

        file_entry = {"file_tag": tag, "foundation": foundation, "severity": severity,
                      "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                      "anomalies": {}, "expected_worst": {}}

        # —— 构造列（表E 在前，表F 在后）——
        header = ["时间"]
        col_meta = []   # (col_name, cat, sub_or_pid)
        for cat, pts in E_POINTS.items():
            for pid in pts:
                col = f"{cat}-{pid}-原始值(mm)"
                header.append(col); col_meta.append((col, cat, pid))
        for pid in F_POINTS:
            for sub in ("长度", "宽度"):
                col = f"裂缝-{pid}-{sub}-原始值(mm)"
                header.append(col); col_meta.append((col, "裂缝" + sub, pid))

        # —— 生成每一列序列 ——
        series_map = {}
        for col, cat, pid in col_meta:
            is_anom = False
            tc = None
            if cat in ("地下水位", "坑底隆起", "裂缝宽度", "地表竖向位移"):
                is_anom = (cat in anomalies and anomalies[cat] == pid)
            elif cat == "裂缝长度":
                is_anom = False  # 长度不作案，仅宽度作案
            if is_anom:
                if cat == "地表竖向位移":
                    tc = ANOM["obvious"]["地表竖向位移"][foundation]
                else:
                    tc = ANOM[severity][cat]
                tc *= rng_sel.uniform(0.97, 1.03)
            else:
                r2 = random.Random(seed_for(foundation, severity, cat, pid, "n"))
                tc = normal_tc(cat, foundation, r2)
            r3 = random.Random(seed_for(foundation, severity, cat, pid, "s"))
            if cat == "裂缝长度":
                init = init_offset("裂缝长度", r3)
                A, sigma = DYN["裂缝长度"]
            elif cat == "裂缝宽度":
                init = init_offset("裂缝宽度", r3)
                A, sigma = DYN["裂缝宽度"]
            else:
                init = init_offset(cat, r3)
                A, sigma = DYN[cat]
            series = gen_series(init, tc, A, sigma,
                                seed_for(foundation, severity, cat, pid))
            series_map[col] = series
            if is_anom:
                th = TH[foundation]["裂缝宽度"] if cat == "裂缝宽度" else TH[foundation][cat]
                lvl = classify_series(series, th)
                file_entry["anomalies"][col] = lvl
                file_entry["expected_worst"][col] = lvl

        # —— 写行 ——
        rows = []
        for i in range(N):
            ts = start + datetime.timedelta(minutes=INTERVAL_MIN * i)
            row = {"时间": ts.strftime("%Y-%m-%d %H:%M:%S")}
            for col, series in series_map.items():
                row[col] = f"{series[i]:.3f}"
            rows.append(row)

        out = os.path.join(OUT, f"基坑监测_{tag}_7天.csv")
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=header)
            w.writeheader(); w.writerows(rows)

        # 整体预期最严重等级
        worst_rank = 0
        for c, lvl in file_entry["expected_worst"].items():
            worst_rank = max(worst_rank, {"正常": 0, "黄色": 1, "橙色": 2, "红色": 3}[lvl])
        file_entry["scenario_expected"] = ["正常", "黄色", "橙色", "红色"][worst_rank]
        file_entry["file"] = os.path.basename(out)
        file_entry["n_columns"] = len(header) - 1
        manifest["files"].append(file_entry)
        print(f"[{tag}] 列数={len(header)-1}  异常测点数={len(file_entry['anomalies'])}  预期={file_entry['scenario_expected']}")

with open(os.path.join(OUT, "数据集清单_3文件_manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print("\nDONE. 文件数:", len(manifest["files"]))
