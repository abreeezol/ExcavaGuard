"""把规范 PDF 抽取为可检索的文本语料（参数化版本）
=================================================

与 `extract_pdfs.py`（路径写死的旧脚本）不同，本工具用命令行参数指定规范根目录与输出目录，
因此同一份代码可以给基坑、隧道或多项目规范集使用，不需要改代码。

产物
----
```
<out>/<类别目录>/<PDF 文件名>.txt      逐页文本，页间用 "----- page N -----" 分隔
<manifest>                             每本的页数、字符数、空页率与"疑似扫描件"标记
```

为什么保留空页率与页字符数
--------------------------
扫描件 PDF 没有文字层，抽出来是空白。如果直接把空文本写进语料，切片数为 0 却"看起来成功"，
后续 RAG 会变成"检索不到就当没有要求"。所以本工具**显式标记** `needs_ocr`，
由调用方决定是否走 OCR，绝不把空语料当成功。

用法
----
```
python -B 确定性计算层/tools/build_tunnel_corpus.py \
    --source-root "C:/Study/bisai/Hai AI Agent/隧道施工相关规范" \
    --out data_tunnel/ocr_text \
    --manifest data_tunnel/corpus_manifest.json
```

只读源 PDF，不复制、不修改原文件。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

MIN_CHARS_PER_PAGE = 40      # 低于此值视为该页无有效文字层
SCANNED_PAGE_RATIO = 0.5     # 空页占比超过此值 → 标记为扫描件


def extract_one(pdf: Path) -> dict:
    import fitz  # pymupdf

    doc = fitz.open(str(pdf))
    try:
        pages = doc.page_count
        texts: list[str] = []
        chars = 0
        empty_pages = 0
        for i in range(pages):
            raw = doc.load_page(i).get_text("text") or ""
            raw = raw.replace("\x00", "")
            stripped = raw.strip()
            if len(stripped) < MIN_CHARS_PER_PAGE:
                empty_pages += 1
            chars += len(stripped)
            texts.append(f"\n----- page {i + 1} -----\n{raw}")
        return {
            "pages": pages,
            "chars": chars,
            "empty_pages": empty_pages,
            "text": "".join(texts),
        }
    finally:
        doc.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="规范 PDF → 文本语料（逐页）")
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--force", action="store_true", help="覆盖已存在的文本文件")
    args = ap.parse_args()

    root = Path(args.source_root)
    out_root = Path(args.out)
    if not root.is_dir():
        print(f"ERR 规范目录不存在：{root}")
        return 2

    pdfs = sorted(root.rglob("*.pdf"))
    if not pdfs:
        print(f"ERR 规范目录内没有 PDF：{root}")
        return 2

    entries: list[dict] = []
    for pdf in pdfs:
        rel = pdf.relative_to(root)
        category = rel.parts[0] if len(rel.parts) > 1 else "根目录"
        target = out_root / category / (pdf.stem + ".txt")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            info = extract_one(pdf)
        except Exception as exc:  # noqa: BLE001
            entries.append({
                "code": pdf.stem, "category": category, "file_name": pdf.name,
                "error": f"{type(exc).__name__}: {exc}", "needs_ocr": True,
            })
            print(f"ERR {rel} -> {type(exc).__name__}: {exc}")
            continue

        if args.force or not target.exists():
            target.write_text(info["text"], encoding="utf-8")

        ratio = (info["empty_pages"] / info["pages"]) if info["pages"] else 1.0
        entries.append({
            "code": pdf.stem,
            "category": category,
            "file_name": pdf.name,
            "path": str(pdf).replace("\\", "/"),
            "text_path": str(target).replace("\\", "/"),
            "pages": info["pages"],
            "chars": info["chars"],
            "chars_per_page": round(info["chars"] / info["pages"], 1) if info["pages"] else 0,
            "empty_pages": info["empty_pages"],
            "empty_page_ratio": round(ratio, 3),
            "needs_ocr": ratio >= SCANNED_PAGE_RATIO or info["chars"] == 0,
            "error": None,
        })
        flag = "需OCR" if entries[-1]["needs_ocr"] else "可检索"
        print(f"OK  [{flag}] {rel}  pages={info['pages']} chars={info['chars']} "
              f"empty={info['empty_pages']}")

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_root": str(root).replace("\\", "/"),
        "out_root": str(out_root).replace("\\", "/"),
        "stats": {
            "total": len(entries),
            "needs_ocr": sum(1 for e in entries if e.get("needs_ocr")),
            "pages": sum(e.get("pages") or 0 for e in entries),
            "chars": sum(e.get("chars") or 0 for e in entries),
        },
        "files": entries,
    }
    if args.manifest:
        mp = Path(args.manifest)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nmanifest -> {mp}")
    print(json.dumps(manifest["stats"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
