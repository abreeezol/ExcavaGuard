"""
三阶段流程编排
==============

    阶段一 · 数据准备  ──►  阶段二 · 确定性计算  ──►  阶段三 · 规范比对识别风险
    （统一输入依据）          （四项核心计算）          （与规范比对 → 风险分级）

阶段语义（重要）
---------------
- **阶段一 数据准备**：用户上传的现有数据 与 为验证健壮性而生成的模拟数据，
  在此统一接入、归一化、做质量扫描，输出**风险识别参数**，作为阶段二的输入依据。
  两者地位不同：真实数据是判定主依据；模拟数据仅用于验证流程处理噪音与缺失的能力，
  **不替代真实数据**，全程带 `data_origin = "simulated"` 标识并单独统计。
- **阶段二 确定性计算**：累计值、本次变化量、变化速率、趋势斜率。相同输入必得相同输出。
- **阶段三 规范比对**：把阶段二结果与规范库中的判据比对，识别风险并分级。
  默认使用 `基坑智守项目相关规范` 目录内的规范（视为覆盖大多数情况的通用规范）；
  用户可自行上传规范，未上传时不作特殊处理。

三个阶段是**流程上的先后关系**，不是方案的递进关系。

日报接口
--------
`build_daily_report_input()` 输出结构化中间结果，供后续日报生成模块消费。
本层**不生成**符合日报规范的文件，仅预留接入点。

契约（冻结字段，只增不改）：
  - `确定性计算层/contracts/daily_report_input.schema.json`
  - `确定性计算层/04_日报模块接口契约.md`
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Sequence

BASE = Path(__file__).resolve().parent
S1 = BASE / "stage1_data_preparation"
S2 = BASE / "stage2_deterministic_calc"
S3 = BASE / "stage3_standard_comparison"
import sys

for p in (str(S1), str(S2), str(S3)):
    if p not in sys.path:
        sys.path.insert(0, p)

from datetime import date  # noqa: E402

from ingest import (  # noqa: E402
    NormalizedRecord,
    build_metric_aliases,
    derive_temporal_fields,
    normalize_records,
    origin_statistics,
)
from quality_scan import scan_records  # noqa: E402
from calculator import compute, compute_batch  # noqa: E402
from standards_registry import StandardsRegistry  # noqa: E402
from risk_identifier import (  # noqa: E402
    ProjectContext,
    judge_batch,
    summarize,
)


def _day_index(ts: str | None) -> float:
    """把 ISO 日期转成相对天序；无法解析时返回 NaN（该序列不参与斜率计算）。"""
    if not ts:
        return float("nan")
    s = str(ts)[:10].replace("/", "-")
    try:
        y, m, d = (int(x) for x in s.split("-"))
        return (date(y, m, d) - date(1970, 1, 1)).days * 1.0
    except Exception:  # noqa: BLE001
        return float("nan")


def build_point_series(norm: Sequence[Any]) -> tuple[dict, dict]:
    """按测点建立时间序列。

    返回 (series, idx_map)：
      series[point_id] = [(timestamp, day_index, value), ...]（按时间升序，已剔除空值）
      idx_map[(point_id, timestamp)] = 在序列中的下标
    """
    buckets: dict[str, list[tuple[str | None, float]]] = {}
    for r in norm:
        pid = getattr(r, "point_id", None) or ""
        if getattr(r, "value", None) is None:
            continue
        buckets.setdefault(pid, []).append((getattr(r, "timestamp", None), float(r.value)))

    series: dict[str, list[tuple[str | None, float, float]]] = {}
    idx_map: dict[tuple, int] = {}
    for pid, items in buckets.items():
        items.sort(key=lambda x: (str(x[0] or ""),))
        seq: list[tuple[str | None, float, float]] = []
        base = None
        for ts, v in items:
            di = _day_index(ts)
            if di != di:  # NaN
                continue
            if base is None:
                base = di
            seq.append((ts, di - base, v))
        series[pid] = seq
        for i, (ts, _d, _v) in enumerate(seq):
            idx_map[(pid, ts)] = i
    return series, idx_map


def compute_batch_with_series(
    norm: Sequence[Any],
    series: dict,
    idx_map: dict,
    expected_interval_days: float | None = None,
) -> list:
    """逐条计算，斜率取"截至本期"的历史。"""
    out = []
    for r in norm:
        pid = getattr(r, "point_id", None) or ""
        seq = series.get(pid, [])
        i = idx_map.get((pid, getattr(r, "timestamp", None)), len(seq) - 1)
        hist = [(d, v) for (_ts, d, v) in seq[: max(0, i + 1)]]
        out.append(
            compute(
                metric_key=getattr(r, "metric_key", ""),
                current=getattr(r, "value", None),
                baseline=getattr(r, "baseline_value", None),
                previous=getattr(r, "previous_value", None),
                interval_days=getattr(r, "interval_days", None),
                point_id=getattr(r, "point_id", None),
                timestamp=getattr(r, "timestamp", None),
                data_origin=getattr(r, "data_origin", "real"),
                history=hist,
                expected_interval_days=expected_interval_days,
                input_flags=getattr(r, "flags", None),
            )
        )
    return out


def build_blocked_map(quality_report: Any) -> dict[tuple, list[str]]:
    """把阶段一的高严重度质量问题整理成 {(point_id, timestamp): [问题码]}。

    这些记录不参与风险判定，一律弃权并转人工复核。
    """
    from risk_identifier import BLOCKING_ISSUE_CODES

    out: dict[tuple, list[str]] = {}
    for issue in getattr(quality_report, "issues", []):
        if issue.code not in BLOCKING_ISSUE_CODES:
            continue
        key = (issue.point_id, issue.timestamp)
        codes = out.setdefault(key, [])
        if issue.code not in codes:
            codes.append(issue.code)
    return out


def build_rate_history(calcs: Sequence[Any]) -> dict[str, list]:
    """把阶段二的速率结果整理成 {point_id: [(timestamp, rate), ...]}，供阶段三的连续 3 次判定。"""
    hist: dict[str, list] = {}
    for c in calcs:
        if c.rate is None:
            continue
        pid = getattr(c, "point_id", None) or ""
        hist.setdefault(pid, []).append((c.timestamp, c.rate))
    for v in hist.values():
        v.sort(key=lambda x: str(x[0] or ""))
    return hist


@dataclass
class PipelineResult:
    stage1: dict = field(default_factory=dict)
    stage2: dict = field(default_factory=dict)
    stage3: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "stage1_data_preparation": self.stage1,
            "stage2_deterministic_calc": self.stage2,
            "stage3_standard_comparison": self.stage3,
            "summary": self.summary,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, default=str)


def run_pipeline(
    records: Sequence[dict],
    ctx: ProjectContext | None = None,
    *,
    default_metric_key: str | None = None,
    target_unit: str = "mm",
    default_origin: str = "real",
    expected_interval_days: float | None = None,
    value_range: tuple[float, float] | None = None,
    registry: StandardsRegistry | None = None,
) -> PipelineResult:
    """按 阶段一 → 阶段二 → 阶段三 顺序执行。"""
    ctx = ctx or ProjectContext()
    # 复制一份：本次运行会填充 rate_history，**不应写回调用方传入的 ctx**。
    # 否则同一个 ctx 复用于第二批数据时会沿用上一批的速率历史，
    # 让"连续 3 期速率超限值 70%"和"位移收敛性"用错序列。
    ctx = replace(ctx, rate_history=dict(ctx.rate_history or {}))
    res = PipelineResult()
    reg = registry or StandardsRegistry()

    # ---------- 阶段一 · 数据准备 ----------
    # 监测项别名：允许用户用中文名称（规范库 display_name）或常见简称，自动映射到 metric_key
    metric_aliases = build_metric_aliases(reg.display_names())

    norm = normalize_records(
        list(records),
        default_metric_key=default_metric_key,
        target_unit=target_unit,
        default_origin=default_origin,
        metric_aliases=metric_aliases,
    )
    # 时序派生：用户只给了「测点/时间/项目/数值/单位」时，
    # 初始值、上次值、观测间隔按测点时序确定性派生（显式提供的值优先，不覆盖）。
    derive_stats = derive_temporal_fields(norm)
    qrep = scan_records(
        norm,
        expected_interval_days=expected_interval_days,
        value_range=value_range,
    )
    # 高严重度数据质量问题 → 该期不参与风险判定，转人工复核
    blocked_map = build_blocked_map(qrep)
    res.stage1 = {
        "stage": "阶段一 · 数据准备",
        "input_records": len(records),
        "normalized_records": len(norm),
        "data_origin_counts": origin_statistics(norm),   # 真实/模拟分开统计
        "quality_report": qrep.to_dict(),
        "blocked_records": len(blocked_map),             # 被数据质量阻塞的期次
        "derived_fields": derive_stats,                  # 时序派生统计
        "note": "用户上传数据与模拟数据在此统一作为风险识别参数的输入依据；模拟数据仅用于健壮性验证，不替代真实数据。",
    }

    # ---------- 阶段二 · 确定性计算 ----------
    # 每个测点按时间建立序列，斜率取"截至本期"的历史，用于阶段三的收敛性判断
    series, idx_map = build_point_series(norm)
    calcs = compute_batch_with_series(
        norm,
        series,
        idx_map,
        expected_interval_days=expected_interval_days,
    )
    res.stage2 = {
        "stage": "阶段二 · 确定性计算",
        "calc_count": len(calcs),
        "abstain_count": sum(1 for c in calcs if not c.ok),
        "results": [c.to_dict() for c in calcs],
        "note": "累计值 / 本次变化量 / 变化速率 / 趋势斜率；输入不足时弃权，不插补、不猜测。",
    }

    # ---------- 阶段三 · 规范比对识别风险 ----------
    if not ctx.rate_history:
        ctx.rate_history = build_rate_history(calcs)
    judgments = judge_batch(calcs, reg, ctx, blocked_map=blocked_map)
    res.stage3 = {
        "stage": "阶段三 · 规范比对",
        "standards_sources": reg.source_report(),
        "has_user_standards": reg.has_user_standards(),
        "standards_index_summary": reg.index_summary(),
        "metric_names": reg.display_names(),
        "judgments": [j.to_dict() for j in judgments],
        "note": "默认使用「基坑智守项目相关规范」目录内的规范作为通用判据；用户上传规范时按字段覆盖，未上传时不作特殊处理。",
    }

    res.summary = {
        "records": len(norm),
        "real_records": res.stage1["data_origin_counts"].get("real", 0),
        "simulated_records": res.stage1["data_origin_counts"].get("simulated", 0),
        "data_quality_issues": len(qrep.issues),
        "data_quality_blocked": len(blocked_map),
        "calc_results": len(calcs),
        "judgments": len(judgments),
        "effective_standard_origin": (
            "user_uploaded" if reg.has_user_standards() else "default_library"
        ),
        **summarize(judgments),
    }
    return res


# --- 健壮性验证（模拟数据的唯一用途） ------------------------------------


def run_robustness_check(
    records: Sequence[dict],
    profile_name: str = "medium",
    *,
    source_dataset: str = "unknown",
    ctx: ProjectContext | None = None,
    **kwargs: Any,
) -> dict:
    """向真实数据副本注入受控噪声，验证三阶段流程是否按预期识别/弃权而不崩溃。

    这是模拟数据的**唯一用途**：证明 Agent 具备处理噪音与缺失的能力。
    输出中的 `simulated` 计数与真实数据分开统计。
    """
    from robustness_simulator import inject_noise, profile_from_preset, robustness_report

    profile = profile_from_preset(profile_name)
    noisy, injected = inject_noise(list(records), profile, source_dataset=source_dataset)
    result = run_pipeline(noisy, ctx, **kwargs)

    detected = result.stage1["quality_report"]["by_code"]
    return {
        "purpose": "验证流程对噪音与缺失的健壮性，不代表工程质量判定能力",
        "profile": profile_name,
        "source_dataset": source_dataset,
        "injected": injected,
        "detected": detected,
        "robustness": robustness_report(detected, injected),
        "pipeline_summary": result.summary,
        "result": result.to_dict(),
    }


# --- 日报模块接入点 -------------------------------------------------------

DAILY_REPORT_SCHEMA = "excavaguard.daily_report_input/v1"

# 需要进入日报"报警清单 / 建议措施"章节的等级
ALERT_LEVELS = ("报警", "危险报警")


def _calc_index(stage2: dict) -> dict[tuple, dict]:
    """把阶段二结果按 (测点, 时间, 监测项) 建索引，避免按位置对齐的串行风险。"""
    idx: dict[tuple, dict] = {}
    for c in stage2.get("results", []):
        key = (c.get("point_id"), c.get("timestamp"), c.get("metric_key"))
        idx.setdefault(key, c)
    return idx


def build_daily_report_input(
    result: PipelineResult,
    *,
    project: dict | None = None,
    points_meta: dict | None = None,
    report_date: str | None = None,
) -> dict:
    """把三阶段结果整理成日报生成模块可直接消费的结构化输入。

    本层**不生成**日报文件，仅提供接入点。契约见
    `确定性计算层/contracts/daily_report_input.schema.json` 与
    `确定性计算层/04_日报模块接口契约.md`。

    参数
    ----
    project     工程概况（名称、监测单位、开挖工况等），调用方注入；缺省为空壳。
    points_meta 测点台账 {point_id: {...}}，用于补测点名称/类型；缺省则留空。
    report_date 报告日期；缺省时由调用方在生成日报时填入。
    """
    s1, s2, s3 = result.stage1, result.stage2, result.stage3
    names: dict = s3.get("metric_names", {}) or {}
    meta: dict = points_meta or {}
    calc_idx = _calc_index(s2)

    items: list[dict] = []
    for j in s3.get("judgments", []):
        key = (j.get("point_id"), j.get("timestamp"), j.get("metric_key"))
        c = calc_idx.get(key, {})
        inputs = c.get("inputs", {})
        outputs = c.get("outputs", {})
        pm = meta.get(j.get("point_id")) or {}
        blocked = list(j.get("abstain", []))
        items.append(
            {
                # --- 标识 ---
                "point_id": j.get("point_id"),
                "point_name": pm.get("point_name"),
                "point_type": pm.get("point_type"),
                "metric_key": j.get("metric_key"),
                "metric_name": names.get(j.get("metric_key"), j.get("metric_key")),
                "timestamp": j.get("timestamp"),
                "data_origin": j.get("data_origin"),
                # --- 本期成果（阶段二）---
                "baseline": inputs.get("baseline"),
                "previous": inputs.get("previous"),
                "current": inputs.get("current"),
                "interval_days": inputs.get("interval_days"),
                "cumulative": outputs.get("cumulative"),
                "single_change": outputs.get("single_change"),
                "rate": outputs.get("rate"),
                "slope": outputs.get("slope"),
                # --- 判定结论（阶段三）---
                "problem_category": j.get("problem_category"),
                "risk_level": j.get("risk_level"),
                "utilization": j.get("utilization"),
                "checks": j.get("checks", []),
                "effective_standard": j.get("effective_source", {}),
                "rule_id": j.get("rule_id"),
                "evidence": j.get("evidence", {}),
                # --- 可追溯性与复核线索 ---
                "abstain": blocked,
                "abstain_reasons": j.get("abstain_reasons", []),
                "flags": j.get("flags", []),
                "needs_review": bool(blocked),
            }
        )

    alerts = [it for it in items if it["risk_level"] in ALERT_LEVELS]
    review_queue = [it for it in items if it["needs_review"]]

    # 用户阈值比默认规范更宽松的告警（同一测点+监测项去重）
    override_warnings: list[dict] = []
    seen_warn: set[tuple] = set()
    for j in s3.get("judgments", []):
        details = (j.get("effective_source") or {}).get("looser_details") or []
        if not details:
            continue
        key = (j.get("point_id"), j.get("metric_key"))
        if key in seen_warn:
            continue
        seen_warn.add(key)
        override_warnings.append(
            {
                "point_id": j.get("point_id"),
                "metric_key": j.get("metric_key"),
                "metric_name": names.get(j.get("metric_key"), j.get("metric_key")),
                "effective_standard": j.get("effective_source", {}),
                "differences": details,
            }
        )

    return {
        "schema": DAILY_REPORT_SCHEMA,
        "contract": {
            "producer": "确定性计算层 · 三阶段流水线",
            "consumer": "日报生成 Agent（后续独立实现，本层不实现）",
            "stability": "字段只增不改；新增字段向后兼容；破坏性变更须升级 schema 版本号",
            "schema_file": "确定性计算层/contracts/daily_report_input.schema.json",
            "excludes": ["日报正文", "日报版式文件", "结论性建议措辞", "规范原文引用全文"],
        },
        "generated_from": {
            "stage1": "阶段一 · 数据准备",
            "stage2": "阶段二 · 确定性计算",
            "stage3": "阶段三 · 规范比对",
        },
        "project": {
            "name": None,
            "monitoring_unit": None,
            "report_date": report_date,
            "excavation_stage": None,
            "excavation_depth_m": None,
            "safety_level": None,
            "support_type": None,
            **(project or {}),
        },
        "context": {
            "real_records": result.summary.get("real_records"),
            "simulated_records": result.summary.get("simulated_records"),
            "records": result.summary.get("records"),
            "effective_standard_origin": result.summary.get("effective_standard_origin"),
            "effective_standard_stage": "阶段三 · 规范比对",
            "real_is_primary": True,
            "simulated_note": "模拟数据仅用于验证流程健壮性，不替代真实数据，统计时与真实数据分开。",
        },
        "standards_sources": s3.get("standards_sources", []),
        "data_quality": {
            "issue_count": s1.get("quality_report", {}).get("issue_count"),
            "by_code": s1.get("quality_report", {}).get("by_code", {}),
            "blocked_records": s1.get("blocked_records"),
        },
        "summary": {
            "total": result.summary.get("total"),
            "by_risk_level": result.summary.get("by_risk_level", {}),
            "by_problem_category": result.summary.get("by_problem_category", {}),
            "by_data_origin": result.summary.get("by_data_origin", {}),
            "abstain": result.summary.get("abstain", {}),
            "overall_risk_level": result.summary.get("overall_risk_level"),
        },
        "alerts": alerts,
        "review_queue": review_queue,
        "standard_override_warnings": override_warnings,
        "items": items,
        "disclaimer": (
            "阈值取自现行规范条文（见各条目 evidence 字段），实际工程使用前须经设计方确认；"
            "本载荷为结构化中间结果，不含日报结论与建议措辞。"
        ),
        "note": "结构化中间结果，供日报生成模块消费；日报文件由后续模块生成。",
    }
