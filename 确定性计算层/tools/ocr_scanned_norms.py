"""扫描版规范 OCR（参数化）
==========================

有些规范 PDF 是扫描件（没有文字层），只能渲染成图再 OCR。本工具把这件事做成
可重复、可审计的一步：记录引擎、DPI、页数、耗时与每页字符数，产出带页标记的文本。

为什么不能"抽不到文本就当没有要求"
----------------------------------
空语料会让下游 RAG 检索不到条文，然后被误读成"规范没有规定"。所以本工具要求
逐页字符数达标，否则显式标记该页 `low_text`，宁可让调用方看到缺口。

用法
----
```
# 指定规范（按文件名包含匹配），只处理扫描件
python -B 确定性计算层/tools/ocr_scanned_norms.py \
    --source-root "C:/Study/bisai/Hai AI Agent/隧道施工相关规范" \
    --out data_tunnel/ocr_text \
    --include "GB 50911-2013" "JTG-T 3660-2020" \
    --dpi 200
```
产物：`<out>/<类别>/<PDF 名>.ocr.txt`，页间以 ``----- page N -----`` 分隔。
只读原 PDF；不修改、不移动任何原始文件。
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path


def ocr_pdf(pdf: Path, out: Path, dpi: int, min_chars: int, first: int | None, last: int | None) -> dict:
    import fitz
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    doc = fitz.open(str(pdf))
    try:
        total = doc.page_count
        start = max(1, first or 1)
        end = min(total, last or total)
        chunks: list[str] = []
        low_pages: list[int] = []
        chars = 0
        t0 = time.time()
        for pno in range(start, end + 1):
            page = doc.load_page(pno - 1)
            pix = page.get_pixmap(dpi=dpi)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            result, _ = engine(img)
            lines = [item[1] for item in (result or [])]
            text = "\n".join(lines)
            n = len(text.strip())
            chars += n
            if n < min_chars:
                low_pages.append(pno)
            chunks.append(f"\n----- page {pno} -----\n{text}")
        elapsed = time.time() - t0
    finally:
        doc.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(chunks), encoding="utf-8")
    return {
        "pages_done": end - start + 1,
        "page_range": [start, end],
        "pages_total": total,
        "chars": chars,
        "low_text_pages": low_pages,
        "seconds": round(elapsed, 1),
        "dpi": dpi,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="扫描版规范 OCR（逐页）")
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--include", nargs="*", default=None, help="按文件名包含匹配，缺省则全部")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--min-chars", type=int, default=30)
    ap.add_argument("--first-page", type=int, default=None)
    ap.add_argument("--last-page", type=int, default=None)
    ap.add_argument("--manifest", default=None)
    args = ap.parse_args()

    root = Path(args.source_root)
    out_root = Path(args.out)
    pdfs = sorted(root.rglob("*.pdf"))
    if args.include:
        keys = [k.lower() for k in args.include]
        pdfs = [p for p in pdfs if any(k in p.stem.lower() for k in keys)]
    if not pdfs:
        print("ERR 没有匹配到 PDF")
        return 2

    entries = []
    for pdf in pdfs:
        rel = pdf.relative_to(root)
        category = rel.parts[0] if len(rel.parts) > 1 else "根目录"
        target = out_root / category / (pdf.stem + ".ocr.txt")
        try:
            stat = ocr_pdf(pdf, target, args.dpi, args.min_chars, args.first_page, args.last_page)
        except Exception as exc:  # noqa: BLE001
            print(f"ERR {rel}: {type(exc).__name__}: {exc}")
            entries.append({"file": pdf.stem, "error": f"{type(exc).__name__}: {exc}"})
            continue
        entries.append({"file": pdf.stem, "category": category,
                        "out": str(target).replace("\\", "/"), **stat})
        print(f"OK {rel}  pages={stat['pages_done']} chars={stat['chars']} "
              f"low={len(stat['low_text_pages'])} {stat['seconds']}s")

    if args.manifest:
        mp = Path(args.manifest)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(json.dumps({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "engine": "rapidocr-onnxruntime",
            "source_root": str(root).replace("\\", "/"),
            "files": entries,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"manifest -> {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
