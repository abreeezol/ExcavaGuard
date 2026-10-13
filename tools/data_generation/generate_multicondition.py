# -*- coding: utf-8 -*-
"""基坑监测多工况原始值数据集生成器（仅保留原始监测值，不含派生量）。

设计原则：
1. 第一列=时间，精确到分钟；间隔=5 分钟；连续 7 天（2016 行）。
2. 仅输出「原始监测值」（单次采集的累计变形读数），不输出累计/本次变化/变化速率/报警值/预警等级
   ——派生量后续由 skill 计算（本报告仅造原始值 + 一份独立的「预期标注」清单供模型自检）。
3. 工况：浅基础（三级基坑）/ 深基础（一级基坑），报警阈值不同（见 TH）。
4. 严重程度：
   - 正常：所有测点变形量均 < 70% 报警值（且速率 < 报警速率），完全合规。
   - 中等预警：含若干「橙色」测点（累计≥报警值且<控制值），无红色。
   - 明显预警：含若干「红色」测点（累计≥控制值）。
5. 每类参数 5–10 个测点（地下水位8 / 地表竖向位移8 / 分层竖向位移6 / 坑底隆起6 / 裂缝8）。
6. 物理方向：地下水位降深、坑底隆起、裂缝发展为正；地表/分层竖向位移（沉降）为负。
7. 固定随机种子，可复现；异常测点编号随文件变化，避免模型记忆位置。

输出目录：基坑监测7天数据/多工况/
  - 表E_浅基础_正常_01_7天.csv / 表F_浅基础_正常_01_7天.csv ...（每种工况、严重度一个 E+F 对）
  - 数据集清单_manifest.json（含每文件阈值集 + 异常测点 + 预期最严重等级，供模型验证用）
"""
import csv, os, random, math, json, datetime, hashlib

OUT = r"C:\Users\xiaolong\WorkBuddy\2026-09-18-10-27-06\基坑监测7天数据\多工况"
os.makedirs(OUT, exist_ok=True)

INTERVAL_MIN = 5
N_DAYS = 7
N = N_DAYS * 24 * 60 // INTERVAL_MIN          # 2016
STEPS_PER_DAY = 24 * 60 // INTERVAL_MIN       # 288
RATE_FACTOR = 1440.0 / INTERVAL_MIN           # 288（把 5-min 增量换算 mm/d）

# —— 各工况报警阈值（GB 50497-2019 表 8.0.4 / 8.0.5）——
# warn_c/control_c: 累计值报警/控制；warn_r/control_r: 变化速率报警/控制；None 表示规范未给阈值
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
# 中等预警：落在 [报警值, 控制值) 区间（橙色）；明显预警：≥控制值（红色）
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
    """正常测点的 7 天总变形量（小，确保合规）。"""
    if cat == "地下水位":     return rng.uniform(200, 600)
    if cat == "地表竖向位移":
        return rng.uniform(-11, -5) if foundation == "deep" else rng.uniform(-11, -6)
    if cat == "分层竖向位移": return rng.uniform(3, 9)
    if cat == "坑底隆起":     return rng.uniform(8, 16)
    if cat == "裂缝宽度":     return rng.uniform(2, 5)
    if cat == "裂缝长度":     return rng.uniform(40, 120)
    return 0.0


def dyn_par(cat):
    """日周期振幅 A 与高斯噪声 sigma。"""
    return {
        "地下水位":     (15.0, 0.6),
        "地表竖向位移": (0.15, 0.01),
        "分层竖向位移": (0.10, 0.008),
        "坑底隆起":     (0.40, 0.02),
        "裂缝宽度":     (0.05, 0.003),
        "裂缝长度":     (1.50, 0.05),
    }[cat]


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


# —— 工况 × 严重度 配置：每基础 4 个场景（2 正常 / 1 中等 / 1 明显）——
SCENARIOS = [
    ("normal",   2),
    ("moderate", 1),
    ("obvious",  1),
]

BASE_DATE = datetime.datetime(2026, 10, 9, 8, 0, 0)
gidx = 0
manifest = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "spec": {"interval_min": INTERVAL_MIN, "n_days": N_DAYS, "rows": N,
                     "thresholds": TH,
                     "points": {"E": E_POINTS, "F": F_POINTS}},
            "files": []}

