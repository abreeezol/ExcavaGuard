# -*- coding: utf-8 -*-
"""
ocr_extract.py — Specification PDF text extraction (direct text-layer read + OCR for scans).

Strategy:
  - PDFs with a real text layer: extract directly via PyMuPDF (fast).
  - Scanned PDFs: render each page at 150dpi -> RapidOCR (Chinese OCR).
  - Multi-process parallelism (sharded by file), resumable: existing complete
    outputs are skipped.

Output: data/ocr_text/<category>/<filename>.txt
Usage: python source/ocr_extract.py [--workers 8] [--dpi 150] [--force-ocr]
"""
import argparse
import os
import sys
import time
from multiprocessing import get_context
from pathlib import Path

# Critical: cap per-process thread counts to avoid N-process x 32-thread
# oversubscription, which can cause livelock on CPU-quota-limited sandboxes.
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "data" / "docs"
OUT_DIR = ROOT / "data" / "ocr_text"
# Pages whose average extracted character count falls below this threshold are
# treated as scanned / fake-text-layer PDFs (many PDFs only embed headers and
# watermarks as text; the body is an image). Chinese spec body pages typically
# hold 400-900 chars, so 150 is a safe lower bound.
TEXT_LAYER_MIN_CHARS = 150


def has_text_layer(doc, sample_pages=6) -> bool:
    n = doc.page_count
    idxs = sorted(set([n // 4, n // 2, 3 * n // 4, n - 2, 1, n // 3][:sample_pages]))
    total = sum(len(doc[i].get_text().strip()) for i in idxs if 0 <= i < n)
    return total / max(len(idxs), 1) >= TEXT_LAYER_MIN_CHARS


def extract_one(args):
    pdf_path_str, out_path_str, dpi, force_ocr = args
    pdf_path, out_path = Path(pdf_path_str), Path(out_path_str)
    name = pdf_path.name
    if out_path.exists() and out_path.stat().st_size > 500:
        return f"[skip] {name} (already exists)"
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        t0 = time.time()
        if not force_ocr and has_text_layer(doc):
            text = "\n".join(doc[i].get_text() for i in range(doc.page_count))
            mode = "text-layer"
        else:
            from rapidocr_onnxruntime import RapidOCR
            try:
                ocr = RapidOCR(intra_op_num_threads=4)
            except TypeError:
                ocr = RapidOCR()
            pages_text = []
            for i in range(doc.page_count):
                pix = doc[i].get_pixmap(dpi=dpi)
                result, _ = ocr(pix.tobytes("png"))
                page_text = "\n".join(line[1] for line in result) if result else ""
                pages_text.append(f"[[page {i+1}]]\n{page_text}")
            text = "\n".join(pages_text)
            mode = "OCR"
        doc.close()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.rename(out_path)
        dt = time.time() - t0
        return f"[done] {name} | {mode} | {len(text)} chars | {dt:.0f}s"
    except Exception as e:  # noqa
        return f"[fail] {name} | {type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--force-ocr", action="store_true",
                    help="Skip text-layer detection and OCR everything "
                         "(use to redo fake-text-layer files).")
    args = ap.parse_args()

    pdfs = sorted(DOCS_DIR.rglob("*.pdf"))
    if not pdfs:
        sys.exit("No PDF files under data/docs")
    tasks = []
    for p in pdfs:
        rel = p.relative_to(DOCS_DIR)
        out = (OUT_DIR / rel).with_suffix(".txt")
        tasks.append((str(p), str(out), args.dpi, args.force_ocr))
    print(f"{len(tasks)} PDFs, {args.workers} parallel workers...", flush=True)
    # spawn context: avoids fork + onnxruntime thread deadlock
    with get_context("spawn").Pool(args.workers) as pool:
        for msg in pool.imap_unordered(extract_one, tasks):
            print(msg, flush=True)
    done = len(list(OUT_DIR.rglob("*.txt")))
    print(f"\nExtraction finished: {done}/{len(tasks)} texts written to {OUT_DIR}")


if __name__ == "__main__":
    main()
