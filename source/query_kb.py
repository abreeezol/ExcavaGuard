# -*- coding: utf-8 -*-
"""
query_kb.py — Knowledge-base retrieval CLI (interactive command-line version).

Usage:
  python source/query_kb.py "基坑顶部水平位移报警值是多少"
  python source/query_kb.py "监测日报应包括哪些内容" --topk 5
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "data" / "chroma_db"
MODEL_DIR = ROOT / "models" / "bge-small-zh"
MODEL_NAME = "BAAI/bge-small-zh"
COLLECTION = "jikeng_norms"


def get_collection():
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    model_path = str(MODEL_DIR) if (MODEL_DIR / "config.json").exists() else MODEL_NAME
    ef = SentenceTransformerEmbeddingFunction(model_name=model_path, device="cpu")
    client = chromadb.PersistentClient(path=str(DB_DIR))
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
