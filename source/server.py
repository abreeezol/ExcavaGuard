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
  /api/stats   GET  -> knowledge-base statistics
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import report_core

app = FastAPI(title="Excavation Guard RAG Demo")


class CheckReq(BaseModel):
    description: str
    meta: dict = {}


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


if __name__ == "__main__":
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8600)
    args = ap.parse_args()
    uvicorn.run(app, host="0.0.0.0", port=args.port)
