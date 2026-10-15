# -*- coding: utf-8 -*-
"""
server.py — Interactive demo service (fully offline).

Start:
  python source/server.py [--port 8600]
Then open http://localhost:8600 in a browser.

Endpoints:
  /            Interactive page (description input -> compliance check -> report)
  /api/check   POST {description, meta} -> parse + check + daily report
  /api/search  GET  ?q=... -> knowledge-base clause retrieval
  /api/evidence/search POST {query, filters, top_k} -> unified evidence
  /api/stats   GET  -> knowledge-base statistics
"""
import argparse
import asyncio
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import report_core
from evidence_api import EvidenceQuery, EvidenceResponse, LocalEvidenceService
from query_kb import get_collection


def load_evidence_service():
    # Reuse the existing audited manifest builder; it makes no network calls.
    subprocess.run(
        [
            "node", "--input-type=module", "-e",
            "import {preparePineconeImport} from './tools/rag/standard-records.ts';"
            "preparePineconeImport();",
        ],
        cwd=ROOT, check=True, capture_output=True, timeout=30,
    )
    return LocalEvidenceService(get_collection())


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.evidence_service = None
    try:
        application.state.evidence_service = await asyncio.to_thread(load_evidence_service)
    except Exception:
        # Keep a safe, explicit unavailable status without exposing paths or input.
        print("本地证据服务初始化失败，请检查模型、知识资产与 Node/Python 依赖。", file=sys.stderr)
    yield


app = FastAPI(title="ExcavaGuard Local RAG", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, _error: RequestValidationError):
    # FastAPI's default validation body includes raw input; never echo it.
    return JSONResponse(
        {"error": {"code": "INVALID_QUERY", "message": "检索或原型请求参数不合法。"}},
        status_code=422,
    )


class CheckReq(BaseModel):
    description: str
    meta: dict = {}


@app.post("/api/evidence/search", response_model=EvidenceResponse, response_model_exclude_none=True)
def evidence_search(req: EvidenceQuery):
    service = getattr(app.state, "evidence_service", None)
    if service is None:
        return JSONResponse(
            {"error": {"code": "RETRIEVER_UNAVAILABLE", "message": "本地规范证据服务未就绪。"}},
            status_code=503,
        )
    try:
        return service.search(req)
    except Exception:
        return JSONResponse(
            {"error": {"code": "QUERY_FAILED", "message": "本地规范证据检索失败。"}},
            status_code=503,
        )


@app.get("/api/evidence/health")
def evidence_health():
    ready = getattr(app.state, "evidence_service", None) is not None
    return JSONResponse({"ready": ready}, status_code=200 if ready else 503)


@app.get("/")
def index():
    return FileResponse(str(ROOT / "demo" / "index.html"))


@app.post("/api/check")
def check(req: CheckReq):
    try:
        out = report_core.run_pipeline(req.description, req.meta or {})
        return JSONResponse(out)
    except Exception as e:  # noqa
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.get("/api/search")
def search(q: str, topk: int = 5):
    return {"hits": report_core.kb_search(q, topk)}


@app.get("/api/stats")
def stats():
    try:
        coll = report_core._get_coll()
        count = coll.count()
    except Exception:
        count = 0
    docs = sorted(p.name for p in (ROOT / "data" / "ocr_text").rglob("*.txt")) if (ROOT / "data" / "ocr_text").exists() else []
    return {"chunks": count, "docs": docs, "doc_count": len(docs)}


@app.get("/api/port")
def port_info():
    """Report the port this process actually bound.

    Lets launcher scripts discover the real URL after auto-avoidance, so the
    local deployment link stays stable across machines.
    """
    bound = getattr(app.state, "bound_port", None)
    return {"port": bound, "url": f"http://127.0.0.1:{bound}" if bound else None}


if __name__ == "__main__":
    import socket
    import uvicorn

    def port_is_free(port: int) -> bool:
        """True only if we can actually bind 127.0.0.1:port.

        Uses a real bind rather than a TCP connect probe, so it also rejects
        ports in the Windows reserved/excluded ranges (WinError 10013), which
        is the usual reason 8600 fails on Windows machines.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                return False
        return True

    def pick_port(preferred: int, span: int = 200) -> int:
        """Return the preferred port if usable, else scan upward for a free one."""
        if port_is_free(preferred):
            return preferred
        for candidate in range(preferred + 1, preferred + span + 1):
            if port_is_free(candidate):
                return candidate
        raise SystemExit(
            f"未找到可用端口（已尝试 {preferred}-{preferred + span}）。"
            "请用 --port 手动指定一个不在系统保留段内的端口。"
        )

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--port",
        type=int,
        default=8600,
        help="首选端口；被占用或落在系统保留段时自动向后寻找可用端口。",
    )
    ap.add_argument(
        "--no-auto-port",
        action="store_true",
        help="禁用端口自动避让，端口不可用则直接失败。",
    )
    args = ap.parse_args()

    if args.no_auto_port:
        port = args.port
    else:
        port = pick_port(args.port)
        if port != args.port:
            print(
                f"[提示] 端口 {args.port} 不可用（被占用或属系统保留段），"
                f"已自动改用 {port}。",
                file=sys.stderr,
            )

    url = f"http://127.0.0.1:{port}"
    app.state.bound_port = port
    print(f"\n  ExcavaGuard 本地 Demo 已启动")
    print(f"  请在浏览器打开： {url}\n", file=sys.stderr)

    uvicorn.run(app, host="127.0.0.1", port=port)
