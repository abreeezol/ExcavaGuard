"""Project-only SQLite retrieval library. Never writes the shared standards corpus."""
import base64
import hashlib
import io
import json
import logging
from pathlib import Path
import re
import sqlite3
import sys
import uuid

logging.getLogger("pypdf").setLevel(logging.ERROR)
DOC_COLUMNS = "id,project_id,sha256,metadata,active,created_at,chunk_count,page_count"


def terms(text):
    result = set(re.findall(r"[a-z0-9]+", text.lower()))
    for word in re.findall(r"[\u3400-\u9fff]+", text):
        result.update(word[i:i + 2] for i in range(len(word) - 1))
    return sorted(result)


def pages_from(data, extension):
    if extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("文件内容不是 PDF。")
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted or len(reader.pages) > 1000:
            raise ValueError("不支持加密 PDF 或超过1000页的文件。")
        pages = [p.extract_text() or "" for p in reader.pages]
        glyphs = sum(len(re.findall(r"/G\d+", text)) for text in pages)
        if glyphs > 20:
            raise ValueError("PDF 字体编码无法可靠还原原文，请先 OCR 导出可搜索 PDF 或 UTF-8 文本，不能将乱码入库。")
        # Do not silently treat an OCR-free scan as a successfully indexed book.
        missing = [i + 1 for i, text in enumerate(pages) if len(re.sub(r"\s", "", text)) < 20]
        if len(missing) > max(2, len(pages) * .1):
            raise ValueError("PDF 缺少可检索文字层，请先完成 OCR，再上传可搜索 PDF 或 UTF-8 文本。")
        return pages, missing
    return [data.decode("utf-8-sig")], []


def chunks_from(pages):
    chunks = []
    for page, text in enumerate(pages, 1):
        text = text.replace("\x00", "").strip()
        # Preserve page-local raw text, including tables; do not infer numeric rules.
        parts = re.split(r"(?m)(?=^\s*\d{1,2}\.\d{1,2}\.\d{1,3}(?:\s|[\u3400-\u9fff]))", text)
        for part in parts:
            part = part.strip()
            if len(re.sub(r"\s", "", part)) < 20:
                continue
            match = re.match(r"(\d{1,2}\.\d{1,2}\.\d{1,3})", part)
            clause = match.group(1) if match else "页内文本（条文号待复核）"
            for offset in range(0, len(part), 2400):
                fragment = part[offset:offset + 2600].strip()
                if fragment:
                    chunks.append((page, clause, fragment))
    if not chunks or len(chunks) > 10000:
        raise ValueError("没有可检索正文或切片超过10000条，请检查文本/OCR。")
    return chunks


def document(row):
    return {**json.loads(row["metadata"]), "document_id": row["id"],
            "project_id": row["project_id"], "sha256": row["sha256"],
            "active": bool(row["active"]), "created_at": row["created_at"],
            "chunk_count": row["chunk_count"], "page_count": row["page_count"]}


