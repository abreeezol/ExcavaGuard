"""阶段三 · 断面级综合判定
=========================

为什么需要
----------
基坑是按测点判的：一个测点一个测项，超了就是超了。隧道不是——规范要求
**同一断面的拱顶下沉与净空收敛同时量测**，工程师看的是"这个断面怎么样"，
不是"GD-01 这个点怎么样"。只给逐点结论，会把一个断面拆成互不相干的几行，
既看不出最不利位置，也看不出"该测的没测"。

本模块只做三件事，不新增任何阈值：

1. **归组**：按显式给出的「测点 → 断面」映射把逐条判定聚到断面下。
   没有映射的测点进 `unassigned` 并披露，**不按点号前缀猜断面**。
2. **取最不利**：断面等级 = 该断面所有可判定条目中最不利的等级。
3. **完整性否决**：规范要求同断面必测的项目缺失时，断面不得判为「正常」；
   该断面降为「未知」并给出缺项清单（缺测 ≠ 安全）。

与五级分级的边界
----------------
断面等级不改变任何单条判定的等级，也不引入新的等级定义；
它只是把已有等级聚合成"断面结论"，并明确标出结论是否完整。
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

LEVEL_NORMAL = "正常"
LEVEL_ATTENTION = "关注"
LEVEL_WARNING = "预警"
LEVEL_ALARM = "报警"
LEVEL_DANGER = "危险报警"
LEVEL_UNKNOWN = "未知"

LEVEL_RANK = {
    LEVEL_UNKNOWN: -1,
    LEVEL_NORMAL: 0,
    LEVEL_ATTENTION: 1,
    LEVEL_WARNING: 2,
    LEVEL_ALARM: 3,
    LEVEL_DANGER: 4,
}

SECTION_COMPLETE = "complete"
SECTION_INCOMPLETE = "incomplete"
SECTION_EMPTY = "empty"


def _higher(a: str, b: str) -> str:
    return a if LEVEL_RANK.get(a, -1) >= LEVEL_RANK.get(b, -1) else b


def build_section_map(
    points_meta: dict | None,
    explicit: dict | None = None,
) -> dict[str, str]:
    """构造 ``{point_id: section_id}``。

    来源优先级：
      1. 显式映射 ``explicit = {point_id: section_id}``
      2. 测点台账 ``points_meta[point_id]["section_id"]``（也接受 ``section`` / ``里程``）
    两边都缺的测点不会出现在返回结果里 —— 由调用方披露为"未归属断面"。
    """
    out: dict[str, str] = {}
    for pid, sec in (explicit or {}).items():
        if pid and sec not in (None, ""):
            out[str(pid)] = str(sec)
    for pid, meta in (points_meta or {}).items():
        if not isinstance(meta, dict):
            continue
        sec = meta.get("section_id") or meta.get("section") or meta.get("里程") or meta.get("chainage")
        if sec not in (None, "") and str(pid) not in out:
            out[str(pid)] = str(sec)
    return out


def judge_sections(
    items: Sequence[dict],
    section_map: dict[str, str],
    *,
    required_metrics: Iterable[str] = (),
    strict: bool = True,
    metric_names: dict | None = None,
) -> dict:
    """把逐条判定聚合成断面结论。

    参数
    ----
    items            : 载荷 `items`（含 point_id / metric_key / metric_name / risk_level / utilization）
    section_map      : ``{point_id: section_id}``
    required_metrics : 规范要求同断面同时量测的测项 key（如拱顶下沉、净空收敛）
    strict           : True 时，断面内存在「未知」条目或必测项缺失 → 断面不得判为「正常」
    metric_names     : ``{metric_key: 中文名}``，用于把缺项清单写成可读名称而不是 key

    返回
    ----
    ``{"sections": [...], "unassigned": [...], "summary": {...}}``
    """
    required = [str(m) for m in required_metrics if str(m)]
    names = metric_names or {}
    # 先收集 items 里出现过的 metric_name，作为 names 的补充
    for row in items:
        key = str(row.get("metric_key") or "")
        name = row.get("metric_name")
        if key and name and key not in names:
            names[key] = name
    buckets: dict[str, list[dict]] = {}
    unassigned: list[dict] = []
    for item in items:
        pid = str(item.get("point_id") or "")
        sec = section_map.get(pid)
        if sec is None:
            unassigned.append({
                "point_id": item.get("point_id"),
                "metric_key": item.get("metric_key"),
                "metric_name": item.get("metric_name"),
                "risk_level": item.get("risk_level"),
            })
            continue
        buckets.setdefault(sec, []).append(item)

    sections: list[dict] = []
    for sec, rows in buckets.items():
        by_level: dict[str, int] = {}
        worst = LEVEL_UNKNOWN
        worst_item: dict | None = None
        metrics_present: list[str] = []
        for row in rows:
            level = str(row.get("risk_level") or LEVEL_UNKNOWN)
            by_level[level] = by_level.get(level, 0) + 1
            mk = str(row.get("metric_key") or "")
            if mk and mk not in metrics_present:
                metrics_present.append(mk)
            if LEVEL_RANK.get(level, -1) > LEVEL_RANK.get(worst, -1):
                worst = level
                worst_item = row

        missing = [m for m in required if m not in metrics_present]
        has_unknown = any(str(r.get("risk_level")) == LEVEL_UNKNOWN for r in rows)
        incomplete_reasons: list[str] = []
        if missing:
            missing_labels = [f"{names.get(m, m)}（{m}）" if names.get(m) else m for m in missing]
            incomplete_reasons.append("缺少规范要求的同断面测项：" + "、".join(missing_labels))
        if strict and has_unknown:
            unknown_items = [f"{r.get('point_id')}/{r.get('metric_name')}"
                             for r in rows if str(r.get("risk_level")) == LEVEL_UNKNOWN]
            incomplete_reasons.append("存在不可判定条目：" + "、".join(unknown_items))

        level = worst
        completeness = SECTION_COMPLETE
        if missing:
            completeness = SECTION_INCOMPLETE
        elif strict and has_unknown:
            completeness = SECTION_INCOMPLETE
        if completeness == SECTION_INCOMPLETE and level == LEVEL_NORMAL:
            # 缺测/不可判定 ≠ 安全：不得因为"能判的都正常"就给出断面正常
            level = LEVEL_UNKNOWN

        sections.append({
            "section_id": sec,
            "point_ids": sorted({str(r.get("point_id") or "") for r in rows}),
            "metrics": metrics_present,
            "item_count": len(rows),
            "by_risk_level": by_level,
            "worst_level": level,
            "raw_worst_level": worst,
            "worst_item": (
                {
                    "point_id": worst_item.get("point_id"),
                    "metric_key": worst_item.get("metric_key"),
                    "metric_name": worst_item.get("metric_name"),
                    "risk_level": worst_item.get("risk_level"),
                    "utilization": worst_item.get("utilization"),
                }
                if worst_item else None
            ),
            "completeness": completeness,
            "incomplete_reasons": incomplete_reasons,
            "needs_review": level == LEVEL_UNKNOWN or bool(incomplete_reasons),
            "note": (
                "断面等级取同断面最不利等级；缺测或不可判定时不得判为正常。"
            ),
        })

    sections.sort(key=lambda s: (-LEVEL_RANK.get(s["worst_level"], -1), s["section_id"]))
    overall = LEVEL_UNKNOWN
    for s in sections:
        overall = _higher(overall, s["worst_level"])
    by_level: dict[str, int] = {}
    for s in sections:
        by_level[s["worst_level"]] = by_level.get(s["worst_level"], 0) + 1

    return {
        "sections": sections,
        "unassigned": unassigned,
        "summary": {
            "sections": len(sections),
            "items_assigned": sum(s["item_count"] for s in sections),
            "items_unassigned": len(unassigned),
            "incomplete_sections": sum(1 for s in sections if s["completeness"] == SECTION_INCOMPLETE),
            "by_section_level": by_level,
            "overall_section_level": overall if sections else LEVEL_UNKNOWN,
            "required_metrics": required,
            "strict": bool(strict),
            "notice": (
                "断面归属来自显式映射（测点台账 section_id）；未归属测点单独披露，不按点号前缀推断。"
            ),
        },
    }
