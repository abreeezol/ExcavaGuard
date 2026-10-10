"""
关键数据文件深度剖析：针对基坑监测可用性做语义级分析。
只读原始文件；结果写入 derived/。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(r"C:\Study\bisai\Hai AI Agent\基坑智守项目相关数据")
OUT = Path(r"C:\Study\bisai\Hai AI Agent\ExcavaGuard\确定性计算层\derived")
OUT.mkdir(parents=True, exist_ok=True)
D = ROOT / "多传感器隧道监测数据" / "sensors_public_dataset" / "data"

res: dict = {"generated_at": datetime.now().isoformat(timespec="seconds"), "sections": {}}


def put(k, v):
    res["sections"][k] = v
    print(f"\n===== {k} =====")
    print(json.dumps(v, ensure_ascii=False, indent=2, default=str)[:4000])


# ---------- 1. observations ----------
obs = pd.read_csv(D / "observations.csv")
put(
    "observations_overview",
    {
        "rows": len(obs),
        "cols": list(obs.columns),
        "missing_per_col": {c: int(obs[c].isna().sum()) for c in obs.columns},
        "sensor_type_counts": obs["sensor_type"].value_counts().to_dict(),
        "zone_counts": obs["zone_id"].value_counts().to_dict(),
        "unit_counts": obs["unit"].value_counts().to_dict(),
        "quality_flag_counts": obs["quality_flag"].value_counts(dropna=False).to_dict(),
        "channel_id_counts": obs["channel_id"].value_counts().to_dict(),
        "section_pair_counts": obs["section_pair"].value_counts().to_dict(),
    },
)

g = obs.groupby("sensor_type")["engineering_value_signed"]
put(
    "observations_value_by_type",
    {
        t: {
            "count": int(sub.count()),
            "min": round(float(sub.min()), 4),
            "max": round(float(sub.max()), 4),
            "mean": round(float(sub.mean()), 4),
            "std": round(float(sub.std()), 4),
            "null": int(sub.isna().sum()),
        }
        for t, sub in g
    },
)

put(
    "observations_depth_by_type",
    {
        t: sorted(obs[obs["sensor_type"] == t]["depth_m"].dropna().unique().tolist())
        for t in obs["sensor_type"].unique()
    },
)

put(
    "observations_temperature",
    {
        "min": round(float(obs["temperature"].min()), 2),
        "max": round(float(obs["temperature"].max()), 2),
        "mean": round(float(obs["temperature"].mean()), 2),
        "null": int(obs["temperature"].isna().sum()),
    },
)

# 每传感器通道真实观测次数与稀疏度
per_ch = (
    obs.groupby(["sensor_id", "sensor_type", "channel_id"])
    .agg(n=("timestamp", "count"), first=("timestamp", "min"), last=("timestamp", "max"))
    .reset_index()
)
put(
    "observations_per_channel",
    {
        "channel_count": len(per_ch),
        "n_min": int(per_ch["n"].min()),
        "n_max": int(per_ch["n"].max()),
        "n_mean": round(float(per_ch["n"].mean()), 1),
        "n_median": float(per_ch["n"].median()),
        "sample": per_ch.head(12).to_dict("records"),
    },
)

# ---------- 2. daily_aligned ----------
da = pd.read_csv(D / "daily_aligned.csv")
put(
    "daily_aligned_overview",
    {
        "rows": len(da),
        "cols": list(da.columns),
        "missing_per_col": {c: int(da[c].isna().sum()) for c in da.columns},
        "sensor_type_counts": da["sensor_type"].value_counts().to_dict(),
        "channel_key_count": int(da["channel_key"].nunique()),
        "mask_ratio_mean": round(float(da["mask"].mean()), 4),
        "mask_0_pct": round(float((da["mask"] == 0).mean() * 100), 2),
        "filled_1_pct": round(float((da["filled"] == 1).mean() * 100), 2),
        "delta_t_days_stats": {
            "min": float(da["delta_t_days"].min()),
            "max": float(da["delta_t_days"].max()),
            "mean": round(float(da["delta_t_days"].mean()), 2),
        },
        "unit_counts": da["unit"].value_counts().to_dict(),
    },
)

# 按通道的缺失率 = 数据质量关键指标
ch_missing = (
    da.groupby(["channel_key", "sensor_type"])
    .agg(rows=("mask", "count"), real=("mask", "sum"))
    .reset_index()
)
ch_missing["missing_pct"] = ((1 - ch_missing["real"] / ch_missing["rows"]) * 100).round(2)
put(
    "daily_aligned_missing_by_channel",
    {
        "channel_count": len(ch_missing),
        "missing_pct_min": float(ch_missing["missing_pct"].min()),
        "missing_pct_max": float(ch_missing["missing_pct"].max()),
        "missing_pct_mean": round(float(ch_missing["missing_pct"].mean()), 2),
        "worst_10": ch_missing.sort_values("missing_pct", ascending=False)
        .head(10)
        .to_dict("records"),
        "best_5": ch_missing.sort_values("missing_pct").head(5).to_dict("records"),
    },
)

# ---------- 3. sensor_metadata ----------
sm = pd.read_csv(D / "sensor_metadata.csv")
put(
    "sensor_metadata",
    {
        "rows": len(sm),
        "cols": list(sm.columns),
        "sensor_type_counts": sm["sensor_type"].value_counts().to_dict(),
        "zone_counts": sm["zone_id"].value_counts().to_dict(),
        "missing_per_col": {c: int(sm[c].isna().sum()) for c in sm.columns},
        "sample": sm.head(50).to_dict("records"),
    },
)

# ---------- 4. label_thresholds（本项目可直接借鉴的阈值结构） ----------
lt = pd.read_csv(D / "label_thresholds.csv")
put(
    "label_thresholds",
    {
        "rows": len(lt),
        "cols": list(lt.columns),
        "sensor_type_counts": lt["sensor_type"].value_counts().to_dict(),
        "describe": json.loads(lt.describe().to_json()),
        "sample": lt.head(15).to_dict("records"),
    },
)

# ---------- 5. channel_evidence（四类确定性规则的触发统计） ----------
ce = pd.read_csv(D / "channel_evidence.csv")
put(
    "channel_evidence",
    {
        "rows": len(ce),
        "cols": list(ce.columns),
        "missing_per_col": {c: int(ce[c].isna().sum()) for c in ce.columns},
        "rules_sample": ce[ce["rules"].notna()]["rules"].head(20).tolist(),
        "rule_value_counts": ce["rules"].value_counts().head(20).to_dict(),
        "sensor_type_counts": ce["sensor_type"].value_counts().to_dict(),
        "numeric_describe": json.loads(
            ce[["delta", "max_step_abs", "slope_per_day", "flatline_ratio", "score"]]
            .apply(pd.to_numeric, errors="coerce")
            .describe()
            .to_json()
        ),
    },
)

# ---------- 6. weak_event ----------
we = pd.read_csv(D / "weak_event.csv")
put(
    "weak_event",
    {
        "rows": len(we),
        "cols": list(we.columns),
        "anomaly_vote_counts": we["anomaly_vote"].value_counts(dropna=False).to_dict(),
        "state_vote_counts": we["state_vote"].value_counts(dropna=False).to_dict(),
        "split_counts": we["split"].value_counts().to_dict(),
        "window_type_counts": we["window_type"].value_counts().to_dict(),
        "rule_source_counts": we["rule_source"].value_counts(dropna=False).to_dict(),
        "missing_per_col": {c: int(we[c].isna().sum()) for c in we.columns},
    },
)

# ---------- 7. 粘土隆起（唯一"竖向位移/隆起"真实时序） ----------
heave = pd.read_csv(ROOT / "地下室粘土隆起监测/B(CSV) - Heave monitoring data 1967-89, data only.csv")
put(
    "heave_monitoring",
    {
        "rows": len(heave),
        "cols": list(heave.columns),
        "missing_per_col": {c: int(heave[c].isna().sum()) for c in heave.columns},
        "dtypes": {c: str(heave[c].dtype) for c in heave.columns},
        "head": heave.head(6).to_dict("records"),
        "tail": heave.tail(4).to_dict("records"),
    },
)

# ---------- 8. 不排水抗剪强度（编码问题文件） ----------
try:
    cu = pd.read_csv(
        ROOT / "地下室粘土隆起监测/A3(CSV) - Undrained shear strength, data only.csv",
        encoding="latin-1",
    )
    put(
        "undrained_shear_strength",
        {
            "encoding_used": "latin-1 (原文件非 UTF-8，含 0xB2 字节)",
            "rows": len(cu),
            "cols": list(cu.columns),
            "missing_per_col": {c: int(cu[c].isna().sum()) for c in cu.columns},
            "head": cu.head(8).to_dict("records"),
        },
    )
except Exception as exc:  # noqa: BLE001
    put("undrained_shear_strength", {"error": str(exc)})

# ---------- 9. 测压管剖面 ----------
piezo = pd.read_csv(ROOT / "地下室粘土隆起监测/A4(CSV) - Piezometric profile, data only.csv")
put(
    "piezometric_profile",
    {"rows": len(piezo), "cols": list(piezo.columns), "full": piezo.to_dict("records")},
)

# ---------- 10. 黏土基坑开挖案例库（与深基坑最相关） ----------
xl = pd.ExcelFile(ROOT / "黏土基坑开挖案例/EXCAV-CLAY152830 database/EXCAV_CLAY_15_2830.xlsx")
sheet = xl.parse(xl.sheet_names[0], header=None)
rows = []
for r in sheet.head(40).values.tolist():
    rows.append([("" if pd.isna(v) else str(v))[:40] for v in r[:25]])
put(
    "excav_clay_database",
    {
        "file": "黏土基坑开挖案例/EXCAV-CLAY152830 database/EXCAV_CLAY_15_2830.xlsx",
        "sheet_names": xl.sheet_names,
        "shape": [int(sheet.shape[0]), int(sheet.shape[1])],
        "non_empty_cells": int(sheet.notna().sum().sum()),
        "head_40_rows_preview": rows,
    },
)

# 尝试以第一行为表头解析
try:
    df2 = xl.parse(xl.sheet_names[0])
    put(
        "excav_clay_parsed_header",
        {
            "columns": [str(c) for c in df2.columns],
            "rows": len(df2),
            "dtypes": {str(c): str(df2[c].dtype) for c in df2.columns},
            "missing_per_col": {str(c): int(df2[c].isna().sum()) for c in df2.columns},
            "head": json.loads(df2.head(8).to_json(orient="records")),
        },
    )
except Exception as exc:  # noqa: BLE001
    put("excav_clay_parsed_header", {"error": str(exc)})

# ---------- 11. 隆起 xlsx 结构 ----------
for name, rel in [
    ("heave_xlsx", "地下室粘土隆起监测/B - Heave monitoring data 1967-89 and calculations.xlsx"),
    ("spt_xlsx", "地下室粘土隆起监测/A5 - Standard penetration test data and calculations.xlsx"),
]:
    x = pd.ExcelFile(ROOT / rel)
    info = {"sheet_names": x.sheet_names}
    for s in x.sheet_names:
        d = x.parse(s, header=None)
        info[s] = {
            "rows": int(d.shape[0]),
            "cols": int(d.shape[1]),
            "preview": [
                [("" if pd.isna(v) else str(v))[:24] for v in row[:10]]
                for row in d.head(8).values.tolist()
            ],
        }
    put(name, info)

out = OUT / "关键数据剖析.json"
out.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(f"\nwritten: {out}")
