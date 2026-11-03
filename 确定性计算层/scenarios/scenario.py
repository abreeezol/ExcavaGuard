"""场景画像（Scenario Profile）加载与访问
======================================

用途
----
ExcavaGuard 的三阶段引擎原本默认按「基坑工程监测」这一场景固化了一批隐含假设：
监测项清单、规范判据来源、条件维度（安全等级/支护形式/管线类型…）、
比例限值的参照长度（基坑设计深度 H）、问题类别、日报附表表式。

本模块把这些假设收敛成一个**显式、可校验、可切换**的画像文件：

    确定性计算层/scenarios/<scenario_id>.json

引擎只读取画像里声明过的东西；画像没声明的，仍走代码内置的基坑默认值。
因此：

- 画像 `jikeng` 的取值与内置默认完全一致 → 现有行为、现有 242 项回归不受影响；
- 画像 `tunnel` 提供隧道施工场景的骨架 → 待规范与数据接入后即可切换；
- 未显式指定场景时默认 `jikeng`，即"不改变现状"。

切换方式
--------
1. 环境变量：`EXCAVAGUARD_SCENARIO=tunnel`
2. 代码显式传入：`load_profile("tunnel")` / `run_pipeline(..., scenario=profile)`
3. 桥接协议：`options.scenario = "tunnel"`（见 `skills/evaluate-thresholds/scripts/run_judgement.py`）

安全边界
--------
- 画像只描述"用什么判据、什么维度、什么表式"，**不承载任何阈值数字**；
  阈值只能来自规范条文（`standards/` 下的判据库）并经人工复核。
- `status != "active"` 的画像（如 tunnel）**不得产出工程结论**：
  缺判据的测项在阶段三一律弃权，绝不因为"没超限"就判"正常"。
"""

from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

SCENARIO_SCHEMA = "excavaguard.scenario_profile/v1"

ENGINE_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = ENGINE_ROOT / "scenarios"
DEFAULT_SCENARIO = "jikeng"
ENV_VAR = "EXCAVAGUARD_SCENARIO"

STATUS_ACTIVE = "active"
STATUS_SKELETON = "skeleton"

# 内置默认（与改造前代码完全一致）：仅在画像未声明时兜底
BUILTIN_CONDITION_DIMENSIONS = (
    "safety_level",
    "support_type",
    "pipeline_type",
    "road_type",
    "crack_state",
)
BUILTIN_SPECIFICITY_DIMENSIONS = (
    "support_type",
    "pipeline_type",
    "road_type",
    "crack_state",
)
BUILTIN_DEFAULT_CONDITIONS = {"safety_level": "一级", "support_type": "地下连续墙"}
BUILTIN_REFERENCE_KEY = "excavation_depth_m"
BUILTIN_REFERENCE_LABEL = "基坑设计深度 H"
BUILTIN_DEFAULT_LABEL = "默认规范库（基坑智守项目相关规范）"
BUILTIN_USER_LABEL = "用户上传规范"
BUILTIN_DEFAULT_DIR = "standards/default"
BUILTIN_TEMPLATE_VERSION = "deep-pit-monitoring-report/service-v5"


class ScenarioError(Exception):
    """画像不可用（缺失、JSON 非法、契约不满足）。"""


# --- 加载 -----------------------------------------------------------------


def _profile_paths() -> dict[str, Path]:
    if not SCENARIOS_DIR.is_dir():
        return {}
    return {
        p.stem: p
        for p in sorted(SCENARIOS_DIR.glob("*.json"))
        if p.name != "scenario_profile.schema.json"
    }


def available_scenarios() -> list[str]:
    return sorted(_profile_paths())


