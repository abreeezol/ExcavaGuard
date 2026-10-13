"""Regression tests for the local provider contract (no model/network required)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from pydantic import ValidationError
from evidence_api import EvidenceQuery, LocalEvidenceService
import query_kb
import server


class CollectionFixture:
    def __init__(self):
        self.calls = []
        self.document = "自动化测试证据，不能用于工程判定。"

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ids": [["test-a"]],
            "documents": [[self.document]],
            "distances": [[0.125]],
        }


class LocalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.records_path = self.root / "records.jsonl"
        self.status_path = self.root / "status.json"
        self.record = {
            "_id": "test-a", "chunk_text": "自动化测试证据，不能用于工程判定。",
            "evidence_kind": "standard", "standard_code": "TEST-2026",
            "standard_name": "测试规范", "standard_version": "TEST-2026",
            "clause": "1.2.3", "source_location": "测试来源#test-a",
            "applicability": ["仅测试"], "effective_status": "active",
        }
        self.records_path.write_text(json.dumps(self.record), encoding="utf-8")
        self.write_status("active")
        self.collection = CollectionFixture()
        self.service = LocalEvidenceService(
            self.collection, self.records_path, self.status_path,
        )

    def write_status(self, status):
        self.status_path.write_text(json.dumps({
            "schema_version": "excavaguard.standard_status/v1",
            "reviewed_at": "2026-10-13T00:00:00Z", "reviewed_by": "test",
            "standards": {"TEST-2026": {"effective_status": status}},
        }), encoding="utf-8")

    def client(self):
        return patch.object(server, "load_evidence_service", return_value=self.service)

    def test_post_defaults_and_evidence_metadata(self):
        with self.client(), TestClient(server.app) as client:
            response = client.post("/api/evidence/search", json={"query": "测试规范"})
            self.assertEqual(response.status_code, 200)
            evidence = response.json()["evidence"][0]
            self.assertEqual(set(evidence), {"id", "text", "metadata", "score", "matched_terms"})
            self.assertEqual(evidence["id"], "test-a")
            self.assertEqual(evidence["score"], 0.875)
            self.assertNotIn("monitoring_item", evidence["metadata"])
            self.assertEqual(evidence["metadata"]["effective_status"], "active")
        self.assertEqual(self.collection.calls[0]["ids"], ["test-a"])
        self.assertEqual(self.collection.calls[0]["n_results"], 1)

    def test_invalid_query_limit_and_types(self):
        for request in (
            {"query": " "}, {"query": "x", "top_k": 11},
            {"query": "x", "top_k": "3"}, {"query": "x", "top_k": True},
            {"query": "x", "filters": {"unknown": "value"}},
            {"query": "x", "filters": {"standard_versions": None}},
        ):
            with self.subTest(request=request):
                with self.assertRaises(ValidationError):
                    EvidenceQuery.model_validate(request)
        with self.client(), TestClient(server.app) as client:
            self.assertEqual(client.post(
                "/api/evidence/search", json={"query": "", "top_k": 0},
            ).status_code, 422)

    def test_version_filter_before_vector_query(self):
        result = self.service.search(EvidenceQuery(
            query="test", filters={"standard_versions": ["TEST-OTHER"]},
        ))
        self.assertEqual(result.evidence, [])
        self.assertEqual(self.collection.calls, [])

    def test_missing_applicability_filter_returns_no_hit(self):
        for key in ("monitoring_item", "excavation_safety_level", "region"):
            with self.subTest(key=key):
                self.assertEqual(self.service.search(EvidenceQuery(
                    query="test", filters={key: "未登记条件"},
                )).evidence, [])
        self.assertEqual(self.collection.calls, [])

    def test_status_revocation_without_restart(self):
        self.write_status("inactive")
        self.assertEqual(self.service.search(EvidenceQuery(query="x")).evidence, [])
        result = self.service.search(EvidenceQuery(
            query="x", filters={"effective_status": "inactive"},
        ))
        self.assertEqual(result.evidence[0].metadata.effective_status, "inactive")

    def test_text_mismatch_is_sanitized_failure(self):
        self.collection.document = "test-private-canary"
        with self.client(), TestClient(server.app) as client:
            response = client.post("/api/evidence/search", json={"query": "x"})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("test-private-canary", response.text)
            self.assertNotIn(str(self.root), response.text)
            self.assertEqual(response.json()["error"]["code"], "QUERY_FAILED")

    def test_initialization_failure_explicitly_unavailable(self):
        with patch.object(server, "load_evidence_service", side_effect=RuntimeError("private-canary")):
            with TestClient(server.app) as client:
                self.assertEqual(client.get("/api/evidence/health").status_code, 503)
                response = client.post("/api/evidence/search", json={"query": "x"})
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("private-canary", response.text)

    def test_existing_model_vectors_only_and_runtime_baseline_isolation(self):
        baseline = self.root / "data/chroma_db"
        baseline.mkdir(parents=True)
        (baseline / "chroma.sqlite3").write_bytes(b"baseline-fixture")
        with patch.object(query_kb, "ROOT", self.root), patch.object(query_kb, "DB_DIR", baseline):
            runtime = query_kb.runtime_database_dir()
            self.assertNotEqual(runtime, baseline)
            self.assertEqual((runtime / "chroma.sqlite3").read_bytes(), b"baseline-fixture")
            (runtime / "chroma.sqlite3").write_bytes(b"runtime-only-write")
            self.assertEqual(query_kb.runtime_database_dir(), runtime)
            self.assertEqual((baseline / "chroma.sqlite3").read_bytes(), b"baseline-fixture")


if __name__ == "__main__":
    unittest.main()
