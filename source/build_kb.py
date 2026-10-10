# -*- coding: utf-8 -*-
"""
build_kb.py — RAG knowledge-base builder for the excavation-guard project (training entry).

Pipeline:
  1. Read specification texts from data/ocr_text/ (produced by ocr_extract.py);
     also accepts .md/.txt/.docx files placed directly under data/docs.
  2. Split into chunks by clause structure + semantic length, keeping metadata
     such as clause id / source file / category.
  3. Embed with the local bge-small-zh model.
  4. Persist into ChromaDB (data/chroma_db/) and export data/chunks.jsonl.

Usage:
  python source/build_kb.py              # full build (incremental by default)
  python source/build_kb.py --rebuild    # wipe and rebuild (after spec files change)

Migration note:
  chroma_db is a plain file-based database. Copying the whole jikeng-rag folder
  completes migration — no retraining required.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")

ROOT = Path(__file__).resolve().parent.parent
OCR_DIR = ROOT / "data" / "ocr_text"
DOCS_DIR = ROOT / "data" / "docs"
DB_DIR = ROOT / "data" / "chroma_db"
CHUNKS_PATH = ROOT / "data" / "chunks.jsonl"
MODEL_DIR = ROOT / "models" / "bge-small-zh"
MODEL_NAME = "BAAI/bge-small-zh"
COLLECTION = "jikeng_norms"

MAX_CHUNK = 420
MIN_CHUNK = 30

# ------------------------------------------------------------ Clause-level splitting
CLAUSE_START = re.compile(
    r"^(\d+\.\d+(?:\.\d+)?[\s　]|"        # numbered clause, e.g. "8.2.1 "
    r"\d+\.\d+(?:\.\d+)?[\u4e00-\u9fff]|" # OCR-joined form, e.g. "8.2.1支护"
    r"第[一二三四五六七八九十百\d]+[章节条]|"          # chapter/section/article header
    r"[（(]\d+[）)]|"                                # item "(1)"
    r"\d+[、])"                                      # item "1、"
)
HEADING = re.compile(r"^(第[一二三四五六七八九十百\d]+章|附录[A-ZＡ-Ｚ]?)")

def norm_text(t: str) -> str:
    t = t.replace("\u3000", " ").replace("〖第", "\n〖第")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t

def split_clauses(text: str):
    """Split on clause-starting lines; drop page-marker lines."""
    blocks, buf = [], []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("〖第") or ln.startswith("[[page"):
            continue
        if CLAUSE_START.match(ln) and buf:
            blocks.append("".join(buf) if len(" ".join(buf)) < 120 else " ".join(buf))
            buf = [ln]
        else:
            buf.append(ln)
    if buf:
        blocks.append(" ".join(buf))
    return blocks

def resize_blocks(blocks):
    """Re-split oversized blocks on sentence ends; merge undersized ones forward."""
    out = []
    for blk in blocks:
        if len(blk) > MAX_CHUNK:
            parts = re.split(r"(?<=[。；;])", blk)
            cur = ""
            for s in parts:
                if len(cur) + len(s) > MAX_CHUNK and cur:
                    out.append(cur)
                    cur = s
                else:
                    cur += s
            if cur:
                out.append(cur)
        else:
            out.append(blk)
    merged = []
    for blk in out:
        if merged and len(blk) < MIN_CHUNK and len(merged[-1]) + len(blk) <= MAX_CHUNK:
            merged[-1] += " " + blk
        else:
            merged.append(blk)
    return [b for b in merged if len(b) >= 12]

def clause_id_of(blk: str) -> str:
    m = re.match(r"^(\d+\.\d+(?:\.\d+)?)", blk)
    if m:
        return m.group(1)
    m = re.match(r"^(第[一二三四五六七八九十百\d]+[章节条])", blk)
    return m.group(1) if m else ""

# ------------------------------------------------------------ Model and vector store
def get_embedding_fn():
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    model_path = str(MODEL_DIR) if (MODEL_DIR / "config.json").exists() else MODEL_NAME
    print(f"Embedding model: {model_path}")
    return SentenceTransformerEmbeddingFunction(
        model_name=model_path, device="cpu"
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    # 1. Collect corpus: prefer ocr_text, then md/txt/docx under docs
    corpus = []  # (category, filename, text)
    for txt in sorted(OCR_DIR.rglob("*.txt")):
        rel = txt.relative_to(OCR_DIR)
        category = rel.parts[0] if len(rel.parts) > 1 else "uncategorized"
        corpus.append((category, txt.stem, txt.read_text(encoding="utf-8", errors="ignore")))
    for p in sorted(DOCS_DIR.rglob("*")):
        if p.suffix.lower() not in (".md", ".txt", ".docx"):
            continue
        rel = p.relative_to(DOCS_DIR)
        category = rel.parts[0] if len(rel.parts) > 1 else "project-files"
        if p.suffix.lower() == ".docx":
            import docx
            d = docx.Document(str(p))
            text = "\n".join(x.text for x in d.paragraphs)
        else:
            text = p.read_text(encoding="utf-8", errors="ignore")
        corpus.append((category, p.stem, text))
    if not corpus:
        sys.exit("No corpus found: run ocr_extract.py first or place text files under data/docs")
    print(f"Corpus files: {len(corpus)}")

    # 2. Chunking
    all_chunks = []
    for category, fname, text in corpus:
        blocks = resize_blocks(split_clauses(norm_text(text)))
        for i, blk in enumerate(blocks):
            cid = clause_id_of(blk)
            all_chunks.append({
                "id": hashlib.md5(f"{fname}|{i}|{blk[:40]}".encode()).hexdigest(),
                "content": blk,
                "source": fname,
                "category": category,
                "clause": cid,
            })
        print(f"  {fname}: {len(blocks)} chunks")
    print(f"Total chunks: {len(all_chunks)}")

    CHUNKS_PATH.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in all_chunks),
        encoding="utf-8",
    )

    # 3. Build the vector store
    import chromadb
    client = chromadb.PersistentClient(path=str(DB_DIR))
    if args.rebuild:
        try:
            client.delete_collection(COLLECTION)
            print("Old collection wiped")
        except Exception:
            pass
    coll = client.get_or_create_collection(
        name=COLLECTION,
        embedding_function=get_embedding_fn(),
        metadata={"hnsw:space": "cosine"},
    )

    BATCH = 128
    existing = set()
    if not args.rebuild and coll.count() > 0:
        got = coll.get(include=[])
        existing = set(got["ids"])
    todo = [c for c in all_chunks if c["id"] not in existing]
    print(f"To write: {len(todo)} chunks (skipping {len(all_chunks)-len(todo)} existing)")
    for s in range(0, len(todo), BATCH):
        batch = todo[s:s + BATCH]
        coll.add(
            ids=[c["id"] for c in batch],
            documents=[c["content"] for c in batch],
            metadatas=[{"source": c["source"], "category": c["category"], "clause": c["clause"]} for c in batch],
        )
        print(f"  wrote {min(s+BATCH, len(todo))}/{len(todo)}", flush=True)
    print(f"Done! {coll.count()} chunks in vector store -> {DB_DIR}")


if __name__ == "__main__":
    main()