def _validate(profile: Any, source: Path) -> dict:
    if not isinstance(profile, dict):
        raise ScenarioError(f"{source.name}：场景画像必须是 JSON 对象。")
    schema = profile.get("schema")
    if schema != SCENARIO_SCHEMA:
        raise ScenarioError(
            f"{source.name}：schema 必须是 {SCENARIO_SCHEMA!r}，实际 {schema!r}。"
        )
    for field in ("id", "name", "status"):
        if not isinstance(profile.get(field), str) or not profile[field].strip():
            raise ScenarioError(f"{source.name}：缺少必填字段 {field}。")
    if profile["status"] not in (STATUS_ACTIVE, STATUS_SKELETON):
        raise ScenarioError(
            f"{source.name}：status 只能是 {STATUS_ACTIVE!r} 或 {STATUS_SKELETON!r}。"
        )
    if profile["id"] != source.stem:
        raise ScenarioError(
            f"{source.name}：id（{profile['id']}）必须与文件名（{source.stem}）一致，"
            "否则通过环境变量切换时无法定位。"
        )
    if not isinstance(profile.get("standards"), dict):
        raise ScenarioError(f"{source.name}：缺少 standards 段。")
    return profile


@lru_cache(maxsize=8)
def _load_cached(key: str) -> dict:
    paths = _profile_paths()
    if key not in paths:
        raise ScenarioError(
            f"未找到场景画像 {key!r}；可用场景：{available_scenarios() or '（无）'}。"
        )
    path = paths[key]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScenarioError(f"{path.name} 不是有效 JSON：{exc}") from exc
    profile = _validate(payload, path)
    profile["_path"] = str(path)
    return profile


def load_profile(name: str | None = None) -> dict:
    """按场景 id 加载画像；``None`` 时读取环境变量，缺省基坑。"""
    key = (name or os.environ.get(ENV_VAR) or DEFAULT_SCENARIO).strip()
    return _load_cached(key)


def active_profile() -> dict:
    return load_profile(None)


def active_scenario_id() -> str:
    return str(active_profile().get("id") or DEFAULT_SCENARIO)


def is_ready(profile: dict | None = None) -> bool:
    """场景是否具备产出工程结论的条件（判据库已接入且已复核）。

    `ready` 显式声明优先；未声明时按「status=active 且无待接入项」推断。
    `pending_inputs` 里可以放"每个项目都要填的运行时参数"（如 U0、开挖直径），
    这类参数缺失只会让对应判据弃权，不代表整个场景不可用。
    """
    p = profile or active_profile()
    if isinstance(p.get("ready"), bool):
        return bool(p["ready"]) and p.get("status") == STATUS_ACTIVE
    return p.get("status") == STATUS_ACTIVE and not p.get("pending_inputs")


# --- 访问器（全部带内置默认兜底） -----------------------------------------


def resolve_path(profile: dict, value: str | None) -> Path | None:
    """画像里的相对路径按引擎根目录解析；绝对路径原样返回。"""
    if not value:
        return None
    p = Path(value)
    return p if p.is_absolute() else (ENGINE_ROOT / p)


def standards_dir(profile: dict | None = None) -> Path:
    p = profile or active_profile()
    declared = (p.get("standards") or {}).get("default_dir")
    return resolve_path(p, declared) or (ENGINE_ROOT / BUILTIN_DEFAULT_DIR)


def user_standards_dir(profile: dict | None = None) -> Path | None:
    p = profile or active_profile()
    return resolve_path(p, (p.get("standards") or {}).get("user_dir"))


def origin_labels(profile: dict | None = None) -> dict[str, str]:
    """规范来源显示名：运维人员看到的"依据来自哪里"。"""
    p = profile or active_profile()
    s = p.get("standards") or {}
    return {
        "default": s.get("origin_display_default") or BUILTIN_DEFAULT_LABEL,
        "user": s.get("origin_display_user") or BUILTIN_USER_LABEL,
    }


def metric_alias_extras(profile: dict | None = None) -> dict[str, str]:
    p = profile or active_profile()
    extra = (p.get("metric_aliases") or {}).get("extra") or {}
    return {str(k): str(v) for k, v in extra.items()}


def problem_category_extras(profile: dict | None = None) -> dict[str, str]:
    p = profile or active_profile()
    extra = (p.get("problem_categories") or {}).get("extra") or {}
    return {str(k): str(v) for k, v in extra.items()}


def condition_dimensions(profile: dict | None = None) -> tuple[str, ...]:
    p = profile or active_profile()
    dims = (p.get("conditions") or {}).get("dimensions")
    return tuple(dims) if isinstance(dims, list) and dims else BUILTIN_CONDITION_DIMENSIONS


