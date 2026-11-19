"use client";

import { useEffect, useState } from "react";
import {
  contextDocumentResponseSchema,
  contextListResponseSchema,
  type ContextDocument,
} from "@/contracts/project-context";

function isAbort(error: unknown) {
  const text = error instanceof Error ? `${error.name} ${error.message}` : String(error);
  return /(?:signal is )?aborted|aborterror/i.test(text);
}

export function ProjectContextPanel({
  apiFetch,
  start,
  finish,
  hidden = false,
}: {
  apiFetch: (url: string, init?: RequestInit) => Promise<Response>;
  start: () => boolean;
  finish: () => void;
  hidden?: boolean;
}) {
  const [documents, setDocuments] = useState<ContextDocument[]>([]);
  const [kind, setKind] = useState("case");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    void apiFetch("/api/project-context")
      .then(async response => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.error?.message || "读取辅助资料失败");
        return body;
      })
      .then(body => {
        if (!cancelled) setDocuments(contextListResponseSchema.parse(body).documents);
      })
      .catch(error => {
        if (!cancelled && !isAbort(error)) {
          setMessage(error instanceof Error ? error.message : "读取辅助资料失败");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [apiFetch]);

  async function upload() {
    if (!file || !start()) return;
    setMessage("");
    try {
      const form = new FormData();
      form.set("file", file);
      form.set("kind", kind);
      form.set("title", title);
      const response = await apiFetch("/api/project-context", { method: "POST", body: form });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error?.message || "上传失败");
      const document = contextDocumentResponseSchema.parse(body).document;
      setDocuments(current => [
        document,
        ...current.filter(item => item.document_id !== document.document_id),
      ]);
      setMessage("辅助资料已保存，生成下一份报告时自动参与分析。");
    } catch (error) {
      if (!isAbort(error)) setMessage(error instanceof Error ? error.message : "上传失败");
    } finally {
      finish();
    }
  }

  async function toggle(document: ContextDocument) {
    if (!start()) return;
    setMessage("");
    try {
      const response = await apiFetch("/api/project-context", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: document.document_id,
          active: !document.active,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error?.message || "更新失败");
      const updated = contextDocumentResponseSchema.parse(body).document;
      setDocuments(rows => rows.map(row =>
        row.document_id === document.document_id ? updated : row
      ));
    } catch (error) {
      if (!isAbort(error)) setMessage(error instanceof Error ? error.message : "更新失败");
    } finally {
      finish();
    }
  }

  return <section className="wb-card" aria-label="案例、工况与巡视资料" hidden={hidden}>
    <div className="wb-card-head"><h2>案例、工况与巡视资料（可选）</h2></div>
    <p className="wb-hint">仅用于当前工程的关联线索，不改变监测判据。无资料时仍可生成报告；新上传资料用于后续新建运行。</p>
    <div className="wb-row">
      <label className="wb-field">
        <span>资料类型</span>
        <select aria-label="辅助资料类型" value={kind} onChange={event => setKind(event.target.value)}>
          <option value="case">相似案例</option>
          <option value="work_condition">工况记录</option>
          <option value="patrol">巡视记录</option>
        </select>
      </label>
      <label className="wb-field">
        <span>资料标题</span>
        <input
          aria-label="辅助资料标题"
          value={title}
          onChange={event => setTitle(event.target.value)}
          placeholder="文本案例可填写标题"
        />
      </label>
    </div>
    <label className="wb-field">
      <span>资料文件</span>
      <input
        aria-label="辅助资料文件"
        type="file"
        accept=".json,.txt,.md,.csv,.pdf"
        onChange={event => setFile(event.target.files?.[0] ?? null)}
      />
    </label>
    <p className="wb-hint">JSON 文件需包含 kind、title、records；案例支持可搜索 PDF 和 UTF-8 文本，工况与巡视支持 CSV。</p>
    <div className="wb-actions">
      <a className="wb-btn wb-btn-sm" href={`/api/project-context?sample=${kind}`} download>
        下载当前类型 JSON 模板
      </a>
      <button className="wb-btn wb-btn-sm" type="button" disabled={!file} onClick={() => void upload()}>
        上传辅助资料
      </button>
    </div>
    {message && <p role="status" className="wb-hint">{message}</p>}
    {documents.length > 0 && <ul className="wb-document-list">
      {documents.map(document => <li key={document.document_id}>
        <span>{document.title} · {({ case: "案例", work_condition: "工况", patrol: "巡视" } as Record<string, string>)[document.kind]} · {document.records.length}条</span>
        <div className="wb-actions">
          <a className="wb-btn wb-btn-sm" href={`/api/project-context?download=${document.document_id}`} download>下载原资料</a>
          <button type="button" className="wb-btn wb-btn-sm" onClick={() => void toggle(document)}>
            {document.active ? "停用" : "启用"}
          </button>
        </div>
      </li>)}
    </ul>}
  </section>;
}
