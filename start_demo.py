#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
start_demo.py — Cross-platform launcher for the ExcavaGuard local demo.

Why this exists
---------------
The demo's port cannot be hard-coded: 8600 is widely blocked on Windows
(it lands in a Hyper-V/WSL/Docker reserved range that shifts between machines
and across reboots), and any fixed port may already be in use.

This script therefore:
  1. Finds the project's own virtualenv (or falls back to the current Python).
  2. Asks the server for a free port (auto-avoiding reserved/occupied ports).
  3. Prints the exact local URL for THIS machine.
  4. Optionally opens the browser.

Usage
-----
    python start_demo.py                  # auto-detect port, print URL
    python start_demo.py --open           # also open the browser
    python start_demo.py --port 9000      # prefer 9000 (still auto-avoids)
    python start_demo.py --check-only     # just print the URL and exit

The printed URL is stable in form (http://127.0.0.1:<port>) while the port
itself adapts per machine, so the installation steps stay identical everywhere.
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WINDOWS = os.name == "nt"


def venv_python() -> Path | None:
    """Locate the project's .venv interpreter, if present."""
    rel = (".venv", "Scripts", "python.exe") if IS_WINDOWS else (".venv", "bin", "python")
    candidate = ROOT.joinpath(*rel)
    return candidate if candidate.is_file() else None


def resolve_python() -> str:
    """Pick the interpreter to run the server with."""
    venv = venv_python()
    if venv is not None:
        return str(venv)
    print(
        "[警告] 未找到项目虚拟环境 .venv，将使用当前解释器。\n"
        "        若启动失败，请先按 DEPLOY.md 创建 .venv 并安装依赖。",
        file=sys.stderr,
    )
    return sys.executable


def which_python_for_import_check() -> str:
    return resolve_python()


def port_is_free(port: int) -> bool:
    """True only if 127.0.0.1:port can actually be bound.

    A real bind (not a connect probe) is required: Windows reserved ranges
    reject binding with WinError 10013 while still refusing connections,
    and this is exactly the failure mode seen with 8600.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def pick_port(preferred: int, span: int = 200) -> int:
    if port_is_free(preferred):
        return preferred
    for candidate in range(preferred + 1, preferred + span + 1):
        if port_is_free(candidate):
            return candidate
    raise SystemExit(
        f"未找到可用端口（已尝试 {preferred}-{preferred + span}）。"
        "请用 --port 手动指定一个不在系统保留段内的端口。"
    )


def check_dependencies(python: str) -> list[str]:
    """Return a list of missing Python packages required by the demo."""
    required = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "pydantic": "pydantic",
        "chromadb": "chromadb",
        "sentence_transformers": "sentence-transformers",
        "torch": "torch",
    }
    probe = ";".join(f'"{m}"' for m in required)
    code = (
        "import importlib.util as u\n"
        f"mods=[{probe}]\n"
        "print(','.join(m for m in mods if u.find_spec(m) is None))\n"
    )
    try:
        out = subprocess.run(
            [python, "-c", code], capture_output=True, text=True, timeout=60
        ).stdout.strip()
    except Exception:
        return []
    if not out:
        return []
    return [required[m] for m in out.split(",") if m in required]


def check_model_weights() -> str | None:
    """Return a warning string if the BGE weights are still an LFS pointer."""
    weight = ROOT / "models" / "bge-small-zh" / "pytorch_model.bin"
    if not weight.is_file():
        return "未找到 models/bge-small-zh/pytorch_model.bin，检索功能不可用。"
    if weight.stat().st_size != 95_842_633:
        return (
            f"模型权重大小为 {weight.stat().st_size} 字节（应为 95842633），"
            "仍是 Git LFS 指针，请执行 `git lfs pull`。检索结果会为空。"
        )
    return None


def wait_for_ready(port: int, proc: subprocess.Popen, timeout: float = 180.0) -> bool:
    """Poll /api/port until the server answers or the process dies."""
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/port"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with opener.open(url, timeout=3) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.7)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="启动 ExcavaGuard 本地 Demo")
    ap.add_argument("--port", type=int, default=8600, help="首选端口（自动避让占用与保留段）")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    ap.add_argument("--check-only", action="store_true", help="只打印可用地址后退出")
    args = ap.parse_args()

    python = resolve_python()

    missing = check_dependencies(python)
    if missing:
        print(
            "缺少 Python 依赖：" + "、".join(missing) + "\n"
            f"请先安装（Windows 示例）：\n"
            f"  .venv\\Scripts\\python.exe -m pip install "
            f"openpyxl fastapi uvicorn pydantic \"chromadb>=1.0\" torch \"sentence-transformers>=3.0\"",
            file=sys.stderr,
        )
        return 1

    warn = check_model_weights()
    if warn:
        print(f"[警告] {warn}", file=sys.stderr)

    port = pick_port(args.port)
    if port != args.port:
        print(
            f"[提示] 端口 {args.port} 不可用（被占用或属系统保留段），已自动改用 {port}。",
            file=sys.stderr,
        )

    url = f"http://127.0.0.1:{port}"

    if args.check_only:
        print(url)
        return 0

    print(f"\n  正在启动 ExcavaGuard 本地 Demo（端口 {port}）…")
    print(f"  启动完成后请在浏览器打开： {url}\n", flush=True)

    proc = subprocess.Popen(
        [python, str(ROOT / "source" / "server.py"), "--port", str(port), "--no-auto-port"],
        cwd=str(ROOT),
    )

    try:
        if wait_for_ready(port, proc):
            print(f"\n  ✅ 服务已就绪： {url}\n", flush=True)
            if args.open:
                try:
                    import webbrowser

                    webbrowser.open(url)
                except Exception:
                    pass
        else:
            print("\n  [错误] 服务未能在超时时间内就绪，请查看上方日志。\n", file=sys.stderr)
        proc.wait()
    except KeyboardInterrupt:
        print("\n  正在停止服务…")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
