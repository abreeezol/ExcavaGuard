"""
用户阈值宽松度校验
==================

**目的**：用户上传的地方规程 / 项目专项方案按字段级覆盖默认规范库时，
判断覆盖后的阈值是否比默认值**更宽松**，并把具体差异连同**默认值的规范依据**
（规范名称 + 条文号 + 限值推导）反馈给用户。

为什么需要
----------
`resolve_limit()` 的 `rank()` 只判断"规则是否来自用户"，**不判断是否更宽松**。
用户上传一份把「一级基坑墙顶水平位移累计限值」从 20 mm 放宽到 50 mm 的文件，
系统会照用，把本该判为「危险报警」的 35 mm 判成「预警」—— 这是漏判。

设计原则
--------
- **只反馈，不阻断**：更宽松可能是合法的地方规程，系统不做裁判，但必须让用户看见。
- **只比较用户实际覆盖的字段**：未提供的字段继承默认，天然一致。
- **按有效值比较，不按原始字段比较**：
  累计值限值取 `min(绝对量, %H)`，逐字段比会产生假告警
  （用户调宽绝对量但调严 %H 时，有效限值可能没变）。
- **缺 H 时判为"不可比"而不是"未放宽"**：不能静默放过。
- **默认库无对应判据时不告警**：属"用户新增判据"，不是"更宽松"。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

# 结果标记
LOOSER_FLAG = "USER_LIMIT_LOOSER_THAN_DEFAULT"
INCOMPARABLE_FLAG = "USER_LIMIT_NOT_COMPARABLE"

# 严重度阈值（放宽幅度 %）
SEVERITY_SERIOUS = 20.0
SEVERITY_MINOR = 5.0

# 比较项：字段 → (显示名, 越严方向)
#   "smaller" = 数值越小越严格（限值上限类）
#   "larger"  = 数值越大越严格（预应力下限类，方向与其余相反）
LIMIT_FIELDS: "OrderedDict[str, tuple[str, str]]" = OrderedDict([
    ("cumulative_mm", ("累计值限值", "smaller")),
    ("rate_mm_per_day", ("变化速率限值", "smaller")),
    ("cumulative_inclination", ("累计倾斜限值", "smaller")),
    ("rate_inclination_per_day", ("倾斜速率限值", "smaller")),
    ("max_ratio_of_design", ("承载力上限比例", "smaller")),
    ("min_ratio_of_design", ("预应力下限比例", "larger")),   # ★ 方向相反
])

# 累计值限值由这两个字段合成，需整体比较
CUMULATIVE_INPUTS = ("cumulative_mm", "cumulative_pct_H")

RATIO_FIELDS = {"max_ratio_of_design", "min_ratio_of_design"}


def _severity(delta_pct: float) -> str:
    if delta_pct >= SEVERITY_SERIOUS:
        return "严重"
    if delta_pct >= SEVERITY_MINOR:
        return "中等"
    return "轻微"


def _is_looser(user_v: float, default_v: float, direction: str) -> bool:
    return user_v > default_v if direction == "smaller" else user_v < default_v


def _delta_pct(user_v: float, default_v: float, direction: str) -> float:
    """放宽幅度（%）。以默认值为基准，正值表示更宽松。"""
    if not default_v:
        return 0.0
    base = abs(float(default_v))
    if direction == "smaller":
        return (float(user_v) - float(default_v)) / base * 100.0
    return (float(default_v) - float(user_v)) / base * 100.0


def _effective_cumulative(rule: dict, registry: Any, ctx: Any) -> tuple[float | None, str]:
    """按判定同口径解析累计值有效限值：min(绝对量, %H)。

    返回 (值 mm, 依据说明)；无法解析时返回 (None, 原因)。
    """
    from risk_identifier import _pick  # 与判定共用区间解析口径

    mode = registry.range_resolution
    abs_limit = _pick(rule.get("cumulative_mm"), mode)
    pct_spec = rule.get("cumulative_pct_H")
    pct = _pick(pct_spec, mode) if (pct_spec is not None) else None

    h = getattr(ctx, "excavation_depth_m", None)
    pct_limit = None
    if pct is not None:
        if isinstance(h, (int, float)) and h > 0:
            pct_limit = pct * float(h) * 10.0          # pct[%] × H[m] × 10 = mm
        else:
            return None, "缺少基坑设计深度 H，无法换算 %H 限值"

    if abs_limit is not None and pct_limit is not None:
        return min(abs_limit, pct_limit), f"min(绝对量 {abs_limit:g} mm, {pct:g}%×H={pct_limit:g} mm)"
    if abs_limit is not None:
        return abs_limit, f"绝对量限值 {abs_limit:g} mm"
    if pct_limit is not None:
        return pct_limit, f"{pct:g}%×H = {pct_limit:g} mm"
    return None, "规则未给出累计值限值"


def _field_unit(field: str) -> str:
    if field == "rate_mm_per_day":
        return "mm/d"
    if field in RATIO_FIELDS:
        return "（比例）"
    if field == "rate_inclination_per_day":
        return "/d"
    return "mm" if field in ("cumulative_mm", "cumulative_inclination") else ""


def default_metrics(registry: Any) -> dict:
    """取默认规范库的原始 metrics（未与用户上传合并）。"""
    from standards_registry import ORIGIN_DEFAULT

    for s in getattr(registry, "sources", []):
        if s.origin == ORIGIN_DEFAULT:
            return s.payload.get("metrics") or {}
    return {}


def find_default_rule(
    registry: Any,
    metric_key: str,
    user_rule: dict,
    user_rule_id: str | None = None,
) -> tuple[dict | None, str]:
    """找出用户规则所覆盖的那条默认规则。

    匹配顺序：
      1. **同 rule_id** —— 字段级合并的正常情形；
      2. **条件匹配** —— 用户用了不同的 rule_id 但条件组合一致；
    都找不到时返回 (None, 原因)，此时属"用户新增判据"，不告警。
    """
    from risk_identifier import _match

    node = default_metrics(registry).get(metric_key)
    if not node:
        return None, "默认规范库中没有该监测项"

    rules = {r.get("rule_id"): r for r in (node.get("rules") or []) if r.get("rule_id")}

    if user_rule_id and user_rule_id in rules:
        return rules[user_rule_id], "同 rule_id 覆盖"

    # 条件匹配：安全等级 / 支护形式 / 管线类型 / 道路类型 / 裂缝状态
    cond_keys = ("safety_level", "support_type", "pipeline_type", "road_type", "crack_state")
    hits = []
    for rid, r in rules.items():
        ok = True
        for k in cond_keys:
            uv = user_rule.get(k)
            if uv in (None, "any", []):
                continue
            if not _match(r.get(k), uv if isinstance(uv, str) else (uv[0] if isinstance(uv, list) and uv else None)):
                ok = False
                break
        if ok:
            hits.append((rid, r))

    if len(hits) == 1:
        return hits[0][1], f"条件匹配到默认规则 {hits[0][0]}"
    if len(hits) > 1:
        # 多个条件相同的默认规则（如按支护形式细分）—— 取最具体的一条
        hits.sort(key=lambda x: sum(1 for k in cond_keys if x[1].get(k) not in (None, "any", [])), reverse=True)
        return hits[0][1], f"条件匹配到多条默认规则，取最具体者 {hits[0][0]}"
    return None, "默认规范库中没有条件相同的判据（属用户新增判据）"


def compare_rule_strictness(
    metric_key: str,
    user_rule: dict,
    default_rule: dict,
    registry: Any,
    ctx: Any,
    *,
    metric_name: str | None = None,
    user_evidence: dict | None = None,
    default_evidence: dict | None = None,
    user_rule_id: str | None = None,
    effective_rule: dict | None = None,
    scope_fields: set[str] | None = None,
) -> list[dict]:
    """逐项比较用户规则与默认规则的严格程度。

    **比较范围**由 `scope_fields`（或 `user_rule` 中显式出现的键）决定；
    **取值**取自 `effective_rule`（用户规则与默认规则**字段级合并后**的结果），
    缺省即 `user_rule`。

    为什么要区分这两者：用户只覆盖 `cumulative_mm` 时，`cumulative_pct_H` 会**继承默认值**，
    有效限值是 `min(用户绝对量, 继承的 %H)`。若拿原始用户规则取值，会把继承来的约束漏掉，
    算出的放宽幅度偏大。

    返回差异清单，每项含 `direction` ∈ {looser, stricter, equal, incomparable}。
    调用方只应把 `direction == "looser"` 的项作为告警展示。
    """
    out: list[dict] = []
    eff = effective_rule if effective_rule is not None else user_rule
    scope = scope_fields if scope_fields is not None else set(user_rule)
    d_ev = dict(default_evidence or default_rule.get("evidence") or {})
    u_ev = dict(user_evidence or user_rule.get("evidence") or {})

    def emit(field: str, display: str, direction: str, u_val, d_val, basis: str, note: str = "") -> None:
        item: dict[str, Any] = {
            "metric_key": metric_key,
            "metric_name": metric_name or metric_key,
            "field": field,
            "field_display": display,
            "unit": _field_unit(field),
            "user_value": u_val,
            "default_value": d_val,
            "direction": direction,
            "default_basis": basis,
            "default_evidence": d_ev,
            "user_evidence": u_ev,
            "user_rule_id": user_rule_id,
            "note": note,
        }
        if direction in ("looser", "stricter", "equal") and d_val not in (None, 0):
            item["delta_pct"] = round(_delta_pct(u_val, d_val, "larger" if field == "min_ratio_of_design" else "smaller"), 2)
            if direction == "looser":
                item["severity"] = _severity(item["delta_pct"])
            else:
                item["delta_pct"] = -abs(item["delta_pct"])
        out.append(item)

    # --- 1) 累计值限值 ---
    # 有 H 时按判定同口径比较**合并后**的有效值 min(绝对量, %H)；
    # 无 H 且规则含 %H 分量时判为"不可比"（无法确定有效限值，不能默认放过）；
    # 无 H 且规则不含 %H 时可直接比较绝对量。
    h = getattr(ctx, "excavation_depth_m", None) if ctx is not None else None
    has_h = isinstance(h, (int, float)) and h > 0
    pct_involved = ("cumulative_pct_H" in default_rule) or ("cumulative_pct_H" in eff)

    if scope & set(CUMULATIVE_INPUTS):
        if has_h:
            u_eff, u_basis = _effective_cumulative(eff, registry, ctx)
            d_eff, d_basis = _effective_cumulative(default_rule, registry, ctx)
            if u_eff is None or d_eff is None:
                emit("cumulative_mm", "累计值限值", "incomparable", u_eff, d_eff, d_basis,
                     note=u_basis if u_eff is None else "")
            else:
                direction = "looser" if u_eff > d_eff else ("stricter" if u_eff < d_eff else "equal")
                emit("cumulative_mm", "累计值限值", direction, u_eff, d_eff, d_basis,
                     note="按判定同口径比较（合并后的 min(绝对量, %H)）")
        elif pct_involved:
            u_val = _scalar(eff.get("cumulative_mm"))
            d_val = _scalar(default_rule.get("cumulative_mm"))
            emit("cumulative_mm", "累计值限值", "incomparable", u_val, d_val, "",
                 note="未提供基坑设计深度 H，无法确定 min(绝对量, %H) 的有效限值，"
                      "故不判定严格程度；请补充 H 后复核")
        else:
            u_val = _scalar(eff.get("cumulative_mm"))
            d_val = _scalar(default_rule.get("cumulative_mm"))
            if u_val is None or d_val is None:
                emit("cumulative_mm", "累计值限值", "incomparable", u_val, d_val, "", note="一方未给出该限值")
            else:
                direction = "looser" if u_val > d_val else ("stricter" if u_val < d_val else "equal")
                emit("cumulative_mm", "累计值限值", direction, u_val, d_val, "",
                     note="规则不含 %H 分量，直接比较绝对量限值")

    # --- 2) 其余单项字段 ---
    for field, (display, dirn) in LIMIT_FIELDS.items():
        if field == "cumulative_mm":
            continue  # 已在第 1 步整体处理
        if field not in scope:
            continue
        u_spec, d_spec = eff.get(field), default_rule.get(field)
        u_val = _scalar(u_spec)
        d_val = _scalar(d_spec)
        if u_val is None or d_val is None:
            emit(field, display, "incomparable", u_val, d_val, "", note="一方未给出该限值")
            continue
        if _is_looser(u_val, d_val, dirn):
            direction = "looser"
        elif u_val == d_val:
            direction = "equal"
        else:
            direction = "stricter"
        emit(field, display, direction, u_val, d_val, "")

    return out


def _scalar(spec: Any) -> float | None:
    """把数值或 {min,max} 规格解析为确定值（取下限，偏安全，与判定口径一致）。"""
    if spec is None:
        return None
    if isinstance(spec, (int, float)):
        return float(spec)
    if isinstance(spec, dict):
        lo, hi = spec.get("min"), spec.get("max")
        if isinstance(lo, (int, float)):
            return float(lo)
        if isinstance(hi, (int, float)):
            return float(hi)
    return None


def summarize(comparisons: list[dict]) -> dict:
    """汇总比较结果，供上传接口返回体使用。"""
    looser = [c for c in comparisons if c["direction"] == "looser"]
    incomparable = [c for c in comparisons if c["direction"] == "incomparable"]
    return {
        "checked": len(comparisons),
        "looser_count": len(looser),
        "incomparable_count": len(incomparable),
        "has_looser": bool(looser),
        "severity_counts": {
            s: sum(1 for c in looser if c.get("severity") == s)
            for s in ("严重", "中等", "轻微")
        },
        "looser": looser,
        "incomparable": incomparable,
        "all": comparisons,
    }


def format_report(items: list[dict], title: str = "用户阈值比默认规范更宽松") -> str:
    """把差异清单格式化为可直接展示给用户的文本。"""
    if not items:
        return ""
    lines = [f"⚠ {title}（{len(items)} 处）", ""]
    for i, c in enumerate(items, 1):
        ev = c.get("default_evidence") or {}
        std = ev.get("standard", "（未标注规范）")
        clause = ev.get("clause", "")
        uev = c.get("user_evidence") or {}
        src = uev.get("standard") or "用户上传规范"
        unit = c.get("unit", "")
        lines.append(f"[{i}] {c['metric_name']} · {c['field_display']}")
        lines.append(f"    用户值   {c['user_value']}{unit}     ← 来源：{src}")
        basis = f"（{c['default_basis']}）" if c.get("default_basis") else ""
        lines.append(f"    默认值   {c['default_value']}{unit}     ← 依据：{std} {clause}{basis}")
        if "delta_pct" in c:
            lines.append(f"    放宽幅度 {c['delta_pct']:+.2f}%（{c.get('severity', '')}）")
        if c.get("note"):
            lines.append(f"    说明：{c['note']}")
        lines.append("")
    lines.append("说明：更宽松的阈值会降低报警灵敏度，可能造成漏判。")
    lines.append("      若该阈值来自经设计方确认的地方规程或项目专项方案，请在日报中注明；")
    lines.append("      否则建议采用默认规范值（GB 50497-2019 第 8.0.1 条：预警值应由设计方确定）。")
    return "\n".join(lines)