def specificity_dimensions(profile: dict | None = None) -> tuple[str, ...]:
    p = profile or active_profile()
    dims = (p.get("conditions") or {}).get("specificity_dimensions")
    if isinstance(dims, list) and dims:
        return tuple(dims)
    return tuple(d for d in condition_dimensions(p) if d != "safety_level")


def default_conditions(profile: dict | None = None) -> dict[str, str]:
    p = profile or active_profile()
    defaults = (p.get("conditions") or {}).get("defaults")
    return dict(defaults) if isinstance(defaults, dict) else dict(BUILTIN_DEFAULT_CONDITIONS)


def condition_labels(profile: dict | None = None) -> dict[str, str]:
    p = profile or active_profile()
    labels = (p.get("conditions") or {}).get("labels")
    return {str(k): str(v) for k, v in labels.items()} if isinstance(labels, dict) else {}


def reference_length_key(profile: dict | None = None) -> str:
    p = profile or active_profile()
    key = (p.get("reference_lengths") or {}).get("primary")
    return str(key) if key else BUILTIN_REFERENCE_KEY


def reference_length_label(key: str, profile: dict | None = None) -> str:
    p = profile or active_profile()
    labels = (p.get("reference_lengths") or {}).get("labels") or {}
    return str(labels.get(key) or (BUILTIN_REFERENCE_LABEL if key == BUILTIN_REFERENCE_KEY else key))


def template_version(profile: dict | None = None) -> str:
    p = profile or active_profile()
    return str((p.get("report") or {}).get("template_version") or BUILTIN_TEMPLATE_VERSION)


def derived_metrics(profile: dict | None = None) -> list[dict]:
    """差值型派生定义（如断面净空收敛 = 同一断面两测点之差）。默认无。"""
    p = profile or active_profile()
    items = p.get("derived_metrics")
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def pending_inputs(profile: dict | None = None) -> list[str]:
    p = profile or active_profile()
    items = p.get("pending_inputs")
    return [str(i) for i in items] if isinstance(items, list) else []


def summary(profile: dict | None = None) -> dict:
    """放进载荷/轨迹的场景摘要（只读、可审计）。"""
    p = profile or active_profile()
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "status": p.get("status"),
        "ready": is_ready(p),
        "standards_dir": str(standards_dir(p)),
        "condition_dimensions": list(condition_dimensions(p)),
        "default_conditions": default_conditions(p),
        "reference_length": reference_length_key(p),
        "pending_inputs": pending_inputs(p),
    }


# --- 规范库工厂 -----------------------------------------------------------


def _ensure_engine_paths() -> None:
    for name in (
        "pipeline",
        "pipeline/stage1_data_preparation",
        "pipeline/stage2_deterministic_calc",
        "pipeline/stage3_standard_comparison",
    ):
        p = str(ENGINE_ROOT / name)
        if p not in sys.path:
            sys.path.insert(0, p)


def load_registry(
    profile: dict | None = None,
    *,
    user_dir: str | Path | None = None,
    default_dir: str | Path | None = None,
):
    """按画像构建规范库注册表（默认仍是 `standards/default`）。"""
    _ensure_engine_paths()
    from standards_registry import StandardsRegistry

    p = profile or active_profile()
    labels = origin_labels(p)
    return StandardsRegistry(
        default_dir=default_dir or standards_dir(p),
        user_dir=user_dir or user_standards_dir(p) or (ENGINE_ROOT / "standards" / "user_uploaded"),
        origin_labels=labels,
        condition_dimensions=condition_dimensions(p),
        specificity_dimensions=specificity_dimensions(p),
        reference_length_label=lambda key: reference_length_label(key, p),
    )


def attach_to_context(ctx: Any, profile: dict | None = None) -> Any:
    """把画像的默认条件写进 ProjectContext（不改写调用方已显式给出的值）。"""
    p = profile or active_profile()
    conditions = dict(default_conditions(p))
    existing = dict(getattr(ctx, "conditions", None) or {})
    for key, value in conditions.items():
        existing.setdefault(key, value)
    ctx.conditions = existing
    if not getattr(ctx, "scenario_id", None):
        ctx.scenario_id = str(p.get("id"))
    return ctx
