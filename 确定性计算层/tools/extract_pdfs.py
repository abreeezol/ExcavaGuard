"""
只读提取 PDF 文本前若干页，用于判断数据可用性。
输出写入 derived/pdf_extract/。
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

ROOT = Path(r"C:\Study\bisai\Hai AI Agent\基坑智守项目相关数据")
OUT = Path(r"C:\Study\bisai\Hai AI Agent\ExcavaGuard\确定性计算层\derived\pdf_extract")
OUT.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("深基坑引起的墙体与地基位移计算数据库.pdf", 12),
    ("黏土基坑开挖案例/EXCAV-CLAY152830 database/Supplementary material.pdf", 10),
    ("地下室粘土隆起监测/Twenty-one years of heave monitoring in London Clay at .pdf", 8),
    ("地下室粘土隆起监测/A1 - Site investigation cross-sections.pdf", 4),
    ("地下室粘土隆起监测/A2 - Graphs of soil test result graphs.pdf", 4),
]

for rel, pages in TARGETS:
    p = ROOT / rel
    if not p.exists():
        print(f"MISSING: {rel}")
        continue
    try:
        r = PdfReader(str(p))
        n = len(r.pages)
        texts = []
        for i in range(min(pages, n)):
            t = r.pages[i].extract_text() or ""
            texts.append(f"\n----- page {i + 1} -----\n{t[:2500]}")
        body = f"file: {rel}\npages_total: {n}\n" + "".join(texts)
        out = OUT / (p.stem[:60].replace("/", "_") + ".txt")
        out.write_text(body, encoding="utf-8")
        print(f"OK {rel} -> {out.name} (pages={n})")
    except Exception as exc:  # noqa: BLE001
        print(f"ERR {rel}: {type(exc).__name__}: {exc}")
