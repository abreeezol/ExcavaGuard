"""Explicitly generate the current pit template sample; preserve all historical samples."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("weekly_verifier", ROOT / "tools/test/verify-weekly-sample.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
DEST = ROOT / "final_test/pit-weekly"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    historical = ROOT / "final_test/latest"
    for folder in ("inputs", "snapshots", "reports/weekly", "validation"):
        (DEST / folder).mkdir(parents=True, exist_ok=True)
    for name in ("weekly_simulated.csv", "weekly_engine_request.json"):
        shutil.copyfile(historical / "inputs" / name, DEST / "inputs" / name)
    payload = verifier.call("evaluate-thresholds", "run_judgement.py", verifier.read(DEST / "inputs/weekly_engine_request.json"))
    for source in payload.get("standards_sources", []):
        path = source.get("path")
        if path and Path(path).is_absolute():
            source["path"] = Path(path).relative_to(ROOT).as_posix()
    write(DEST / "snapshots/weekly_engine_payload.json", payload)
    # Frozen historical evidence supports offline reproduction, not a new retrieval or live audit.
    evidence = verifier.read(historical / "snapshots/weekly_evidence.json")
    write(DEST / "snapshots/weekly_evidence.json", evidence)
    write(DEST / "snapshots/weekly_analysis.json", None)
    uid = str(uuid4())
    staging = ROOT / "var/report-artifacts" / uid
    try:
        request = {"daily_report_input": payload, "standard_evidence": evidence,
                   "work_condition_analysis": None, "artifact_id": uid, "artifact_output_dir": str(staging)}
        rendered = verifier.call("render-daily-report", "render_daily_report.py", request)
        audit = verifier.call("validate-report", "validate_report.py", {
            **request, **{key: rendered[key] for key in
                         ("report_payload", "template_version", "fact_bindings", "artifacts", "artifact_bindings", "citations")}})
        assert audit["valid"], audit["issues"]
        for artifact in rendered["artifacts"]:
            shutil.copyfile(ROOT / artifact["relative_path"], DEST / "reports/weekly" / artifact["file_name"])
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    paths = sorted(path for folder in ("inputs", "snapshots", "reports") for path in (DEST / folder).rglob("*") if path.is_file())
    write(DEST / "validation/files.sha256.json", {"files": [
        {"path": path.relative_to(DEST).as_posix(), "size_bytes": path.stat().st_size,
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths]})
    print("Generated current pit template sample; run verify-weekly-sample.py for independent expected values and file checks.")


if __name__ == "__main__":
    main()
