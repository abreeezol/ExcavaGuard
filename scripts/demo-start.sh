#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"

usage() {
  cat <<'EOF'
Usage: scripts/demo-start.sh [options]

Options:
  --force-env       Overwrite an existing .env.local when decrypting.
  --skip-decrypt    Do not decrypt .env.local.enc.
  --skip-npm-ci     Do not run npm ci.
  --no-start        Prepare dependencies only; do not start npm run dev.
  --full-python     Install requirements.txt into .venv instead of only openpyxl.
  -h, --help        Show this help.

This script does not install global system tools. Install Node.js/npm and Python
first if they are missing.
EOF
}

FORCE_ENV=0
SKIP_DECRYPT=0
SKIP_NPM_CI=0
NO_START=0
FULL_PYTHON=0

for arg in "$@"; do
  case "${arg}" in
    --force-env) FORCE_ENV=1 ;;
    --skip-decrypt) SKIP_DECRYPT=1 ;;
    --skip-npm-ci) SKIP_NPM_CI=1 ;;
    --no-start) NO_START=1 ;;
    --full-python) FULL_PYTHON=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: ${arg}" >&2; usage >&2; exit 1 ;;
  esac
done

log() {
  printf '\n==> %s\n' "$1"
}

need_command() {
  local name="$1"
  local hint="$2"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "Missing command: ${name}" >&2
    echo "${hint}" >&2
    exit 1
  fi
}

node_version_ok() {
  local version major minor
  version="$(node -p "process.versions.node")"
  major="${version%%.*}"
  minor="$(printf '%s' "${version}" | cut -d. -f2)"

  if (( major >= 26 )); then
    return 0
  fi
  if (( major == 24 )); then
    return 0
  fi
  if (( major == 22 && minor >= 13 )); then
    return 0
  fi
  return 1
}

pick_python() {
  if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    printf '%s\n' "${ROOT_DIR}/.venv/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi
  return 1
}

log "Checking system tools"
need_command node "Install Node.js 22.13+, 24.x, or 26.x first."
need_command npm "Install npm with Node.js first."
need_command openssl "Install openssl first, or use a macOS/Linux shell that provides it."

if ! node_version_ok; then
  echo "Unsupported Node.js version: $(node -p "process.versions.node")" >&2
  echo "Required by package.json: ^22.13.0 || ^24.0.0 || >=26.0.0" >&2
  exit 1
fi

PYTHON_BIN="$(pick_python || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "Missing Python. Install Python 3 first." >&2
  exit 1
fi

echo "Node: $(node -v)"
echo "npm: $(npm -v)"
echo "Python: ${PYTHON_BIN} ($("${PYTHON_BIN}" --version 2>&1))"

if [[ "${SKIP_DECRYPT}" != "1" ]]; then
  log "Preparing .env.local"
  if [[ -f ".env.local" && "${FORCE_ENV}" != "1" ]]; then
    echo ".env.local already exists; keeping it. Use --force-env to overwrite."
  else
    if [[ "${FORCE_ENV}" == "1" ]]; then
      scripts/decrypt-env-local.sh --force
    else
      scripts/decrypt-env-local.sh
    fi
  fi
fi

if [[ "${SKIP_NPM_CI}" != "1" ]]; then
  log "Installing Node dependencies"
  npm ci
fi

log "Preparing Python runtime"
if [[ ! -d ".venv" ]]; then
  "${PYTHON_BIN}" -m venv .venv
fi

VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"
"${VENV_PYTHON}" -m pip install --upgrade pip

if [[ "${FULL_PYTHON}" == "1" ]]; then
  "${VENV_PYTHON}" -m pip install -r requirements.txt
else
  "${VENV_PYTHON}" - <<'PY' >/dev/null 2>&1 || "${VENV_PYTHON}" -m pip install 'openpyxl>=3.1,<4'
import openpyxl
PY
fi

log "Checking demo env"
if [[ ! -f ".env.local" ]]; then
  echo "Missing .env.local. Online Supabase/Pinecone/LLM demo will not work." >&2
  echo "Run scripts/decrypt-env-local.sh or re-run this script without --skip-decrypt." >&2
  exit 1
fi

if [[ "${NO_START}" == "1" ]]; then
  log "Demo environment is ready"
  exit 0
fi

log "Starting ExcavaGuard"
echo "Open http://localhost:3000/workbench after the server starts."
exec npm run dev
