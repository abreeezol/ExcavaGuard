"""
只读扫描脚本：扫描「基坑智守项目相关数据」目录，输出每个数据文件的
文件清单、字段结构、数据量、时间范围、缺失与异常值统计。

约束：只读原始文件，绝不修改/覆盖/删除；所有结果写入 derived/ 目录。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(r"C:\Study\bisai\Hai AI Agent\基坑智守项目相关数据")
OUT_DIR = Path(r"C:\Study\bisai\Hai AI Agent\ExcavaGuard\确定性计算层\derived")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SENSOR_DIR = ROOT / "多传感器隧道监测数据" / "sensors_public_dataset"


def file_entry(rel: str) -> dict:
    p = ROOT / rel
    return {
        "file": rel,
        "format": p.suffix.lower().lstrip("."),
        "size_bytes": p.stat().st_size if p.exists() else None,
        "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        if p.exists()
        else None,
    }


def profile_csv(rel: str, time_cols: list[str] | None = None) -> dict:
    p = ROOT / rel
    info = file_entry(rel)
    try:
        df = pd.read_csv(p, low_memory=False)
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
        return info

    info["row_count"] = int(len(df))
    info["col_count"] = int(df.shape[1])
    info["columns"] = [
        {
            "name": c,
            "dtype": str(df[c].dtype),
            "non_null": int(df[c].notna().sum()),
            "null": int(df[c].isna().sum()),
            "null_pct": round(float(df[c].isna().mean() * 100), 2),
            "nunique": int(df[c].nunique(dropna=True)),
            "sample": [str(v) for v in df[c].dropna().unique()[:5]],
        }
        for c in df.columns
    ]

    if time_cols:
        ranges = {}
        for tc in time_cols:
            if tc in df.columns:
                try:
                    s = pd.to_datetime(df[tc], errors="coerce")
                    ranges[tc] = {
                        "min": str(s.min()),
                        "max": str(s.max()),
                        "span_days": round(float((s.max() - s.min()).total_seconds() / 86400), 1)
                        if s.notna().any()
                        else None,
                        "invalid_count": int(s.isna().sum() - df[tc].isna().sum()),
                    }
                except Exception as exc:  # noqa: BLE001
                    ranges[tc] = {"error": str(exc)}
        info["time_range"] = ranges

    num = df.select_dtypes(include="number")
    if not num.empty:
        info["numeric_summary"] = {
            c: {
                "min": _f(num[c].min()),
                "max": _f(num[c].max()),
                "mean": _f(num[c].mean()),
                "std": _f(num[c].std()),
                "zeros": int((num[c] == 0).sum()),
                "negatives": int((num[c] < 0).sum()),
            }
            for c in num.columns[:25]
        }
    return info


def _f(v):
    try:
        if pd.isna(v):
            return None
        return round(float(v), 6)
    except Exception:  # noqa: BLE001
        return None


def profile_xlsx(rel: str, max_sheets: int = 30) -> dict:
    p = ROOT / rel
    info = file_entry(rel)
    try:
        xl = pd.ExcelFile(p)
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
        return info
    info["sheet_names"] = xl.sheet_names
    sheets = []
    for name in xl.sheet_names[:max_sheets]:
        try:
            df = xl.parse(name, header=None)
            sheets.append(
                {
                    "sheet": name,
                    "rows": int(df.shape[0]),
                    "cols": int(df.shape[1]),
                    "non_empty_cells": int(df.notna().sum().sum()),
                    "preview": [
                        [("" if pd.isna(v) else str(v))[:28] for v in row[:12]]
                        for row in df.head(10).values.tolist()
                    ],
                }
            )
        except Exception as exc:  # noqa: BLE001
            sheets.append({"sheet": name, "error": str(exc)})
    info["sheets"] = sheets
    info["sheet_count"] = len(xl.sheet_names)
    return info


def main() -> None:
    report: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(ROOT),
        "note": "只读扫描，未修改任何原始文件",
        "files": [],
    }

    # 全量文件清单
    all_files = []
    for dirpath, _dirnames, filenames in os.walk(ROOT):
        for fn in filenames:
            full = Path(dirpath) / fn
            all_files.append(
                {
                    "path": str(full.relative_to(ROOT)).replace("\\", "/"),
                    "format": full.suffix.lower().lstrip("."),
                    "size_bytes": full.stat().st_size,
                    "modified": datetime.fromtimestamp(full.stat().st_mtime).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                }
            )
    all_files.sort(key=lambda x: x["path"])
    report["file_inventory"] = all_files
    report["file_inventory_stats"] = {
        "total_files": len(all_files),
        "total_bytes": sum(f["size_bytes"] for f in all_files),
        "by_format": {},
    }
    for f in all_files:
        report["file_inventory_stats"]["by_format"].setdefault(f["format"], {"count": 0, "bytes": 0})
        report["file_inventory_stats"]["by_format"][f["format"]]["count"] += 1
        report["file_inventory_stats"]["by_format"][f["format"]]["bytes"] += f["size_bytes"]

    # 逐文件剖析
    csv_specs = [
        ("地下室粘土隆起监测/B(CSV) - Heave monitoring data 1967-89, data only.csv", None),
        ("地下室粘土隆起监测/A3(CSV) - Undrained shear strength, data only.csv", None),
        ("地下室粘土隆起监测/A4(CSV) - Piezometric profile, data only.csv", None),
        (
            "多传感器隧道监测数据/sensors_public_dataset/data/observations.csv",
            ["timestamp"],
        ),
        (
            "多传感器隧道监测数据/sensors_public_dataset/data/daily_aligned.csv",
            ["date", "last_observation_timestamp"],
        ),
        ("多传感器隧道监测数据/sensors_public_dataset/data/sensor_metadata.csv", None),
        ("多传感器隧道监测数据/sensors_public_dataset/data/label_thresholds.csv", None),
        ("多传感器隧道监测数据/sensors_public_dataset/data/window_index.csv", ["window_start", "window_end"]),
        ("多传感器隧道监测数据/sensors_public_dataset/data/weak_event.csv", ["window_start", "window_end"]),
        ("多传感器隧道监测数据/sensors_public_dataset/data/channel_evidence.csv", None),
        ("多传感器隧道监测数据/sensors_public_dataset/data/monthly_evidence.csv", None),
        ("多传感器隧道监测数据/sensors_public_dataset/data/research_cohort.csv", None),
        ("多传感器隧道监测数据/sensors_public_dataset/DATA_DICTIONARY.csv", None),
        ("多传感器隧道监测数据/sensors_public_dataset/FILE_MANIFEST.csv", None),
    ]
    for rel, tc in csv_specs:
        report["files"].append(profile_csv(rel, tc))

    xlsx_specs = [
        "地下室粘土隆起监测/A3 - Undrained shear strength data and calculations.xlsx",
        "地下室粘土隆起监测/A4 - Piezometric profile with interpreted trendline.xlsx",
        "地下室粘土隆起监测/A5 - Standard penetration test data and calculations.xlsx",
        "地下室粘土隆起监测/B - Heave monitoring data 1967-89 and calculations.xlsx",
        "黏土基坑开挖案例/EXCAV-CLAY152830 database/EXCAV_CLAY_15_2830.xlsx",
    ]
    for rel in xlsx_specs:
        report["files"].append(profile_xlsx(rel))

    out = OUT_DIR / "数据扫描_raw.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written: {out}")

    # 控制台摘要
    print("\n=== 文件清单 ===")
    print(json.dumps(report["file_inventory_stats"], ensure_ascii=False, indent=2))
    for f in report["files"]:
        tag = f.get("row_count")
        sheet_tag = f.get("sheet_count")
        print(
            f"\n--- {f['file']}\n    format={f['format']} rows={tag} cols={f.get('col_count')} "
            f"sheets={sheet_tag} err={f.get('error')}"
        )
        if f.get("time_range"):
            print(f"    time_range={json.dumps(f['time_range'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
