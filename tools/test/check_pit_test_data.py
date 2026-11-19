"""Check the published pit sample and 27 synthetic engine scenarios without external services."""
import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
subprocess.run([sys.executable, str(ROOT / "tools/test/verify-weekly-sample.py")], cwd=ROOT, check=True)
path = ROOT / "确定性计算层/tools/run_simulated_validation.py"
spec = importlib.util.spec_from_file_location("pit_scenarios_check", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.DERIVED = ROOT / "var/acceptance/pit-data/scenarios"
raise SystemExit(module.main())