def main(req):
    project = str(uuid.UUID(req["project_id"]))
    root = Path(req["root"]).resolve() / project
    action = req["action"]
    dbfile = root / "standards.sqlite3"
    if not dbfile.exists() and action in ("list", "search", "select"):
        if action == "select" and req.get("document_ids"):
            raise ValueError("所选规范不属于当前项目或已不存在。")
        return []
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(dbfile, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL, sha256 TEXT NOT NULL,
          metadata TEXT NOT NULL, original BLOB NOT NULL, active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
          chunk_count INTEGER NOT NULL, page_count INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS chunks (
          id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
          page INTEGER NOT NULL, clause TEXT NOT NULL, text TEXT NOT NULL);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_search USING fts5(id UNINDEXED, document_id UNINDEXED, tokens);
    """)
    try:
        if action == "ingest":
            raw = base64.b64decode(req["bytes"], validate=True)
            if not raw or len(raw) > 20 * 1024 * 1024:
                raise ValueError("文件为空或超过20MB。")
            meta = req["metadata"]
            pages, missing = pages_from(raw, meta["extension"])
            if sum(map(len, pages)) > 5_000_000:
                raise ValueError("提取正文超过500万字，请拆分文件。")
            chunks = chunks_from(pages)
            sha = hashlib.sha256(raw).hexdigest()
            meta["unindexed_pages"] = missing
            key = hashlib.sha256((project + sha + json.dumps(meta, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
            docid = str(uuid.UUID(key[:32], version=5))
            with db:
                existing = db.execute(f"SELECT {DOC_COLUMNS} FROM documents WHERE id=? AND project_id=?", (docid, project)).fetchone()
                if not existing:
                    db.execute("UPDATE documents SET active=0 WHERE project_id=? AND json_extract(metadata,'$.standard_version')=?",
                               (project, meta["standard_version"]))
                    db.execute("INSERT INTO documents(id,project_id,sha256,metadata,original,chunk_count,page_count) VALUES(?,?,?,?,?,?,?)",
                               (docid, project, sha, json.dumps(meta, ensure_ascii=False), raw, len(chunks), len(pages)))
                    for i, (page, clause, text) in enumerate(chunks):
                        cid = "project:" + docid + ":" + str(i)
                        db.execute("INSERT INTO chunks VALUES(?,?,?,?,?)", (cid, docid, page, clause, text))
                        db.execute("INSERT INTO chunk_search VALUES(?,?,?)", (cid, docid, " ".join(terms(text))))
            return document(db.execute(f"SELECT {DOC_COLUMNS} FROM documents WHERE id=?", (docid,)).fetchone())
        if action == "set_active":
            with db:
                target = db.execute("SELECT metadata FROM documents WHERE id=? AND project_id=?", (req["document_id"], project)).fetchone()
                if not target:
                    raise ValueError("未找到当前项目的规范。")
                if req["active"]:
                    version = json.loads(target["metadata"])["standard_version"]
                    db.execute("UPDATE documents SET active=0 WHERE project_id=? AND json_extract(metadata,'$.standard_version')=?", (project, version))
                changed = db.execute("UPDATE documents SET active=? WHERE id=? AND project_id=?",
                                     (int(req["active"]), req["document_id"], project)).rowcount
                if not changed:
                    raise ValueError("未找到当前项目的规范。")
            return document(db.execute(f"SELECT {DOC_COLUMNS} FROM documents WHERE id=?", (req["document_id"],)).fetchone())
        if action in ("list", "select"):
            docs = [document(r) for r in db.execute(f"SELECT {DOC_COLUMNS} FROM documents WHERE project_id=? ORDER BY created_at DESC,id", (project,))]
            if action == "list":
                return docs
            ids = req.get("document_ids")
            selected = [d for d in docs if d["document_id"] in ids] if ids is not None else [d for d in docs if d["active"]]
            if ids is not None and set(ids) != {d["document_id"] for d in selected}:
                raise ValueError("所选规范不属于当前项目或已不存在。")
            if req.get("require_active") and any(not d["active"] for d in selected):
                raise ValueError("所选规范已停用，请重新选择。")
            return selected
        if action == "search":
            ids = req.get("document_ids", [])
            if not ids:
                return []
            query = req["query"]
            tokens = terms(query["query"])[:80]
            if not tokens:
                return []
            marks = ",".join("?" for _ in ids)
            rows = db.execute(f"""SELECT c.*, d.metadata, d.project_id, d.sha256, bm25(chunk_search) AS rank
                FROM chunk_search JOIN chunks c ON c.id=chunk_search.id JOIN documents d ON d.id=c.document_id
                WHERE chunk_search MATCH ? AND d.project_id=? AND d.id IN ({marks}) ORDER BY rank LIMIT 500""",
                (" OR ".join('"' + t + '"' for t in tokens), project, *ids)).fetchall()
            result = []
            filters = query.get("filters") or {}
            for row in rows:
                meta = json.loads(row["metadata"])
                if filters.get("standard_versions") and meta["standard_version"] not in filters["standard_versions"]:
                    continue
                if filters.get("region") and meta["region"] != filters["region"]:
                    continue
                if filters.get("effective_status", "active") != "active":
                    continue
                if filters.get("monitoring_item") and filters["monitoring_item"] not in row["text"]:
                    continue
                if filters.get("excavation_safety_level") and filters["excavation_safety_level"] not in row["text"]:
                    continue
                result.append({"id": row["id"], "text": row["text"], "score": -row["rank"], "provider": "project",
                  "matched_terms": [t for t in tokens if t in row["text"]][:50],
                  "metadata": {"standard_name": meta["standard_name"], "standard_version": meta["standard_version"],
                    "clause": row["clause"], "source_location": f"项目补充规范《{meta['standard_name']}》· PDF/文本第{row['page']}页",
                    "applicability": [meta["applicability"], "仅当前工程；工程师已确认文件效力及适用范围；条文仍需复核"],
                    "effective_status": "active", "region": meta["region"], "project_id": project,
                    "document_id": row["document_id"], "content_sha256": row["sha256"]}})
            return result[:query.get("top_k", 3)]
        raise ValueError("不支持的规范库操作。")
    finally:
        db.close()


if __name__ == "__main__":
    try:
        result = main(json.load(sys.stdin))
        response = {"schema": "excavaguard.skill_result/v1", "skill": "project-standard-library", "ok": True, "result": result}
    except ImportError:
        response = {"ok": False, "error": {"code": "INVALID_STANDARD", "message": "PDF 解析依赖缺失，请在项目虚拟环境安装 requirements.txt 中的 pypdf。"}}
    except (ValueError, KeyError, UnicodeError) as error:
        response = {"ok": False, "error": {"code": "INVALID_STANDARD", "message": str(error)}}
    except Exception:
        response = {"ok": False, "error": {"code": "INVALID_STANDARD", "message": "项目规范解析或数据库操作失败；请检查 PDF 和独立存储配置。"}}
    print(json.dumps(response, ensure_ascii=False))
