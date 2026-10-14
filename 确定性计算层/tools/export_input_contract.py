"""
导出用户数据文件契约（机器可读）
================================

从**代码本身**导出契约，避免文档与实现漂移：
  - 列名与别名  ← `file_reader.COLUMN_ALIASES`
  - 必填 / 可派生 / 可选列 ← `file_reader.REQUIRED_COLUMNS` 等
  - 支持的编码与分隔符 ← `file_reader.ENCODINGS` / `DELIMITERS`
  - 单位量纲表 ← `ingest.DIMENSION_TABLES` / `DIMENSIONLESS_UNITS` / `TEMPERATURE_UNITS`
  - 方向别名 ← `ingest.DIRECTION_ALIASES`
  - 监测项别名 ← `ingest.build_metric_aliases()`（取自默认规范库）

输出：`contracts/monitoring_input.contract.json`

运行：
    python -B tools/export_input_contract.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
S1 = BASE / "pipeline" / "stage1_data_preparation"
S3 = BASE / "pipeline" / "stage3_standard_comparison"
for p in (str(S1), str(S3), str(BASE / "pipeline")):
    if p not in sys.path:
        sys.path.insert(0, p)

from file_reader import (  # noqa: E402
    COLUMN_ALIASES,
    DELIMITERS,
    DERIVABLE_COLUMNS,
    ENCODINGS,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
)
from ingest import (  # noqa: E402
    DIMENSIONLESS_UNITS,
    DIMENSION_TABLES,
    DIRECTION_ALIASES,
    TEMPERATURE_UNITS,
    build_metric_aliases,
)
from standards_registry import StandardsRegistry  # noqa: E402

FIELD_DISPLAY = {
    "point_id": "测点编号",
    "timestamp": "观测时间",
    "metric": "监测项目（metric_key 或中文名称）",
    "value": "本次观测值",
    "unit": "单位",
    "direction": "方向",
    "baseline_value": "初始值/基准值（可派生）",
    "previous_value": "上次观测值（可派生）",
    "interval_days": "观测间隔·天（可派生）",
    "interval_hours": "观测间隔·小时（可派生，÷24）",
    "data_origin": "数据来源 real/simulated",
    "measurement_semantics": "量值语义 raw_observation/precomputed_cumulative",
    "source_flags": "来源与预处理限制标记",
    "source_metadata": "来源元数据",
    "note": "备注",
}


def build_contract() -> dict:
    reg = StandardsRegistry()
    names = reg.display_names()
    return {
        "schema": "excavaguard.monitoring_input/v1",
        "title": "基坑智守 · 用户监测数据文件契约",
        "description": (
            "用户上传的监测数据文件（CSV / TSV / Excel）应满足本契约。"
            "读取器支持五列长表及带明确量值语义的混合宽表；"
            "只做列映射、宽表展开与来源留痕，不修改观测数值。"
        ),
        "source_module": {
            "reader": "pipeline/stage1_data_preparation/file_reader.py",
            "normalizer": "pipeline/stage1_data_preparation/ingest.py",
            "exported_by": "tools/export_input_contract.py",
        },
        "file": {
            "formats": ["csv", "tsv", "txt", "xlsx"],
            "encodings_tried_in_order": list(ENCODINGS),
            "delimiters_auto_detected": [{"\t": "\\t"}.get(d, d) for d in DELIMITERS],
            "notes": [
                "编码按顺序尝试，取首个能完整解码且无替换字符者。",
                "分隔符由表头行中出现次数最多的候选决定，默认逗号。",
                "读取 Excel 需要 openpyxl；未安装时请另存为 CSV。",
            ],
            "layouts": {
                "long": "含 point_id / timestamp / metric / value / unit 五列的标准长表。",
                "wide": (
                    "一个时间列 + 多个“监测项目-测点号-量值语义(单位)”通道；"
                    "任一非空通道无法明确解析时整表拒绝。"
                ),
            },
        },
        "columns": {
            "required": [
                {"name": c, "display": FIELD_DISPLAY.get(c, c), "aliases": list(COLUMN_ALIASES.get(c, ()))}
                for c in REQUIRED_COLUMNS
            ],
            "derivable": [
                {"name": c, "display": FIELD_DISPLAY.get(c, c), "aliases": list(COLUMN_ALIASES.get(c, ()))}
                for c in DERIVABLE_COLUMNS
            ],
            "optional": [
                {"name": c, "display": FIELD_DISPLAY.get(c, c), "aliases": list(COLUMN_ALIASES.get(c, ()))}
                for c in OPTIONAL_COLUMNS
            ],
        },
        "measurement_semantics": {
            "raw_observation": "原始观测值；缺少基准时按该测点+监测项的首个有效观测派生。",
            "precomputed_cumulative": (
                "输入已是相对工程基准的累计量；baseline_value 固定为 0，"
                "不得以本次上传窗口首值重新归零。"
            ),
            "marks": ["PRECOMPUTED_CUMULATIVE", "SEMANTIC_BASELINE_ZERO"],
        },
        "derivation_rules": {
            "applies_to": "每个 (point_id, metric_key) 时序按时间升序独立派生",
            "baseline_value": "该测点+监测项时序的首个有效观测值；显式提供时不覆盖",
            "previous_value": "同一测点+监测项的前一个有效观测值；首期为 null（本次变化量弃权）",
            "interval_days": "本期与前一个有效观测的时间差（天）；首期为 null（速率弃权）",
            "valid_observation": "数值可解析的记录；空值与非数值不参与派生",
            "marks": ["BASELINE_DERIVED", "PREVIOUS_DERIVED", "INTERVAL_DERIVED"],
            "precedence": (
                "除 precomputed_cumulative 的语义零基准外，显式提供的值优先；"
                "累计量同时给出非零基准时标记冲突并阻塞判定"
            ),
        },
        "wide_daily_aggregation": {
            "applies_when": "混合宽表进入日报分析",
            "method": "保留截至报告日的逐通道每日末次记录历史",
            "series_key": ["point_id", "metric_key"],
            "preserved_intraday_fields": [
                "sample_count",
                "source_start",
                "source_end",
                "first_value",
                "last_value",
                "minimum",
                "maximum",
                "max_abs_step",
                "max_abs_step_at",
            ],
            "warning": "日末记录不能证明日内无异常；工作簿级插值/末值保持限制必须保留。",
        },
        "unit_conversion": {
            "by_dimension": {
                dim: {"to": canon, "factors": tbl} for dim, (tbl, canon) in DIMENSION_TABLES.items()
            },
            "preserved_as_is": sorted(DIMENSIONLESS_UNITS | TEMPERATURE_UNITS),
            "unsupported": "无法识别的单位原样保留并标记 UNSUPPORTED_UNIT（高严重度，阻塞该期判定）",
        },
        "direction_aliases": DIRECTION_ALIASES,
        "metric_aliases": build_metric_aliases(names),
        "metric_display_names": names,
        "rejection_rules": [
            "缺少任一必填列 → 拒收，并列出缺失列",
            "文件无可读数据行 → 拒收",
            "编码无法解码 → 按 latin-1 兜底读取，不丢数据",
        ],
        "disclaimer": "本契约只定义文件如何进入管线；判定结论须以阶段三输出的规范条文依据为准。",
    }


def main() -> int:
    out_dir = BASE / "contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "monitoring_input.contract.json"
    c = build_contract()
    out.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 70)
    print("用户数据文件契约已导出")
    print("=" * 70)
    print(f"  必填列    : {REQUIRED_COLUMNS}")
    print(f"  可派生列  : {DERIVABLE_COLUMNS}")
    print(f"  可选列    : {OPTIONAL_COLUMNS}")
    print(f"  编码候选  : {ENCODINGS}")
    print(f"  监测项别名: {len(c['metric_aliases'])} 条")
    print(f"  方向别名  : {len(DIRECTION_ALIASES)} 条")
    print(f"\n写入：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
