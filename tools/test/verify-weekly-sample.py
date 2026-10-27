"""Verify the published synthetic weekly sample offline; never calls an external model."""
import hashlib
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "final_test/latest"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def call(skill, script, request):
    process = subprocess.run([sys.executable, str(ROOT / "skills" / skill / "scripts" / script)],
                             input=json.dumps(request, ensure_ascii=False), text=True,
                             capture_output=True, cwd=ROOT, check=True)
    envelope = json.loads(process.stdout)
    assert envelope.get("ok"), envelope.get("error")
    return envelope["result"]


def workbook_values(path):
    workbook = load_workbook(path)
    try:
        return [(sheet.title, [(cell.coordinate, cell.value,
                 cell.hyperlink.target if cell.hyperlink else None)
                for row in sheet for cell in row if cell.value is not None or cell.hyperlink])
                for sheet in workbook]
    finally:
        workbook.close()


def main():
    for entry in read(SAMPLE / "validation/files.sha256.json")["files"]:
        path = (SAMPLE / entry["path"]).resolve()
        assert path.is_relative_to(SAMPLE.resolve())
        assert path.stat().st_size == entry["size_bytes"], entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], entry["path"]
    request = read(SAMPLE / "inputs/weekly_engine_request.json")
    assert all(r["data_origin"] == "simulated" for r in request["records"])
    with (SAMPLE / "inputs/weekly_simulated.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = [{**row, "value": float(row["value"])} for row in csv.DictReader(stream)]
    assert rows == request["records"], "CSV and JSON inputs differ"
    payload = call("evaluate-thresholds", "run_judgement.py", request)
    # Source-file locations vary by checkout; publish repository-relative metadata.
    for source in payload.get("standards_sources", []):
        path = source.get("path")
        if path and Path(path).is_absolute():
            source["path"] = Path(path).relative_to(ROOT).as_posix()
    assert payload == read(SAMPLE / "snapshots/weekly_engine_payload.json")
    uid = str(uuid4())
    staging = ROOT / "var/report-artifacts" / uid
    try:
        render_request = {
            "daily_report_input": payload,
            "standard_evidence": read(SAMPLE / "snapshots/weekly_evidence.json"),
            "work_condition_analysis": read(SAMPLE / "snapshots/weekly_analysis.json"),
            "artifact_id": uid, "artifact_output_dir": str(staging),
        }
        rendered = call("render-daily-report", "render_daily_report.py", render_request)
        audit = call("validate-report", "validate_report.py", {
            **render_request, **{key: rendered[key] for key in
            ("report_payload", "template_version", "fact_bindings", "artifacts", "artifact_bindings", "citations")},
        })
        assert audit["valid"], audit["issues"]
        for artifact in rendered["artifacts"]:
            actual = ROOT / artifact["relative_path"]
            published = SAMPLE / "reports/weekly" / artifact["file_name"]
            if artifact["kind"] == "workbook":
                assert workbook_values(actual) == workbook_values(published), "Workbook differs from published sample"
            else:
                assert actual.read_text(encoding="utf-8") == published.read_text(encoding="utf-8"), artifact["file_name"]
        print("PASS: hashes, synthetic inputs, frozen facts, workbook cells/links, Markdown and report audit; no external calls.")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    main()
