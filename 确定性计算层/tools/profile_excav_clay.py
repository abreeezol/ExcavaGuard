"""
对 EXCAV-CLAY/15/2830 黏土基坑案例库做统计画像，
输出可作为「变形量级经验参考」的分位数，写入 derived/（不改原始文件）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(r"C:\Study\bisai\Hai AI Agent\基坑智守项目相关数据")
OUT = Path(r"C:\Study\bisai\Hai AI Agent\ExcavaGuard\确定性计算层\derived")
OUT.mkdir(parents=True, exist_ok=True)

df = pd.read_excel(
    ROOT / "黏土基坑开挖案例/EXCAV-CLAY152830 database/EXCAV_CLAY_15_2830.xlsx",
    sheet_name="Parameters",
)

Q = [0.05, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]


def prof(col: str) -> dict:
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if s.empty:
        return {"n": 0}
    return {
        "n": int(s.size),
        "missing": int(df[col].isna().sum()),
        "min": round(float(s.min()), 3),
        "max": round(float(s.max()), 3),
        "mean": round(float(s.mean()), 3),
        **{f"q{int(q * 100)}": round(float(s.quantile(q)), 3) for q in Q},
    }


out = {
    "source": "EXCAV_CLAY_15_2830.xlsx / sheet=Parameters",
    "rows": int(len(df)),
    "cols": int(df.shape[1]),
    "site_count": int(pd.to_numeric(df["Site"], errors="coerce").nunique()),
    "country_counts": df["Country"].value_counts().head(15).to_dict(),
    "construction_type_counts": df["Construction type"].value_counts().to_dict(),
    "retaining_wall_counts": df["RW"].value_counts().to_dict(),
    "cmm_counts": df["CMM"].value_counts().to_dict(),
    "profiles": {
        "He_m_excavation_depth": prof("He (m)"),
        "B_m_excavation_width": prof("B (m)"),
        "dhm_mid_mm_max_lateral_wall_displacement": prof("dhm,mid (mm)"),
        "zm_m_depth_of_max_displacement": prof("zm (m)"),
        "su_sv_normalized_undrained_shear": prof("su/sv'"),
        "SPT_N": prof("N"),
        "R_relative_stiffness_ratio": prof("R"),
        "IF_influence_factor": prof("IF"),
    },
    "missing_per_col": {str(c): int(df[c].isna().sum()) for c in df.columns},
}

# 归一化变形比 δhm/He（%），可用于经验参考
d = df[["He (m)", "dhm,mid (mm)", "Country", "Construction type", "RW"]].copy()
d["He (m)"] = pd.to_numeric(d["He (m)"], errors="coerce")
d["dhm,mid (mm)"] = pd.to_numeric(d["dhm,mid (mm)"], errors="coerce")
d = d.dropna()
d["ratio_pct"] = (d["dhm,mid (mm)"] / (d["He (m)"] * 1000) * 100).round(4)
out["delta_hm_over_He_percent"] = {
    "n": int(len(d)),
    "min": round(float(d["ratio_pct"].min()), 4),
    "max": round(float(d["ratio_pct"].max()), 4),
    "mean": round(float(d["ratio_pct"].mean()), 4),
    **{f"q{int(q * 100)}": round(float(d["ratio_pct"].quantile(q)), 4) for q in Q},
}

# 按国家/工法分组的中位变形比
grp = (
    d.groupby("Country")["ratio_pct"]
    .agg(n="count", median="median", q90=lambda s: s.quantile(0.9))
    .round(4)
    .reset_index()
)
out["ratio_by_country"] = grp.to_dict("records")

p = OUT / "EXCAV_CLAY_统计画像.json"
p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2)[:6000])
print(f"\nwritten: {p}")