for foundation in ("shallow", "deep"):
    fcn = "浅基础" if foundation == "shallow" else "深基础"
    for severity, count in SCENARIOS:
        for k in range(count):
            gidx += 1
            start = BASE_DATE + datetime.timedelta(days=2 * (gidx - 1))
            sev_cn = {"normal": "正常", "moderate": "中等预警", "obvious": "明显预警"}[severity]
            tag = f"{fcn}_{sev_cn}_{k+1:02d}"

            # 选异常测点编号（随文件随机，避免记忆位置）
            rng_sel = random.Random(seed_for(foundation, severity, k, "sel"))
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

            # ===== 表E =====
            e_header = ["时间"]
            e_cols = {}   # point_key -> list
            for cat, pts in E_POINTS.items():
                for pid in pts:
                    col = f"{cat}-{pid}-原始值(mm)"
                    e_header.append(col)
                    is_anom = (cat in anomalies and anomalies[cat] == pid)
                    if is_anom:
                        if cat == "地表竖向位移":
                            tc = ANOM["obvious"]["地表竖向位移"][foundation]
                        else:
                            tc = ANOM[severity][cat]
                        tc *= rng_sel.uniform(0.97, 1.03)
                    else:
                        r2 = random.Random(seed_for(foundation, severity, k, cat, pid, "n"))
                        tc = normal_tc(cat, foundation, r2)
                    r3 = random.Random(seed_for(foundation, severity, k, cat, pid, "s"))
                    init = init_offset(cat, r3)
                    A, sigma = dyn_par(cat)
                    series = gen_series(init, tc, A, sigma,
                                        seed_for(foundation, severity, k, cat, pid))
                    e_cols[col] = series
                    if is_anom:
                        file_entry["anomalies"][col] = classify_series(series, TH[foundation][cat])
                        file_entry["expected_worst"][col] = classify_series(series, TH[foundation][cat])

            e_rows = []
            for i in range(N):
                ts = start + datetime.timedelta(minutes=INTERVAL_MIN * i)
                row = {"时间": ts.strftime("%Y-%m-%d %H:%M:%S")}
                for col, series in e_cols.items():
                    row[col] = f"{series[i]:.3f}"
                e_rows.append(row)

            ef = os.path.join(OUT, f"表E_{tag}_7天.csv")
            with open(ef, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=e_header)
                w.writeheader(); w.writerows(e_rows)
            file_entry["e_file"] = os.path.basename(ef)

            # ===== 表F（裂缝：长度 + 宽度）=====
            f_header = ["时间"]
            f_cols = {}
            for pid in F_POINTS:
                for sub in ("长度", "宽度"):
                    col = f"裂缝-{pid}-{sub}-原始值(mm)"
                    f_header.append(col)
                    is_anom = (severity in ("moderate", "obvious") and
                               "裂缝宽度" in anomalies and anomalies["裂缝宽度"] == pid and sub == "宽度")
                    r2 = random.Random(seed_for(foundation, severity, k, "F", pid, sub, "n"))
                    if is_anom:
                        tc = ANOM[severity]["裂缝宽度"] * rng_sel.uniform(0.97, 1.03)
                        r3 = random.Random(seed_for(foundation, severity, k, "F", pid, sub, "s"))
                        init = init_offset("裂缝宽度", r3)
                        A, sigma = dyn_par("裂缝宽度")
                    else:
                        tc = normal_tc("裂缝长度" if sub == "长度" else "裂缝宽度", foundation, r2)
                        r3 = random.Random(seed_for(foundation, severity, k, "F", pid, sub, "s"))
                        init = init_offset("裂缝长度" if sub == "长度" else "裂缝宽度", r3)
                        A, sigma = dyn_par("裂缝长度" if sub == "长度" else "裂缝宽度")
                    series = gen_series(init, tc, A, sigma,
                                        seed_for(foundation, severity, k, "F", pid, sub))
                    f_cols[col] = series
                    if is_anom:
                        file_entry["anomalies"][col] = classify_series(series, TH[foundation]["裂缝宽度"])
                        file_entry["expected_worst"][col] = classify_series(series, TH[foundation]["裂缝宽度"])

            f_rows = []
            for i in range(N):
                ts = start + datetime.timedelta(minutes=INTERVAL_MIN * i)
                row = {"时间": ts.strftime("%Y-%m-%d %H:%M:%S")}
                for col, series in f_cols.items():
                    row[col] = f"{series[i]:.3f}"
                f_rows.append(row)

            ff = os.path.join(OUT, f"表F_{tag}_7天.csv")
            with open(ff, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=f_header)
                w.writeheader(); w.writerows(f_rows)
            file_entry["f_file"] = os.path.basename(ff)

            # 整体预期最严重等级 = 所有异常测点中最严重者
            worst_rank = 0
            for c, lvl in file_entry["expected_worst"].items():
                worst_rank = max(worst_rank, {"正常": 0, "黄色": 1, "橙色": 2, "红色": 3}[lvl])
            file_entry["scenario_expected"] = ["正常", "黄色", "橙色", "红色"][worst_rank]
            manifest["files"].append(file_entry)
            print(f"[{tag}] E={len(e_header)-1}列 F={len(f_header)-1}列  异常测点数={len(file_entry['anomalies'])}  预期={file_entry['scenario_expected']}")

with open(os.path.join(OUT, "数据集清单_manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print("\nDONE. 文件数:", len(manifest["files"]))
