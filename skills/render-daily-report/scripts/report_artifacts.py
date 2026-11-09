"""Backward compatible import for existing pit tools; not an adapter selection API."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "source" / "adapter_runtime"))
from dispatch import import_legacy_module
_values = import_legacy_module("report_artifacts")
globals().update({key: value for key, value in _values.items() if key not in ("__name__", "__file__", "__spec__", "__loader__")})
