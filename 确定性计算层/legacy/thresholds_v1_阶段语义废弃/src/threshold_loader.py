"""
基坑智守 · 阈值配置加载器（三阶段优先级）

设计要点
--------
1. 阶段1 generic_default   ：内置通用默认阈值（GB 50497-2019），始终存在，优先级最低。
2. 阶段2 imported_standard ：用户导入的标准 / 地方规程阈值文件，覆盖阶段1。
3. 阶段3 project_specific  ：项目经审批专项方案 / 人工审定阈值，覆盖阶段2，优先级最高。

优先级规则：后一阶段覆盖前一阶段，按 `metric_key` 粒度逐字段合并；
导入文件未显式给出的字段继承上一阶段的值，不出现"覆盖即清空"。

每次解析结果都会携带 `source`（阶段号、阶段名、来源 ID、来源标签、来源类型），
以及 `overrides`（哪些字段被后一阶段覆盖），保证结果可追溯。

仅依赖标准库，便于在任意环境运行。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# 阶段定义
# ---------------------------------------------------------------------------

STAGE_GENERIC_DEFAULT = 1
STAGE_IMPORTED_STANDARD = 2
STAGE_PROJECT_SPECIFIC = 3

STAGE_NAMES = {
    STAGE_GENERIC_DEFAULT: "generic_default",
    STAGE_IMPORTED_STANDARD: "imported_standard",
    STAGE_PROJECT_SPECIFIC: "project_specific",
}

STAGE_DISPLAY = {
    STAGE_GENERIC_DEFAULT: "第一阶段 · 通用默认阈值",
    STAGE_IMPORTED_STANDARD: "第二阶段 · 导入标准/地方规程阈值",
    STAGE_PROJECT_SPECIFIC: "第三阶段 · 项目专项方案阈值",
}

# 可合并的阈值字段（导入文件里出现的这些字段会覆盖上一阶段）
MERGEABLE_METRIC_FIELDS = ("unit", "limit_mode", "design_value_key", "note")
MERGEABLE_RULE_FIELDS = (
    "safety_level",
    "support_type",
    "pipeline_type",
    "road_type",
    "crack_state",
    "cumulative_mm",
    "cumulative_pct_H",
    "rate_mm_per_day",
    "max_ratio_of_design",
    "min_ratio_of_design",
    "cumulative_inclination",
    "rate_inclination_per_day",
    "requires_continuous_development",
    "evidence",
)


class ThresholdError(Exception):
    """阈值配置错误。"""


# ---------------------------------------------------------------------------
# 数据源
# ---------------------------------------------------------------------------


@dataclass
class ThresholdSource:
    """一个阈值来源文件。"""

    stage: int
    source_id: str
    source_label: str
    source_type: str
    path: str | None
    payload: dict

    @property
    def stage_name(self) -> str:
        return STAGE_NAMES[self.stage]

    @property
    def stage_display(self) -> str:
        return STAGE_DISPLAY[self.stage]

    def summary(self) -> dict:
        return {
            "stage": self.stage,
            "stage_name": self.stage_name,
            "stage_display": self.stage_display,
            "source_id": self.source_id,
            "source_label": self.source_label,
            "source_type": self.source_type,
            "path": self.path,
            "builtin": bool(self.payload.get("builtin")),
            "metric_count": len(self.payload.get("metrics", {})),
        }


# ---------------------------------------------------------------------------
# 解析结果
# ---------------------------------------------------------------------------


@dataclass
class ResolvedThreshold:
    """针对某个监测项 + 适用条件解析出的生效阈值。"""

    metric_key: str
    display_name: str
    unit: str | None
    limit_mode: str
    rule_id: str | None

    cumulative_limit_mm: float | None = None
    cumulative_basis: str | None = None
    rate_limit_mm_per_day: float | None = None
    max_ratio_of_design: float | None = None
    min_ratio_of_design: float | None = None
    cumulative_inclination: float | None = None
    rate_inclination_per_day: float | None = None
    requires_continuous_development: bool = False

    selection_used: str | None = None
    source: dict = field(default_factory=dict)
    evidence: dict | None = None
    flags: list[str] = field(default_factory=list)
    overrides: list[str] = field(default_factory=list)

    @property
    def stage(self) -> int:
        return self.source.get("stage", STAGE_GENERIC_DEFAULT)

    @property
    def stage_display(self) -> str:
        return self.source.get("stage_display", STAGE_DISPLAY[STAGE_GENERIC_DEFAULT])

    @property
    def source_label(self) -> str:
        return self.source.get("source_label", "")

    def to_dict(self) -> dict:
        return {
            "metric_key": self.metric_key,
            "display_name": self.display_name,
            "unit": self.unit,
            "limit_mode": self.limit_mode,
            "rule_id": self.rule_id,
            "cumulative_limit_mm": self.cumulative_limit_mm,
            "cumulative_basis": self.cumulative_basis,
            "rate_limit_mm_per_day": self.rate_limit_mm_per_day,
            "max_ratio_of_design": self.max_ratio_of_design,
            "min_ratio_of_design": self.min_ratio_of_design,
            "cumulative_inclination": self.cumulative_inclination,
            "rate_inclination_per_day": self.rate_inclination_per_day,
            "requires_continuous_development": self.requires_continuous_development,
            "selection_used": self.selection_used,
            "threshold_source": self.source,
            "threshold_source_stage": self.stage,
            "threshold_source_stage_display": self.stage_display,
            "threshold_source_label": self.source_label,
            "evidence": self.evidence,
            "flags": self.flags,
            "overridden_fields": self.overrides,
        }


# ---------------------------------------------------------------------------
# 加载器
# ---------------------------------------------------------------------------


class ThresholdConfig:
    """加载并按三阶段优先级合并阈值配置。"""

    def __init__(
        self,
        config_dir: str | Path | None = None,
        import_dirs: Iterable[str | Path] | None = None,
        range_resolution: str | None = None,
    ) -> None:
        self.config_dir = Path(config_dir) if config_dir else Path(__file__).resolve().parent.parent / "config"
        self.builtin_path = self.config_dir / "thresholds.generic_default.json"
        self.import_dirs = [Path(d) for d in import_dirs] if import_dirs else [
            self.config_dir / "project_thresholds"
        ]

        self.sources: list[ThresholdSource] = []
        self._load_builtin()
        self._load_imports()

        # 全局策略：默认取内置值，可被后续阶段覆盖
        if range_resolution:
            self.range_resolution = range_resolution
        else:
            sp = self._policy_dict("selection_policy")
            self.range_resolution = sp.get("range_resolution", "conservative")
        if self.range_resolution not in ("conservative", "lenient", "midpoint"):
            raise ThresholdError(
                f"range_resolution 只允许 conservative/lenient/midpoint，当前为 {self.range_resolution}"
            )
        self.cumulative_limit_policy = self._policy_dict("cumulative_limit_policy")
        self.rate_alarm_policy = self._policy_dict("rate_alarm_policy")
        self.post_slab_policy = self._policy_dict("post_slab_policy")
        self.danger_alarm_conditions = self._policy_list("danger_alarm_conditions")
        self.mandatory_alarm_supplement = self._policy_list("mandatory_alarm_supplement")
        self.disclaimer = self._policy("disclaimer", None)

        self._metrics = self._merge_metrics()

    # -- 加载 -------------------------------------------------------------

    def _load_builtin(self) -> None:
        if not self.builtin_path.exists():
            raise ThresholdError(f"内置通用阈值文件缺失: {self.builtin_path}")
        payload = json.loads(self.builtin_path.read_text(encoding="utf-8"))
        payload.setdefault("stage", STAGE_GENERIC_DEFAULT)
        payload.setdefault("source_id", "builtin-generic-default")
        payload.setdefault("source_label", "内置通用默认阈值")
        payload.setdefault("source_type", "national_standard")
        self.sources.append(
            ThresholdSource(
                stage=STAGE_GENERIC_DEFAULT,
                source_id=payload["source_id"],
                source_label=payload["source_label"],
                source_type=payload["source_type"],
                path=str(self.builtin_path),
                payload=payload,
            )
        )

    def _load_imports(self) -> None:
        """扫描导入目录，按文件名前缀 *.json 加载（跳过 *.example.json）。"""
        for d in self.import_dirs:
            if not d.exists():
                continue
            for p in sorted(d.glob("*.json")):
                if p.name.endswith(".example.json"):
                    continue
                payload = json.loads(p.read_text(encoding="utf-8"))
                stage = int(payload.get("stage", STAGE_IMPORTED_STANDARD))
                if stage not in (STAGE_IMPORTED_STANDARD, STAGE_PROJECT_SPECIFIC):
                    raise ThresholdError(
                        f"导入文件 stage 只允许 2 或 3，当前为 {stage}: {p}"
                    )
                if not payload.get("source_id"):
                    raise ThresholdError(f"导入文件缺少 source_id: {p}")
                payload.setdefault("source_label", payload["source_id"])
                payload.setdefault("source_type", "unknown")
                self.sources.append(
                    ThresholdSource(
                        stage=stage,
                        source_id=payload["source_id"],
                        source_label=payload["source_label"],
                        source_type=payload["source_type"],
                        path=str(p),
                        payload=payload,
                    )
                )
        self.sources.sort(key=lambda s: s.stage)

    # -- 全局策略 ---------------------------------------------------------

    def _policy(self, key: str, default: Any) -> Any:
        val = default
        for s in self.sources:
            if key in s.payload and s.payload[key] is not None:
                val = s.payload[key]
        return val

    def _policy_dict(self, key: str) -> dict:
        out: dict = {}
        for s in self.sources:
            v = s.payload.get(key)
            if isinstance(v, dict):
                out.update(v)
        return out

    def _policy_list(self, key: str) -> list:
        out: list = []
        seen: set[str] = set()
        for s in self.sources:
            v = s.payload.get(key)
            if isinstance(v, list):
                for item in v:
                    code = item.get("code") if isinstance(item, dict) else None
                    ident = code or json.dumps(item, ensure_ascii=False, sort_keys=True)
                    if ident in seen:
                        continue
                    seen.add(ident)
                    out.append(item)
        return out

    # -- 合并 -------------------------------------------------------------

    def _merge_metrics(self) -> dict:
        """按 metric_key 合并所有来源，记录每个字段的最终生效阶段。"""
        merged: dict[str, dict] = {}
        for s in self.sources:
            for key, m in (s.payload.get("metrics") or {}).items():
                node = merged.setdefault(key, {"metric": {}, "rules": {}, "field_stage": {}, "rule_field_stage": {}})
                for f in MERGEABLE_METRIC_FIELDS:
                    if f in m:
                        node["metric"][f] = m[f]
                        node["field_stage"][f] = s.stage
                for r in m.get("rules", []) or []:
                    rid = r.get("rule_id") or _synthetic_rule_id(key, r)
                    rnode = node["rules"].setdefault(rid, {"rule": {}, "field_stage": {}})
                    for f in MERGEABLE_RULE_FIELDS:
                        if f in r:
                            rnode["rule"][f] = r[f]
                            rnode["field_stage"][f] = s.stage
        return merged

    # -- 查询 -------------------------------------------------------------

    def stage_report(self) -> list[dict]:
        return [s.summary() for s in self.sources]

    def metric_keys(self) -> list[str]:
        return sorted(self._metrics.keys())

    def resolve(
        self,
        metric_key: str,
        safety_level: str,
        support_type: str,
        excavation_depth_m: float | None = None,
        pipeline_type: str | None = None,
        road_type: str | None = None,
        crack_state: str | None = None,
    ) -> ResolvedThreshold:
        """解析某监测项在当前适用条件下的生效阈值。"""
        node = self._metrics.get(metric_key)
        if node is None:
            raise ThresholdError(f"未知监测项 metric_key: {metric_key}")

        m = node["metric"]
        candidates = [
            (rid, rnode)
            for rid, rnode in node["rules"].items()
            if _match(rnode["rule"].get("safety_level"), safety_level)
            and _match(rnode["rule"].get("support_type"), support_type)
            and (pipeline_type is None or _match(rnode["rule"].get("pipeline_type"), pipeline_type))
            and (road_type is None or _match(rnode["rule"].get("road_type"), road_type))
            and (crack_state is None or _match(rnode["rule"].get("crack_state"), crack_state))
        ]

        if not candidates:
            return ResolvedThreshold(
                metric_key=metric_key,
                display_name=m.get("display_name", metric_key),
                unit=m.get("unit"),
                limit_mode=m.get("limit_mode", "none"),
                rule_id=None,
                selection_used=self.range_resolution,
                source=self.sources[0].summary(),
                flags=["NO_APPLICABLE_RULE"],
            )

        # 多个命中时取"最终阶段最高、其次规则最具体"的一条
        def specificity(item: tuple[str, dict]) -> tuple[int, int]:
            _rid, rnode = item
            stage = max(rnode["field_stage"].values()) if rnode["field_stage"] else STAGE_GENERIC_DEFAULT
            spec = sum(
                1
                for k in ("support_type", "pipeline_type", "road_type", "crack_state")
                if rnode["rule"].get(k) not in (None, "any", [])
            )
            return (stage, spec)

        rid, rnode = max(candidates, key=specificity)
        rule = rnode["rule"]
        stages = rnode["field_stage"]
        effective_stage = max(stages.values()) if stages else STAGE_GENERIC_DEFAULT
        src = self._source_of_stage(effective_stage)

        overrides = sorted({f for f, st in stages.items() if st > STAGE_GENERIC_DEFAULT})
        flags: list[str] = []

        cum_limit, cum_basis = self._resolve_cumulative(rule, excavation_depth_m, flags)
        rate = _pick(rule.get("rate_mm_per_day"), self.range_resolution)
        max_ratio = _pick(rule.get("max_ratio_of_design"), self.range_resolution)
        min_ratio = _pick(rule.get("min_ratio_of_design"), self.range_resolution)
        if max_ratio is not None and max_ratio > 1.0:
            flags.append("MAX_RATIO_GT_1_NOT_CLIPPED")

        return ResolvedThreshold(
            metric_key=metric_key,
            display_name=m.get("display_name", metric_key),
            unit=m.get("unit"),
            limit_mode=m.get("limit_mode", "none"),
            rule_id=rid,
            cumulative_limit_mm=cum_limit,
            cumulative_basis=cum_basis,
            rate_limit_mm_per_day=rate,
            max_ratio_of_design=max_ratio,
            min_ratio_of_design=min_ratio,
            cumulative_inclination=rule.get("cumulative_inclination"),
            rate_inclination_per_day=rule.get("rate_inclination_per_day"),
            requires_continuous_development=bool(rule.get("requires_continuous_development")),
            selection_used=self.range_resolution,
            source=src.summary(),
            evidence=rule.get("evidence"),
            flags=flags,
            overrides=overrides,
        )

    def _resolve_cumulative(
        self, rule: dict, H_m: float | None, flags: list[str]
    ) -> tuple[float | None, str | None]:
        """累计值取「绝对量」与「相对 H 的限值」两者的较小值。"""
        abs_mm = _pick(rule.get("cumulative_mm"), self.range_resolution)
        pct = _pick(rule.get("cumulative_pct_H"), self.range_resolution)
        if abs_mm is None and pct is None:
            return None, None
        if pct is None:
            return abs_mm, "absolute"
        if H_m is None:
            flags.append("PCT_H_NOT_EVALUATED")
            return abs_mm, "absolute(H_unknown)"
        rel_mm = pct / 100.0 * H_m * 1000.0
        if abs_mm is None:
            return rel_mm, "pct_H"
        return min(abs_mm, rel_mm), "min(absolute, pct_H)"

    def _source_of_stage(self, stage: int) -> ThresholdSource:
        for s in self.sources:
            if s.stage == stage:
                return s
        return self.sources[0]

    # -- 导入 -------------------------------------------------------------

    def validate_import(self, payload: dict) -> list[str]:
        """校验用户导入的阈值文件，返回问题列表（空列表表示通过）。"""
        problems: list[str] = []
        if int(payload.get("stage", 0)) not in (STAGE_IMPORTED_STANDARD, STAGE_PROJECT_SPECIFIC):
            problems.append("stage 必须为 2（导入标准/地方规程）或 3（项目专项方案）")
        if not payload.get("source_id"):
            problems.append("缺少 source_id")
        if not payload.get("source_label"):
            problems.append("缺少 source_label（建议填写规范/方案全称）")
        if not payload.get("metrics"):
            problems.append("缺少 metrics")
        for key, m in (payload.get("metrics") or {}).items():
            for r in m.get("rules", []) or []:
                if not r.get("rule_id"):
                    problems.append(f"{key}: 存在缺少 rule_id 的规则")
                if not r.get("safety_level"):
                    problems.append(f"{key}: 存在缺少 safety_level 的规则")
                if r.get("safety_level") and not set(_as_list(r["safety_level"])).issubset({"一级", "二级", "三级"}):
                    problems.append(f"{key}: safety_level 只允许 一级/二级/三级")
                for f in ("cumulative_mm", "cumulative_pct_H", "rate_mm_per_day",
                          "max_ratio_of_design", "min_ratio_of_design"):
                    v = r.get(f)
                    if v is not None and not isinstance(v, (int, float)) and "min" not in v:
                        problems.append(f"{key}/{r.get('rule_id')}: {f} 必须是数值或 {{min,max}}")
                if r.get("evidence") and not r["evidence"].get("standard"):
                    problems.append(f"{key}/{r.get('rule_id')}: evidence 缺少 standard")
        return problems


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _as_list(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, str):
        return [] if v == "any" else [v]
    if isinstance(v, (list, tuple, set)):
        return list(v)
    return [v]


def _match(rule_value: Any, query: str | None) -> bool:
    """规则适用性匹配。None / 'any' / [] 视为通配。"""
    if rule_value is None or rule_value == "any" or rule_value == []:
        return True
    if query is None:
        return False
    return query in _as_list(rule_value)


def _pick(value: Any, policy: str) -> float | None:
    """把 {min,max} 区间按策略解析为确定值。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        lo, hi = value.get("min"), value.get("max")
        if lo is None and hi is None:
            return None
        if lo is None:
            lo = hi
        if hi is None:
            hi = lo
        if policy == "lenient":
            return float(hi)
        if policy == "midpoint":
            return float((lo + hi) / 2)
        return float(lo)  # conservative（默认，取严）
    raise ThresholdError(f"无法解析的阈值字段: {value!r}")


def _synthetic_rule_id(metric_key: str, rule: dict) -> str:
    parts = [metric_key]
    for k in ("safety_level", "support_type", "pipeline_type", "road_type", "crack_state"):
        v = rule.get(k)
        if v:
            parts.append("-".join(_as_list(v)))
    return "|".join(parts)


def load_default(config_dir: str | Path | None = None) -> ThresholdConfig:
    return ThresholdConfig(config_dir=config_dir)
