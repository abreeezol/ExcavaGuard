r"""
阶段三 · 规范比对 —— 规范库注册与加载

规范来源
--------
1. **默认规范库**（始终加载）
   目录：`C:\Study\bisai\Hai AI Agent\基坑智守项目相关规范`
   该目录内的规范被视为**覆盖大多数情况的通用规范**，是本阶段的默认判据来源。
   索引文件：`standards/default/规范库索引.json`
   阈值文件：`standards/default/thresholds_gb50497_2019.json`（条文级阈值，人工摘录并标注出处）

2. **用户上传规范**（可选）
   目录：`standards/user_uploaded/`
   用户可自行放入其他规范/地方规程/项目专项方案的阈值 JSON。
   **用户未上传时不作特殊处理**——不报错、不告警、不提示缺失，仅使用默认规范库。

优先级
------
同一监测项同一规则下，用户上传规范的字段覆盖默认规范库；
未显式给出的字段继承默认规范库，不会出现"覆盖即清空"。
每次比对结果都会标注实际生效的规范来源（source_id / source_label / origin）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parents[2]
DEFAULT_DIR = BASE / "standards" / "default"
USER_DIR = BASE / "standards" / "user_uploaded"

SPEC_ROOT = Path(r"C:\Study\bisai\Hai AI Agent\基坑智守项目相关规范")

ORIGIN_DEFAULT = "default_library"
ORIGIN_USER = "user_uploaded"

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
MERGEABLE_METRIC_FIELDS = ("unit", "limit_mode", "design_value_key", "note", "display_name")


class StandardsError(Exception):
    pass


@dataclass
class StandardSource:
    origin: str
    source_id: str
    source_label: str
    source_type: str
    path: str | None
    payload: dict

    @property
    def origin_display(self) -> str:
        return {
            ORIGIN_DEFAULT: "默认规范库（基坑智守项目相关规范）",
            ORIGIN_USER: "用户上传规范",
        }.get(self.origin, self.origin)

    def summary(self) -> dict:
        return {
            "origin": self.origin,
            "origin_display": self.origin_display,
            "source_id": self.source_id,
            "source_label": self.source_label,
            "source_type": self.source_type,
            "path": self.path,
            "metric_count": len(self.payload.get("metrics", {})),
        }


class StandardsRegistry:
    """加载默认规范库 + 用户上传规范，并按字段合并。"""

    def __init__(
        self,
        default_dir: str | Path | None = None,
        user_dir: str | Path | None = None,
    ) -> None:
        self.default_dir = Path(default_dir) if default_dir else DEFAULT_DIR
        self.user_dir = Path(user_dir) if user_dir else USER_DIR
        self.sources: list[StandardSource] = []
        self.index: dict | None = None

        self._load_index()
        self._load_default()
        self._load_user()

        self.range_resolution = self._policy("selection_policy", {}).get("range_resolution", "conservative")
        self.cumulative_policy = self._policy("cumulative_limit_policy", {})
        self.rate_policy = self._policy("rate_alarm_policy", {})
        self.post_slab_policy = self._policy("post_slab_policy", {})
        self.danger_conditions = self._merge_list("danger_alarm_conditions")
        self.mandatory_alarms = self._merge_list("mandatory_alarm_supplement")

        self._metrics = self._merge_metrics()

    # -- 加载 ------------------------------------------------------------

    def _load_index(self) -> None:
        p = self.default_dir / "规范库索引.json"
        if p.exists():
            self.index = json.loads(p.read_text(encoding="utf-8"))

    def _load_dir(self, d: Path, origin: str) -> None:
        if not d.exists():
            return
        for p in sorted(d.glob("*.json")):
            if p.name.endswith(".example.json"):
                continue
            if p.name == "规范库索引.json":
                continue
            payload = json.loads(p.read_text(encoding="utf-8"))
            if "metrics" not in payload:
                continue  # 非阈值文件，跳过
            payload.setdefault("source_id", p.stem)
            payload.setdefault("source_label", p.stem)
            payload.setdefault("source_type", "unknown")
            self.sources.append(
                StandardSource(
                    origin=origin,
                    source_id=payload["source_id"],
                    source_label=payload["source_label"],
                    source_type=payload["source_type"],
                    path=str(p),
                    payload=payload,
                )
            )

    def _load_default(self) -> None:
        self._load_dir(self.default_dir, ORIGIN_DEFAULT)
        if not self.sources:
            raise StandardsError(f"默认规范库的阈值文件缺失：{self.default_dir}")

    def _load_user(self) -> None:
        """用户未上传规范时静默跳过，不作任何特殊处理。"""
        self._load_dir(self.user_dir, ORIGIN_USER)

    # -- 策略 ------------------------------------------------------------

    def _policy(self, key: str, default: Any) -> Any:
        out = dict(default) if isinstance(default, dict) else default
        for s in self.sources:
            v = s.payload.get(key)
            if isinstance(v, dict):
                out = {**(out if isinstance(out, dict) else {}), **v}
            elif v is not None:
                out = v
        return out

    def _merge_list(self, key: str) -> list:
        out: list = []
        seen: set[str] = set()
        for s in self.sources:
            for item in s.payload.get(key, []) or []:
                ident = item.get("code") if isinstance(item, dict) else json.dumps(item, ensure_ascii=False)
                if ident in seen:
                    out = [x for x in out if (x.get("code") if isinstance(x, dict) else None) != ident]
                seen.add(ident)
                out.append(item)
        return out

    # -- 合并 ------------------------------------------------------------

    def _merge_metrics(self) -> dict:
        merged: dict[str, dict] = {}
        for s in self.sources:
            for key, m in (s.payload.get("metrics") or {}).items():
                node = merged.setdefault(key, {"metric": {}, "rules": {}, "origin": {}, "overridden": set()})
                for f in MERGEABLE_METRIC_FIELDS:
                    if f in m:
                        node["metric"][f] = m[f]
                for r in m.get("rules", []) or []:
                    rid = r.get("rule_id") or f"{key}|{r.get('safety_level')}"
                    rnode = node["rules"].setdefault(rid, {"rule": {}, "origin": {}})
                    for f in MERGEABLE_RULE_FIELDS:
                        if f in r:
                            rnode["rule"][f] = r[f]
                            rnode["origin"][f] = s
                            if s.origin == ORIGIN_USER:
                                node["overridden"].add(f"{rid}.{f}")
        return merged

    # -- 查询 ------------------------------------------------------------

    def source_report(self) -> list[dict]:
        return [s.summary() for s in self.sources]

    def has_user_standards(self) -> bool:
        return any(s.origin == ORIGIN_USER for s in self.sources)

    def index_summary(self) -> dict | None:
        if not self.index:
            return None
        return {
            "source_root": self.index.get("source_root"),
            "total": self.index.get("stats", {}).get("total"),
            "by_relevance": self.index.get("stats", {}).get("by_relevance"),
            "primary_codes": [
                s["code"] for s in self.index.get("standards", []) if s["relevance"] == "primary"
            ],
        }

    def metric_keys(self) -> list[str]:
        return sorted(self._metrics.keys())

    def display_names(self) -> dict[str, str]:
        """监测项 key → 中文名称，供日报表格直接引用。

        名称取自定义该监测项的规范条目；缺失时回退为 key 本身。
        """
        out: dict[str, str] = {}
        for key, node in self._metrics.items():
            metric = node.get("metric") or {}
            name = metric.get("display_name")
            out[key] = name if isinstance(name, str) and name else key
        return out

    def get_metric(self, metric_key: str) -> dict | None:
        node = self._metrics.get(metric_key)
        if not node:
            return None
        return {
            "metric_key": metric_key,
            "metric": node["metric"],
            "rules": {rid: r["rule"] for rid, r in node["rules"].items()},
            "overridden_fields": sorted(node["overridden"]),
        }

    def get_rule_origins(self, metric_key: str, rule_id: str) -> dict[str, str]:
        node = self._metrics.get(metric_key, {})
        rnode = node.get("rules", {}).get(rule_id)
        if not rnode:
            return {}
        return {f: s.origin for f, s in rnode["origin"].items()}

    def validate_upload(self, payload: dict) -> list[str]:
        """校验用户拟上传的规范阈值文件。"""
        problems: list[str] = []
        if not payload.get("source_id"):
            problems.append("缺少 source_id")
        if not payload.get("source_label"):
            problems.append("缺少 source_label（建议填写规范/方案全称，将原样输出到比对结果）")
        if not payload.get("metrics"):
            problems.append("缺少 metrics")
        for key, m in (payload.get("metrics") or {}).items():
            for r in m.get("rules", []) or []:
                if not r.get("rule_id"):
                    problems.append(f"{key}: 存在缺少 rule_id 的规则")
                sl = r.get("safety_level")
                if sl and not set(sl if isinstance(sl, list) else [sl]).issubset({"一级", "二级", "三级"}):
                    problems.append(f"{key}: safety_level 只允许 一级/二级/三级")
                for f in ("cumulative_mm", "cumulative_pct_H", "rate_mm_per_day",
                          "max_ratio_of_design", "min_ratio_of_design"):
                    v = r.get(f)
                    if v is not None and not isinstance(v, (int, float)) and not isinstance(v, dict):
                        problems.append(f"{key}/{r.get('rule_id')}: {f} 必须是数值或 {{min,max}}")
                if r.get("evidence") and not r["evidence"].get("standard"):
                    problems.append(f"{key}/{r.get('rule_id')}: evidence 缺少 standard")
        return problems


# --- 用户上传规范接口 -----------------------------------------------------

UPLOAD_TEMPLATE: dict = {
    "schema_version": "1.0",
    "source_id": "",
    "source_label": "",          # 例如："XX 市基坑工程监测技术规程 / XX 项目基坑支护专项方案"
    "source_type": "user_uploaded",
    "metrics": {
        "wall_top_horizontal_displacement": {
            "rules": [
                {
                    "rule_id": "USER-WTHD-L1",
                    "safety_level": ["一级"],
                    "support_type": ["地下连续墙"],
                    "cumulative_mm": {"min": 20, "max": 30},
                    "cumulative_pct_H": {"min": 0.2, "max": 0.3},
                    "rate_mm_per_day": {"min": 2, "max": 3},
                    "evidence": {"standard": "填写规范/方案全称", "clause": "填写条文号", "note": ""},
                }
            ]
        }
    },
}


def upload_standard(
    payload: dict,
    user_dir: str | Path | None = None,
    filename: str | None = None,
    overwrite: bool = False,
    ctx: Any = None,
) -> dict:
    """写入用户上传的规范阈值文件，并校验其阈值是否比默认规范更宽松。

    返回 {"ok": True, "path": ..., "strictness": {...}} 或 {"ok": False, "problems": [...]}。
    只写入 `standards/user_uploaded/`，绝不触碰默认规范库与原始数据。

    **严格度校验只反馈、不阻断**：更宽松的阈值可能来自合法的地方规程或项目专项方案，
    系统不做裁判，但必须把具体差异连同默认值的规范依据反馈给用户。
    `ctx` 可选；提供 `excavation_depth_m` 时按判定同口径比较有效累计限值，
    未提供时退化为逐字段比较并在结果中注明。
    """
    d = Path(user_dir) if user_dir else USER_DIR
    d.mkdir(parents=True, exist_ok=True)

    registry = StandardsRegistry(user_dir=d)
    problems = registry.validate_upload(payload)
    if problems:
        return {"ok": False, "problems": problems}

    name = filename or f"{payload.get('source_id') or 'user_standard'}.json"
    if not name.endswith(".json"):
        name += ".json"
    target = d / name
    if target.exists() and not overwrite:
        return {"ok": False, "problems": [f"文件已存在：{target.name}（如需覆盖请传入 overwrite=True）"]}

    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 写入后**重新加载**再比较，保证比较对象就是将来实际生效的合并规则
    strictness = check_upload_strictness(StandardsRegistry(user_dir=d), payload, ctx)

    from limit_strictness import format_report

    return {
        "ok": True,
        "path": str(target),
        "source_id": payload.get("source_id"),
        "strictness": strictness,
        "strictness_report": format_report(strictness["looser"]) if strictness["has_looser"] else "",
    }


def check_upload_strictness(
    registry: "StandardsRegistry",
    payload: dict,
    ctx: Any = None,
) -> dict:
    """比对用户上传阈值与默认规范库的严格程度。

    只比较用户**实际给出**的字段；默认库无对应判据时归入 `unmatched`（不告警）。
    取值来自**字段级合并后**的规则（用户未给出的字段继承默认值），
    避免把继承来的约束漏掉而高估放宽幅度。

    注意：上传校验发生在用户规范**落盘之前**，此时 registry 里只有默认库，
    因此"合并后规则"必须现场合成（`{**default_rule, **user_rule}`），
    不能从 registry 取 —— 否则会把默认值当成用户值，校验永远显示"无差异"。
    """
    from limit_strictness import (
        compare_rule_strictness,
        find_default_rule,
        summarize,
    )

    names = registry.display_names()
    comparisons: list[dict] = []
    unmatched: list[dict] = []

    for metric_key, m in (payload.get("metrics") or {}).items():
        for rule in (m.get("rules") or []):
            rid = rule.get("rule_id")
            default_rule, how = find_default_rule(registry, metric_key, rule, rid)
            if default_rule is None:
                unmatched.append({
                    "metric_key": metric_key,
                    "metric_name": names.get(metric_key, metric_key),
                    "rule_id": rid,
                    "reason": how,
                })
                continue
            # 现场合成字段级合并后的规则：用户显式字段覆盖默认字段
            effective = {**default_rule, **rule}
            comparisons.extend(
                compare_rule_strictness(
                    metric_key,
                    rule,
                    default_rule,
                    registry,
                    ctx,
                    metric_name=names.get(metric_key, metric_key),
                    user_evidence=rule.get("evidence"),
                    default_evidence=default_rule.get("evidence"),
                    user_rule_id=rid,
                    effective_rule=effective,
                    scope_fields=set(rule),
                )
            )

    result = summarize(comparisons)
    result["unmatched"] = unmatched
    result["matched_rule_note"] = "只比较用户实际提供的字段；未提供的字段继承默认库，取值按合并后规则计算"
    return result


def clear_user_standards(user_dir: str | Path | None = None) -> int:
    """清空用户上传目录（仅用于测试）。返回删除的文件数。"""
    d = Path(user_dir) if user_dir else USER_DIR
    if not d.exists():
        return 0
    n = 0
    for p in d.glob("*.json"):
        if p.name.endswith(".example.json"):
            continue
        p.unlink()
        n += 1
    return n


def write_upload_template(dest: str | Path) -> Path:
    """导出上传模板，供前端/用户填写。"""
    p = Path(dest)
    if p.is_dir():
        p = p / "user_standard_template.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(UPLOAD_TEMPLATE, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
