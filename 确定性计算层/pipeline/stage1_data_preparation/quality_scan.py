"""
阶段一 · 数据准备 —— 噪音与缺失识别

识别但不修改：对每条记录给出问题码、严重度、说明与处置建议。
原值一律保留，是否参与计算由下游（阶段二/阶段三）按弃权规则决定。

粗差判据为何不用「原始值 ±kσ」
--------------------------------
监测序列本身带有趋势（开挖引起的持续变形），趋势尾部天然偏离均值。
对原始值做统计离群会把**真实突变**和**趋势尾部**误判为粗差，
进而把真实险情当成数据错误屏蔽掉，属于危险的漏判。

因此粗差只识别**孤立尖峰**：相邻两步大小相当、方向相反、总摆幅超阈值。
- 孤立尖峰 = 单点跳变后又立即跳回 → 数据错误；
- 台阶跳变 = 跳变后维持在新水平 → 真实变形，应进入判定而不是被屏蔽。

覆盖的噪音/缺失类型
--------------------
| 问题码 | 含义 | 默认严重度 |
|---|---|---|
| MISSING_VALUE | 空值 / 缺测 | 中 |
| MISSING_BASELINE | 缺初始值，累计值不可算 | 中 |
| MISSING_PREVIOUS | 缺上次值，本次变化量不可算 | 中 |
| OUTLIER | 孤立尖峰（粗差）或超出物理量程 | 高 |
| NON_NUMERIC_VALUE | 数值字段非数值（格式不一致） | 高 |
| UNPARSED_TIMESTAMP | 日期格式无法解析 | 高 |
| UNSUPPORTED_UNIT | 单位无法识别（格式不一致） | 高 |
| UNIT_INCONSISTENT | 同测点单位前后不一致 | 中 |
| FORMAT_INCONSISTENT | 点号/日期/单位格式不统一 | 低 |
| DUPLICATE_RECORD | 同测点同时间重复记录 | 中 |
| TIMESTAMP_OUT_OF_ORDER | 时间倒流 | 中 |
| IRREGULAR_INTERVAL | 观测间隔显著异常 | 低 |
| FLATLINE | 连续多期数值不变，疑似传感器漂移 | 高 |
| TIME_SERIES_TOO_SHORT | 序列过短无法计算速率 | 低 |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

SEVERITY_ORDER = {"高": 3, "中": 2, "低": 1}


@dataclass
class DataIssue:
    """一条数据质量问题。"""

    code: str
    severity: str
    point_id: str | None
    timestamp: str | None
    metric_key: str | None
    description: str
    suggestion: str
    data_origin: str = "real"

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "point_id": self.point_id,
            "timestamp": self.timestamp,
            "metric_key": self.metric_key,
            "description": self.description,
            "suggestion": self.suggestion,
            "data_origin": self.data_origin,
        }


@dataclass
class QualityReport:
    """数据质量扫描报告。"""

    total_records: int = 0
    real_records: int = 0
    simulated_records: int = 0
    issues: list[DataIssue] = field(default_factory=list)
    by_code: dict[str, int] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)
    affected_points: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_records": self.total_records,
            "real_records": self.real_records,
            "simulated_records": self.simulated_records,
            "issue_count": len(self.issues),
            "by_code": self.by_code,
            "by_severity": self.by_severity,
            "affected_points": self.affected_points,
            "issues": [i.to_dict() for i in self.issues],
        }


def scan_records(
    records: Iterable,
    flatline_min_run: int = 4,
    expected_interval_days: float | None = None,
    value_range: tuple[float, float] | None = None,
    spike_ratio: float = 0.5,
    spike_min_excursion: float = 5.0,
) -> QualityReport:
    """扫描归一化后的记录，返回质量问题清单。

    spike_ratio / spike_min_excursion 控制孤立尖峰（粗差）判据：
    相邻两步的较小者需 >= 较大者 × spike_ratio，且两步绝对值之和 >= spike_min_excursion。
    """
    recs = list(records)
    rep = QualityReport(total_records=len(recs))
    rep.real_records = sum(1 for r in recs if r.data_origin == "real")
    rep.simulated_records = sum(1 for r in recs if r.data_origin == "simulated")

    def add(code: str, severity: str, r, desc: str, sug: str) -> None:
        rep.issues.append(
            DataIssue(
                code=code,
                severity=severity,
                point_id=getattr(r, "point_id", None),
                timestamp=getattr(r, "timestamp", None),
                metric_key=getattr(r, "metric_key", None),
                description=desc,
                suggestion=sug,
                data_origin=getattr(r, "data_origin", "real"),
            )
        )
        rep.by_code[code] = rep.by_code.get(code, 0) + 1
        rep.by_severity[severity] = rep.by_severity.get(severity, 0) + 1
        p = getattr(r, "point_id", None)
        if p and p not in rep.affected_points:
            rep.affected_points.append(p)

    # --- 逐条检查 -------------------------------------------------------
    for r in recs:
        if r.value is None and "NON_NUMERIC_VALUE" not in r.flags:
            add("MISSING_VALUE", "中", r, "观测值为空", "标记待复核，受影响指标暂停判定")
        if r.baseline_value is None:
            add("MISSING_BASELINE", "中", r, "缺少初始值/基准值", "累计值不可计算，需补充初始值")
        if r.previous_value is None:
            add("MISSING_PREVIOUS", "中", r, "缺少上次观测值", "本次变化量与速率不可计算")
        for f in r.flags:
            if f == "NON_NUMERIC_VALUE":
                add("NON_NUMERIC_VALUE", "高", r, "数值字段不是合法数字", "核对导出格式，修正后重新导入")
            elif f == "UNPARSED_TIMESTAMP":
                add("UNPARSED_TIMESTAMP", "高", r, "日期格式无法解析", "统一为 ISO 8601 后重新导入")
            elif f == "UNSUPPORTED_UNIT":
                add("UNSUPPORTED_UNIT", "高", r, "单位无法识别", "确认单位后重新导入，不自动换算")
            elif f == "UNKNOWN_DIRECTION":
                add("FORMAT_INCONSISTENT", "低", r, "方向字段取值异常", "统一为 positive / negative")
            elif f == "MISSING_POINT_ID":
                add("FORMAT_INCONSISTENT", "低", r, "测点编号缺失", "补齐测点编号后重新导入")

        if value_range and r.value is not None:
            lo, hi = value_range
            if r.value < lo or r.value > hi:
                add("OUTLIER", "高", r, f"观测值 {r.value} 超出量程 [{lo}, {hi}]", "保留原值，标记粗差并提示现场复核")

        if expected_interval_days and r.interval_days:
            if r.interval_days > expected_interval_days * 3:
                add(
                    "IRREGULAR_INTERVAL",
                    "低",
                    r,
                    f"观测间隔 {r.interval_days} 天，显著超出预期 {expected_interval_days} 天",
                    "速率结果标记为待复核",
                )

    # --- 序列级检查 -----------------------------------------------------
    series: dict[str, list] = {}
    for r in recs:
        if r.value is not None:
            series.setdefault(r.point_id, []).append(r)

    for pid, seq in series.items():
        seq = sorted(seq, key=lambda x: (x.timestamp or ""))

        # 时间倒流（按已排序后的原始顺序判断）
        stamps = [s.timestamp for s in seq if s.timestamp]
        if stamps != sorted(stamps):
            add("TIMESTAMP_OUT_OF_ORDER", "中", seq[0], "同测点时间序列存在时间倒流", "核对观测日期先后")

        # 重复记录
        seen: dict[tuple, int] = {}
        for s in seq:
            k = (s.timestamp, s.metric_key)
            seen[k] = seen.get(k, 0) + 1
        for k, c in seen.items():
            if c > 1:
                add("DUPLICATE_RECORD", "中", seq[0], f"同一时间同一监测项存在 {c} 条记录", "核对并去重后重新导入")

        # 单位不一致
        units = {s.unit for s in seq if s.unit}
        if len(units) > 1:
            add("UNIT_INCONSISTENT", "中", seq[0], f"同测点存在多种单位：{sorted(units)}", "统一单位后重新导入")

        # 孤立尖峰（粗差）：相邻两步大小相当、方向相反、总摆幅超阈值
        for i in range(1, len(seq) - 1):
            a, b, c = seq[i - 1], seq[i], seq[i + 1]
            if a.value is None or b.value is None or c.value is None:
                continue
            d1, d2 = b.value - a.value, c.value - b.value
            if d1 == 0 or d2 == 0 or (d1 > 0) == (d2 > 0):
                continue
            m1, m2 = abs(d1), abs(d2)
            if min(m1, m2) < spike_ratio * max(m1, m2):
                continue
            if m1 + m2 < spike_min_excursion:
                continue
            add(
                "OUTLIER",
                "高",
                b,
                f"孤立尖峰：{a.value:g} → {b.value:g} → {c.value:g}，摆幅 {m1 + m2:g}",
                "保留原值，标记粗差；该期不参与判定并提示现场复核",
            )
            # 粗差会污染相邻期的"本次变化量"，其后一期同样不可用于判定
            if i + 1 < len(seq):
                add(
                    "OUTLIER",
                    "高",
                    seq[i + 1],
                    "上一期存在孤立尖峰，本期本次变化量被污染",
                    "保留原值；该期不参与判定并提示现场复核",
                )

        vals = [s.value for s in seq if s.value is not None]

        # 传感器漂移（连续多期不变）
        run, run_start = 1, None
        for i in range(1, len(seq)):
            if seq[i].value is not None and seq[i].value == seq[i - 1].value:
                if run == 1:
                    run_start = seq[i - 1]
                run += 1
            else:
                if run >= flatline_min_run and run_start is not None:
                    add("FLATLINE", "高", run_start, f"连续 {run} 期数值不变，疑似传感器漂移", "检查传感器与采集链路")
                run, run_start = 1, None
        if run >= flatline_min_run and run_start is not None:
            add("FLATLINE", "高", run_start, f"连续 {run} 期数值不变，疑似传感器漂移", "检查传感器与采集链路")

        if len(vals) < 2:
            add("TIME_SERIES_TOO_SHORT", "低", seq[0], "有效观测不足 2 期", "无法计算变化速率")

    return rep
