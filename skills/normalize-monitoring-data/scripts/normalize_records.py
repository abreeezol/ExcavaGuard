#!/usr/bin/env python3
"""Generic compatibility entrypoint; professional implementation belongs to the adapter."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "source" / "adapter_runtime"))
from dispatch import execute
if __name__ == "__main__":
    execute("normalize-monitoring-data", "normalize_records.py")
