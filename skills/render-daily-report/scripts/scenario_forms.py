"""场景 → 日报表式映射接缝
=========================

为什么单独一个模块
------------------
基坑的附表 A~G 来自 GB 50497-2019 附录，表头、列、页脚都写在
`deep-pit-monitoring-report/scripts/appendix_forms.py` 里。隧道日报的表式
（拱顶下沉/净空收敛、地表下沉、围岩压力与支护内力、管片变形…）与基坑**不同**，
而且不同项目/规范的表头与签署栏也会有差异。

因此这里只提供**映射接缝**，不复制也不猜测表式：

- `form_map()`：返回当前场景的「测项名称关键词 → 附表代号」映射与表题。
  基坑返回既有的 `DEFAULT_FORM_MAP`（行为完全不变）。
- `is_renderable()` / `assert_renderable()`：场景画像声明 `report.renderable=false`
  时（隧道当前状态），日报渲染必须**拒绝出报**，而不是沿用基坑附录表头拼接。

为什么必须拒绝而不是"先凑一份"
------------------------------
`report_artifacts.py` 用附表代号最后一位字符去查 `APPENDIX_FORMS`；
若允许隧道直接走这条路径，`T-A` 会被截成 `A`，静默套用基坑表头 ——
一份看起来完整、实则表头与栏目都不对的日报，比不出报危险得多。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SKILLS_ROOT.parent
ENGINE_ROOT = REPO_ROOT / "确定性计算层"

if str(ENGINE_ROOT / "scenarios") not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT / "scenarios"))

import scenario as scenario_profile  # noqa: E402


class ReportFormError(RuntimeError):
    """当前场景的日报表式尚未确认，拒绝渲染。"""


def _jikeng_form_map() -> dict[str, Any]:
    scripts = SKILLS_ROOT / "deep-pit-monitoring-report" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from render_report import DEFAULT_FORM_MAP  # noqa: PLC0415 - 延迟导入避免循环

    return DEFAULT_FORM_MAP


def form_map(profile: dict | None = None) -> dict[str, Any]:
    """当前场景的表式映射。

    返回值与 `render_report.DEFAULT_FORM_MAP` 同构：
    ``{"order": [...], "rules": {表单: [关键词...]}, "forms": {表单: {title, unit}}}``
    """
    p = profile or scenario_profile.active_profile()
    report = p.get("report") or {}
    family = report.get("form_family")

    # 基坑：沿用既有附录 A~G，行为不变
    if p.get("id") == "jikeng" or family == "gb50497_appendix_A_G":
        return _jikeng_form_map()

    forms = [str(f) for f in (report.get("forms") or [])]
    titles = report.get("form_titles") or {}
    rules = report.get("form_rules") or {}
    return {
        "order": forms,
        "rules": {f: [str(k) for k in (rules.get(f) or [])] for f in forms},
        "forms": {
            f: {"title": str(titles.get(f) or f), "unit": ""}
            for f in forms
        },
    }


def template_version(profile: dict | None = None) -> str:
    """当前场景的日报模板版本（基坑 = deep-pit-monitoring-report/service-v5）。"""
    return scenario_profile.template_version(profile)


def active_report_scenario() -> str:
    """当前生效场景 id（渲染器据此选择表式族：基坑附录 A~G / 隧道附录 D）。"""
    return scenario_profile.active_scenario_id()


def is_renderable(profile: dict | None = None) -> bool:
    p = profile or scenario_profile.active_profile()
    return bool((p.get("report") or {}).get("renderable", True))


def assert_renderable(profile: dict | None = None) -> None:
    """表式未确认时拒绝出报，且说明缺什么。"""
    p = profile or scenario_profile.active_profile()
    if is_renderable(p):
        return
    pending = scenario_profile.pending_inputs(p)
    raise ReportFormError(
        f"场景 {p.get('id')}（{p.get('name')}）的日报表式尚未确认，"
        "拒绝生成三件套：不得沿用基坑附录 A~G 的表头与栏目。"
        + (f" 待提供：{'；'.join(pending[:3])}" if pending else "")
    )


def appendix_form_of(metric_name: str, profile: dict | None = None) -> str | None:
    """按表式关键词把测项名映射到附表代号；无歧义匹配失败返回 None。"""
    mapping = form_map(profile)
    for form in mapping.get("order", []):
        keywords = mapping.get("rules", {}).get(form, [])
        if any(k and k in metric_name for k in keywords):
            return form
    return None
