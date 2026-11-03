"""阶段一 · 差值型派生（断面收敛等）
====================================

为什么需要
----------
基坑的判据几乎都能落在「单点单测项」上：墙顶位移、水位、轴力都是单通道时序。
隧道不同：**净空收敛**（周边收敛）本质是同一断面两个测线的**两点读数之差**，
不是某一个传感器的原始读数。若只按单通道处理，收敛值要么无法得到，
要么被迫由上游"先在本系统外算好再上传"，失去可追溯性。

本模块只做一件事：把显式给定的点对，按时间对齐后确定性相减，产出新的
`NormalizedRecord` 序列，交给后续相同的派生/计算/判定流程。

安全边界
--------
- **配对必须显式给出**：不接受"按点号前缀自动配对"这类猜测。
  同一断面两点命名规则因项目而异，猜错会把收敛值算成两倍或零。
- **只删不补**：仅在两点的同一时间戳都有有效数值时产出记录；不做插值、不做末值保持。
- **单位必须同量纲**：归一化后两个测点的单位若属不同量纲（如 mm 与 kN），拒绝配对并告警，
  不产出记录，也不做单位猜测。
- 派生记录带 `PAIR_DERIVED` 标记与 `source_metadata.pair`，日报/审计可追溯到
  具体是哪两个测点的差值，不必反推。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

PAIR_FLAG = "PAIR_DERIVED"


@dataclass
class PairSpec:
    """一对收敛测线/测点。"""

    point_a: str
    point_b: str
    section_id: str | None = None
    metric_key: str | None = None

    def resolved_section(self, separator: str = "~") -> str:
        return self.section_id or f"{self.point_a}{separator}{self.point_b}"


@dataclass
class DeriveReport:
    pairs: int = 0
    produced: int = 0
    skipped_no_overlap: int = 0
    skipped_unit_mismatch: int = 0
    skipped_missing_point: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pairs": self.pairs,
            "produced": self.produced,
            "skipped_no_overlap": self.skipped_no_overlap,
            "skipped_unit_mismatch": self.skipped_unit_mismatch,
            "skipped_missing_point": self.skipped_missing_point,
            "warnings": self.warnings,
            "method": "difference_abs_source",   # 差值取原始带符号差，判定侧按绝对量比对
            "note": "仅在两点同一时间戳均有有效数值时产出；不插值、不末值保持。",
        }


def _norm_point(value: Any) -> str:
    return str(value or "").strip().upper()


def _pair_specs(pairs: Sequence[Any]) -> list[PairSpec]:
    out: list[PairSpec] = []
    for item in pairs:
        if isinstance(item, PairSpec):
            out.append(item)
            continue
        if isinstance(item, dict):
            a, b = item.get("point_a"), item.get("point_b")
            if a and b:
                out.append(
                    PairSpec(
                        point_a=str(a),
                        point_b=str(b),
                        section_id=item.get("section_id"),
                        metric_key=item.get("metric_key"),
                    )
                )
            continue
        if isinstance(item, (list, tuple)) and len(item) >= 2 and item[0] and item[1]:
            out.append(PairSpec(point_a=str(item[0]), point_b=str(item[1])))
    return out


def derive_pair_records(
    records: Sequence[Any],
    pairs: Sequence[Any],
    *,
    metric_key: str,
    section_separator: str = "~",
) -> tuple[list[Any], DeriveReport]:
    """把点对读数相减，产出 ``metric_key`` 的派生序列。

    参数
    ----
    records   : 阶段一归一化后的记录（`ingest.NormalizedRecord`），单位已按量纲归一
    pairs     : 点对；元素可以是 `PairSpec`、``{"point_a","point_b","section_id"}`` 或二元组
    metric_key: 派生结果的监测项 key（如 `clearance_convergence`）

    返回 ``(派生记录列表, 派生报告)``。派生记录未做时序派生，
    调用方应把它们与原始归一化记录一起交给 `derive_temporal_fields()`。
    """
    from ingest import NormalizedRecord  # 延迟导入，避免与阶段一模块循环依赖

    specs = _pair_specs(pairs)
    report = DeriveReport(pairs=len(specs))
    if not specs:
        report.warnings.append("未提供任何点对，差值型派生未执行。")
        return [], report

    # (point_id, timestamp) -> record（同一测项、同一时间取首条，重复由质量扫描另行报出）
    index: dict[tuple[str, str], Any] = {}
    units: dict[str, str | None] = {}
    for rec in records:
        pid = _norm_point(getattr(rec, "point_id", None))
        ts = getattr(rec, "timestamp", None)
        if not pid or not ts or getattr(rec, "value", None) is None:
            continue
        index.setdefault((pid, str(ts)), rec)
        units.setdefault(pid, getattr(rec, "unit", None))

    derived: list[Any] = []
    for spec in specs:
        a, b = _norm_point(spec.point_a), _norm_point(spec.point_b)
        missing = [p for p in (a, b) if p not in units]
        if missing:
            report.skipped_missing_point.extend(missing)
            report.warnings.append(f"点对 {a}/{b} 中的 {','.join(missing)} 没有可用的归一化记录，未产出。")
            continue
        if units.get(a) != units.get(b):
            report.skipped_unit_mismatch += 1
            report.warnings.append(
                f"点对 {a}({units.get(a)}) 与 {b}({units.get(b)}) 单位不一致，未产出（不做单位猜测）。"
            )
            continue

        section = spec.resolved_section(section_separator)
        hit = 0
        for (pid, ts), rec_a in index.items():
            if pid != a:
                continue
            rec_b = index.get((b, ts))
            if rec_b is None:
                continue
            diff = float(rec_a.value) - float(rec_b.value)
            hit += 1
            derived.append(
                NormalizedRecord(
                    point_id=section,
                    timestamp=getattr(rec_a, "timestamp", None),
                    metric_key=metric_key,
                    value=diff,
                    unit=getattr(rec_a, "unit", None),
                    direction="positive",
                    baseline_value=None,
                    previous_value=None,
                    interval_days=None,
                    data_origin=getattr(rec_a, "data_origin", "real"),
                    measurement_semantics="raw_observation",
                    source_flags=[PAIR_FLAG],
                    source_metadata={
                        "pair": {
                            "point_a": a,
                            "point_b": b,
                            "section_id": section,
                            "metric_key": metric_key,
                            "formula": "value = value(A) - value(B)",
                        }
                    },
                )
            )
        report.produced += hit
        if hit == 0:
            report.skipped_no_overlap += 1
            report.warnings.append(f"点对 {a}/{b} 没有同一时间戳的双点观测，未产出（不做插值）。")

    return derived, report
