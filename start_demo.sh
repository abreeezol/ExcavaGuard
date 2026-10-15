#!/usr/bin/env bash
# ExcavaGuard 本地 Demo 一键启动 (macOS / Linux)
# 端口自动探测：占用或落在保留段时自动改用可用端口
set -euo pipefail
cd "$(dirname "$0")"

PY="./.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "[错误] 未找到虚拟环境： $PY"
  echo ""
  echo "请先按 DEPLOY.md 第三章创建虚拟环境并安装依赖："
  echo "    python3 -m venv .venv"
  echo "    .venv/bin/python -m pip install --upgrade pip"
  echo "    .venv/bin/python -m pip install openpyxl fastapi uvicorn pydantic \"chromadb>=1.0\" torch \"sentence-transformers>=3.0\""
  exit 1
fi

exec "$PY" ./start_demo.py --open
