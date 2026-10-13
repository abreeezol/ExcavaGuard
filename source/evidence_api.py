"""Local evidence contract shared by FastAPI and the Next.js retriever."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ROOT = Path(__file__).resolve().parents[1]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Status = Literal["active", "inactive", "unknown"]


class EvidenceFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    standard_versions: list[Label] | None = Field(default=None, min_length=1, max_length=20)
    monitoring_item: Label | None = None
    excavation_safety_level: Label | None = None
    region: Label | None = None
    effective_status: Status = "active"

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_nulls(cls, value: Any) -> Any:
        # Zod optional fields accept omission, not explicit JSON null.
        if isinstance(value, dict) and any(item is None for item in value.values()):
            raise ValueError("过滤条件字段不能为 null。")
        return value


class EvidenceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    filters: EvidenceFilters = Field(default_factory=EvidenceFilters)
    top_k: int = Field(default=3, ge=1, le=10)


class EvidenceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    standard_name: Label
    standard_version: Label
    clause: Label
    source_location: Label
    applicability: list[Label] = Field(min_length=1, max_length=20)
    effective_status: Status
    monitoring_item: Label | None = None
    excavation_safety_level: Label | None = None
    region: Label | None = None


class EvidenceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
    metadata: EvidenceMetadata
    score: float = Field(allow_inf_nan=False)
    matched_terms: list[Label] = Field(default_factory=list, max_length=50)


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    evidence: list[EvidenceCandidate] = Field(max_length=10)


class LocalEvidenceService:
    """Filter audited IDs before similarity search; preserve existing vectors."""

    def __init__(
        self,
        collection: Any,
        records_path: Path = ROOT / "var/rag/pinecone-records.jsonl",
        status_path: Path = ROOT / "rag/standard-status.json",
    ):
        self.collection = collection
        self.status_path = status_path
        self.records: dict[str, dict] = {}
        for line in records_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            record_id = record["_id"]
            if record_id in self.records or record.get("evidence_kind") != "standard":
                raise ValueError("本地证据清单存在重复 ID 或非规范记录。")
            EvidenceCandidate(
                id=record_id, text=record["chunk_text"],
                metadata=self._metadata(record, record.get("effective_status")), score=0.0,
            )
            self.records[record_id] = record
        if not self.records:
            raise ValueError("本地证据清单为空。")
        self._statuses()

    def _statuses(self) -> dict:
        manifest = json.loads(self.status_path.read_text(encoding="utf-8"))
        if (
            manifest.get("schema_version") != "excavaguard.standard_status/v1"
            or not manifest.get("reviewed_at")
            or not manifest.get("reviewed_by")
            or not isinstance(manifest.get("standards"), dict)
        ):
            raise ValueError("规范状态清单尚未复核。")
        statuses = manifest["standards"]
        for record in self.records.values():
            entry = statuses.get(record["standard_code"])
            if not isinstance(entry, dict) or entry.get("effective_status") not in (
                "active", "inactive", "unknown",
            ):
                raise ValueError("规范状态清单缺少有效状态。")
        return statuses

    @staticmethod
    def _metadata(record: dict, status: Any) -> EvidenceMetadata:
        fields = {
            key: record[key]
            for key in (
                "standard_name", "standard_version", "clause", "source_location",
                "applicability", "monitoring_item", "excavation_safety_level", "region",
            )
            if key in record
        }
        return EvidenceMetadata(**fields, effective_status=status)

    def search(self, request: EvidenceQuery) -> EvidenceResponse:
        # Read current statuses each time so revocation never needs re-embedding.
        statuses = self._statuses()
        filters = request.filters
        selected: dict[str, dict] = {}
        for record_id, record in self.records.items():
            status = statuses[record["standard_code"]]["effective_status"]
            if status != filters.effective_status:
                continue
            if (
                filters.standard_versions is not None
                and record["standard_version"] not in filters.standard_versions
            ):
                continue
            if any(
                value is not None and record.get(key) != value
                for key, value in (
                    ("monitoring_item", filters.monitoring_item),
                    ("excavation_safety_level", filters.excavation_safety_level),
                    ("region", filters.region),
                )
            ):
                continue
            selected[record_id] = record
        if not selected:
            return EvidenceResponse(evidence=[])

        result = self.collection.query(
            query_texts=["为这个句子生成表示以用于检索相关文章：" + request.query],
            ids=list(selected),
            n_results=min(request.top_k, len(selected)),
            include=["documents", "distances"],
        )
        ids = result["ids"][0]
        documents = result["documents"][0]
        distances = result["distances"][0]
        if not (len(ids) == len(documents) == len(distances)) or len(ids) > request.top_k:
            raise ValueError("本地向量库返回了无效响应。")
        evidence: list[EvidenceCandidate] = []
        seen: set[str] = set()
        for record_id, document, distance in zip(ids, documents, distances):
            record = selected.get(record_id)
            if (
                record is None or record_id in seen
                or document != record["chunk_text"]
                or isinstance(distance, bool) or not isinstance(distance, (int, float))
                or not math.isfinite(distance)
            ):
                raise ValueError("本地向量库正文或 ID 与证据清单不一致。")
            seen.add(record_id)
            evidence.append(EvidenceCandidate(
                id=record_id, text=document, score=1.0 - distance,
                metadata=self._metadata(
                    record, statuses[record["standard_code"]]["effective_status"],
                ),
                matched_terms=[],
            ))
        return EvidenceResponse(evidence=evidence)
