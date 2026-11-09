"""Presentation labels only; evidence IDs remain internal immutable join keys."""
from functools import lru_cache
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]


def clean_name(name):
    return re.sub(r"[（(]标准网[^）)]*[）)]", "", str(name or "")).strip()


@lru_cache(maxsize=1)
def standard_names():
    registry = json.loads((ROOT / "确定性计算层/standards/default/规范库索引.json").read_text(encoding="utf-8"))
    return {re.sub(r"[^A-Z0-9]", "", entry["code"].upper()): clean_name(entry["name"])
            for entry in registry["standards"]}


def citation_label(metadata):
    name = clean_name(metadata.get("standard_name"))
    version = str(metadata.get("standard_version") or "").strip()
    clause = str(metadata.get("clause") or "").strip()
    if not name or not version or not clause:
        raise ValueError("INVALID_EVIDENCE_SOURCE：规范引用缺少名称、编号或条文，不能以切片ID代替。")
    return f"《{name}》 {version} · {clause}"


def source_location(metadata):
    return str(metadata.get("source_location") or "来源定位待补充").split("#chunk=", 1)[0]


def engine_basis(item):
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    effective = item.get("effective_standard") if isinstance(item.get("effective_standard"), dict) else {}
    source = str(evidence.get("standard") or effective.get("source_label") or "").strip()
    clause = str(evidence.get("clause") or "").strip()
    normalized = re.sub(r"[^A-Z0-9]", "", source.upper())
    for code, name in standard_names().items():
        if code in normalized:
            # Preserve the source's displayed code and its exact frozen clause.
            match = re.search(r"(?:GB\s*/?\s*T?|JGJ\s*/?\s*T?)\s*\d+\s*[-－]\s*\d{4}", source, re.I)
            version = match.group(0) if match else code
            return f"《{name}》 {version}" + (f" · {clause}" if clause else " · 条文待复核")
    if source and not re.fullmatch(r"[a-zA-Z0-9_.:/#-]+", source):
        return f"《{clean_name(source)}》" + (f" · {clause}" if clause else " · 条文待复核")
    return "未匹配具名适用规范（待复核）"


def reference_text(report, ids):
    labels = {item["id"]: citation_label(item.get("metadata") or {})
              for item in report["sections"]["standard_evidence"].get("items", [])}
    if any(eid not in labels for eid in ids):
        raise ValueError("UNGROUNDED_CITATION：引用不存在的规范来源。")
    return "；".join(dict.fromkeys(labels[eid] for eid in ids))


def paragraph_text(report, paragraph):
    text = paragraph.get("text", "")
    refs = reference_text(report, paragraph.get("evidence_ids") or [])
    return text + ("\n规范依据：" + refs if refs else "")


def form_evidence(report, form):
    """Only associate references explicitly attached to this form by report-delivery."""
    narrative = report["sections"].get("narrative") or {}
    entry = next((item for item in narrative.get("appendix_analysis", []) if item["form"] == form), {})
    ids = [eid for field in ("analysis", "recommendation") for eid in entry.get(field, {}).get("evidence_ids", [])]
    ids += [item["id"] for item in project_form_candidates(report, form)]
    return reference_text(report, list(dict.fromkeys(ids)))


def project_form_candidates(report, form):
    """Procedural candidates only; never infer compliance or change numeric rules."""
    words = {"A": ["水平位移", "位移"], "B": ["深层", "测斜"],
             "C": ["内力", "土压力", "孔隙水"], "D": ["轴力", "锚杆"],
             "E": ["水位", "沉降", "隆起", "竖向"], "F": ["裂缝"]}.get(form, [])
    return [item for item in report["sections"]["standard_evidence"].get("items", [])
            if item.get("provider") == "project" and
            (any(word in item["text"] for word in words) or
             any(word in item["text"] for word in ("监测频率", "监测频次", "监测日报", "巡视", "预警", "报警")))]
