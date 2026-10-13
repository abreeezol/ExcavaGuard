# -*- coding: utf-8 -*-
"""
query_kb.py — Knowledge-base retrieval CLI (interactive command-line version).

Usage:
  python source/query_kb.py "基坑顶部水平位移报警值是多少"
  python source/query_kb.py "监测日报应包括哪些内容" --topk 5
"""
import argparse
import json
import os
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "data" / "chroma_db"
MODEL_DIR = ROOT / "models" / "bge-small-zh"
MODEL_NAME = "BAAI/bge-small-zh"
COLLECTION = "jikeng_norms"


def runtime_database_dir() -> Path:
    """Copy the release baseline once; never open it with PersistentClient."""
    runtime = ROOT / "var" / "rag" / "chroma_db"
    if (runtime / "chroma.sqlite3").is_file():
        return runtime
    if runtime.exists() or not (DB_DIR / "chroma.sqlite3").is_file():
        raise RuntimeError("本地向量库运行副本不完整或发布基线缺失。")
    runtime.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="chroma-copy-", dir=runtime.parent))
    try:
        shutil.copytree(DB_DIR, staging / "database")
        try:
            (staging / "database").rename(runtime)
        except OSError:
            if not (runtime / "chroma.sqlite3").is_file():
                raise
    finally:
        shutil.rmtree(staging)
    return runtime


@lru_cache(maxsize=1)
def get_collection():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    if (
        not (MODEL_DIR / "config.json").is_file()
        or not (MODEL_DIR / "pytorch_model.bin").is_file()
        or (MODEL_DIR / "pytorch_model.bin").stat().st_size != 95_842_633
    ):
        raise RuntimeError("本地 BGE 模型缺失或仍为 Git LFS 指针。")
    ef = SentenceTransformerEmbeddingFunction(
        model_name=str(MODEL_DIR), device="cpu", local_files_only=True,
    )
    client = chromadb.PersistentClient(path=str(runtime_database_dir()))
    return client.get_collection(name=COLLECTION, embedding_function=ef)


def search(query: str, topk: int = 5):
    coll = get_collection()
    # bge-family models recommend an instruction prefix for retrieval queries
    q = "为这个句子生成表示以用于检索相关文章：" + query
    res = coll.query(query_texts=[q], n_results=topk)
    hits = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        hits.append({
            "score": round(1 - dist, 4),
            "source": meta.get("source", ""),
            "category": meta.get("category", ""),
            "clause": meta.get("clause", ""),
            "content": doc,
        })
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    hits = search(args.query, args.topk)
    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return
    print(f"\nQuery: {args.query}\n" + "=" * 60)
    for i, h in enumerate(hits, 1):
        print(f"\n[{i}] score {h['score']:.3f} | {h['source']} | clause {h['clause'] or '-'}")
        print("-" * 60)
        print(h["content"][:500])


if __name__ == "__main__":
    main()
