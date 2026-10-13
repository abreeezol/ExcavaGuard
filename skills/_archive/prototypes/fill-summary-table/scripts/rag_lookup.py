# -*- coding: utf-8 -*-
"""
rag_lookup.py — 规范知识库（jikeng-rag）检索桥
================================================

用途
----
供 `fill_summary_table.py --layout verdict` 调用，为「判定汇总表」的
**I 规范条文 / J 规范依据摘要** 两列补充「RAG 命中」证据。

设计原则
--------
- **可选增强**：知识库不可用时安静降级，不报错、不阻断主流程。
- **进程隔离**：本脚本作为独立子进程运行，避免把 torch / chromadb 的重量级
  依赖与全局状态带进主填表脚本。
- **一次批量**：把所有待查监测项一次性传入，只加载一次向量库。
- **结果可缓存**：命中结果写回 JSON，后续运行零依赖、零等待。

用法
----
    python rag_lookup.py --queries queries.json --out hits.json
    python rag_lookup.py --rag-dir <jikeng-rag 根目录> --queries ... --out ...

`queries.json` 形如：`["土压力", "孔隙水压力", "立柱内力"]`
`hits.json` 形如：
    {"土压力": {"ok": true, "source": "...", "clause": "表8.0.4",
                "content": "...", "score": 0.81}, ...}
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path

# 进度条 / 告警必须留在 stderr：chromadb、sentence-transformers、transformers 的
# 加载进度条默认写 stdout，会污染「结果走 stdout」的调用方（同事踩过的坑）。
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

QUERY_SUFFIX = " 监测 报警值 累计值 变化速率 基坑 监测预警值"


def find_rag_dir(explicit: str | None = None) -> Path | None:
    """按优先级定位 jikeng-rag 根目录；找不到返回 None。"""
    import os

    cands: list[Path] = []
    if explicit:
        cands.append(Path(explicit))
    env = os.environ.get("JIKENG_RAG_DIR")
    if env:
        cands.append(Path(env))
    here = Path(__file__).resolve().parent          # .../fill-summary-table/scripts
    skill_root = here.parent                        # .../fill-summary-table
    for up in (skill_root.parent, skill_root.parent.parent, skill_root.parent.parent.parent):
        cands.append(up / "jikeng-rag")
    for c in cands:
        try:
            if (c / "source" / "query_kb.py").exists() and (c / "data" / "chroma_db").exists():
                return c.resolve()
        except OSError:
            continue
    return None


def lookup(queries: list[str], rag_dir: Path, topk: int = 2) -> dict:
    sys.path.insert(0, str(rag_dir / "source"))
    out: dict[str, dict] = {}
    # 模型加载与向量检索期间的进度条/日志一律导向 stderr，保持 stdout 干净
    with contextlib.redirect_stdout(sys.stderr):
        import query_kb  # type: ignore

        for q in queries:
            try:
                hits = query_kb.search(q + QUERY_SUFFIX, topk=topk)
            except Exception as exc:  # noqa: BLE001
                out[q] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                continue
            if not hits:
                out[q] = {"ok": False, "error": "无命中"}
                continue
            h = hits[0]
            out[q] = {
                "ok": True,
                "source": h.get("source", ""),
                "category": h.get("category", ""),
                "clause": h.get("clause", "") or "",
                "content": (h.get("content") or "").strip(),
                "score": h.get("score"),
                "alternatives": [
                    {"source": x.get("source", ""), "clause": x.get("clause", "") or "",
                     "score": x.get("score")}
                    for x in hits[1:]
                ],
            }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="jikeng-rag 检索桥（可选增强）")
    ap.add_argument("--rag-dir", help="jikeng-rag 根目录（默认自动探测）")
    ap.add_argument("--queries", required=True, help="待查监测项 JSON 数组")
    ap.add_argument("--out", required=True, help="命中结果输出 JSON")
    ap.add_argument("--topk", type=int, default=2)
    args = ap.parse_args()

    queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    rag_dir = find_rag_dir(args.rag_dir)
    if rag_dir is None:
        Path(args.out).write_text(json.dumps(
            {"available": False, "reason": "未找到 jikeng-rag 知识库目录"},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print("RAG 未接入：未找到 jikeng-rag 目录", file=sys.stderr)
        return 3

    try:
        hits = lookup(queries, rag_dir, topk=args.topk)
    except Exception as exc:  # noqa: BLE001
        Path(args.out).write_text(json.dumps(
            {"available": False, "reason": f"{type(exc).__name__}: {exc}",
             "rag_dir": str(rag_dir)}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"RAG 未接入：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    Path(args.out).write_text(json.dumps(
        {"available": True, "rag_dir": str(rag_dir), "hits": hits},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"RAG 命中 {sum(1 for v in hits.values() if v.get('ok'))}/{len(queries)} 项",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
