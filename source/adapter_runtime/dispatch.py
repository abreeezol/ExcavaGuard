"""Compatibility entrypoints. Only developer-installed adapter handlers are executable."""
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]


def manifest(adapter_id="foundation-pit"):
    if not isinstance(adapter_id, str) or not adapter_id or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in adapter_id):
        raise ValueError("ENGINEERING_ADAPTER_UNSUPPORTED")
    path = (ROOT / "engineering-adapters" / adapter_id / "manifest.json").resolve()
    path.relative_to(ROOT / "engineering-adapters")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["id"] != adapter_id or (data["status"] == "test_only" and os.environ.get("NODE_ENV") != "test"):
        raise ValueError("ENGINEERING_ADAPTER_UNSUPPORTED")
    return data


def path_for(path):
    result = (ROOT / path).resolve()
    result.relative_to(ROOT)
    return result


def execute(skill, file):
    raw = sys.stdin.read()
    try:
        request = json.loads(raw)
        payload = request.get("daily_report_input") or {}
        snapshot = (payload.get("project") or {}).get("engineering_adapter") or {}
        adapter_id = request.get("_adapter_id") or snapshot.get("id") or "foundation-pit"
        config = manifest(adapter_id)
        target = path_for(config["handlers"][skill + "/" + file])
        sys.path.insert(0, str(target.parent))
        sys.stdin = io.StringIO(raw)
        runpy.run_path(str(target), run_name="__main__")
    except (ValueError, KeyError, OSError) as error:
        print(json.dumps({"ok": False, "error": {"code": "ADAPTER_INVALID", "message": str(error)}}))
        raise SystemExit(2)


def import_legacy_module(name):
    # Imported by legacy test/tools only; runtime runners dispatch using registered handlers.
    target = ROOT / "engineering-adapters" / "foundation-pit" / "runtime" / (name + ".py")
    sys.path.insert(0, str(target.parent))
    spec = importlib.util.spec_from_file_location("pit_compat_" + name, target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return vars(module)
