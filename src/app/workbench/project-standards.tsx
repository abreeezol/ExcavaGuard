"use client";
import { useEffect, useState } from "react";
import type { ProjectStandardDocument } from "@/contracts/project-standards";

async function body(response: Response) {
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message || "项目规范操作失败。");
  return result;
}

export function ProjectStandards({ projectId, disabled, onBusyChange }: {
  projectId: string; disabled: boolean; onBusyChange: (busy: boolean) => void;
}) {
  const apiFetch = (url: string, init?: RequestInit) => {
    const headers = new Headers(init?.headers); headers.set("X-Excavaguard-Project", projectId);
    return fetch(url, { ...init, headers });
  };
  const [documents, setDocuments] = useState<ProjectStandardDocument[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    let cancelled = false;
    void fetch("/api/project-standards", { headers: { "X-Excavaguard-Project": projectId } }).then(body).then(result => {
      if (!cancelled) setDocuments(result.documents);
    }).catch(error => { if (!cancelled) setMessage(String(error.message)); });
    return () => { cancelled = true; };
  }, [projectId]);

  async function upload(form: HTMLFormElement) {
    setBusy(true); onBusyChange(true); setMessage("");
    try {
      const data = new FormData(form);
      data.set("confirmed", "true");
      const result = await body(await apiFetch("/api/project-standards", { method: "POST", body: data }));
      setDocuments((await body(await apiFetch("/api/project-standards"))).documents);
      setMessage(`已入库：${result.document.chunk_count}条切片、${result.document.page_count}页。后续新建报告自动检索启用的项目规范。`);
      form.reset();
    } catch (error) { setMessage(error instanceof Error ? error.message : "上传失败。"); }
    finally { setBusy(false); onBusyChange(false); }
  }

  async function toggle(document: ProjectStandardDocument) {
    setBusy(true); onBusyChange(true); setMessage("");
    try {
      await body(await apiFetch("/api/project-standards", { method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: document.document_id, active: !document.active }) }));
      setDocuments((await body(await apiFetch("/api/project-standards"))).documents);
      setMessage("已更新，影响之后新建的报告；历史报告使用原冻结版本。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "更新失败。"); }
    finally { setBusy(false); onBusyChange(false); }
  }

  return <section className="wb-card" aria-label="项目补充规范">
    <div className="wb-card-head"><h2>项目补充规范（全文检索）</h2></div>
    <p className="wb-hint">上传本工程适用的地方标准、行业标准或专项要求。仅当前工程使用，独立入库；日报、周期报告及附表会保留检索依据。同编号重传后，新文件替换当前启用版本。数值阈值变更请使用下方“用户规范 JSON”。</p>
    <p className="wb-hint">当前工程标识：{projectId}。切换工程请使用工作台上方的项目选择器。</p>
    <form onSubmit={event => { event.preventDefault(); void upload(event.currentTarget); }}>
      <fieldset disabled={disabled || busy} style={{ border: 0, padding: 0 }}>
        <label className="wb-field">规范名称<input name="standard_name" required maxLength={200} placeholder="城市地下工程施工与运行监测技术规程" /></label>
        <label className="wb-field">规范编号及版本<input name="standard_version" required minLength={3} maxLength={100} placeholder="DB33/T 1266-2021" /></label>
        <label className="wb-field">适用地区<input name="region" required maxLength={100} placeholder="浙江省 / 全国" /></label>
        <label className="wb-field">本工程适用范围<input name="applicability" required minLength={2} maxLength={400} placeholder="浙江省基坑施工阶段的监测工作" /></label>
        <label className="wb-field">规范文件<input name="file" type="file" accept=".pdf,.txt,.md" required /></label>
        <p className="wb-hint">支持20MB以内可搜索PDF、UTF-8文本；扫描件请先OCR。原文件和索引仅保存在本服务的项目专库。</p>
        <label><input type="checkbox" required /> 我已核对文件名称、编号、效力及本工程适用范围，同意作为本工程规范候选。</label>
        <div className="wb-actions"><button type="submit" className="wb-btn">{busy ? "处理中…" : "上传并建立项目规范索引"}</button></div>
      </fieldset>
    </form>
    {message && <p role="status" className="wb-hint">{message}</p>}
    {documents.map(document => <div key={document.document_id} className="wb-alert">
      <strong>《{document.standard_name}》 {document.standard_version}</strong>
      <p>{document.region} · {document.chunk_count}条切片 · {document.active ? "已启用" : "已停用"}</p>
      <p>{document.applicability}</p>
      {document.unindexed_pages.length > 0 && <p>文字不足的页码（需人工核对）：{document.unindexed_pages.join("、")}</p>}
      <button type="button" disabled={busy || disabled} className="wb-btn wb-btn-sm" onClick={() => void toggle(document)}>{document.active ? "停用" : "启用"}</button>
    </div>)}
  </section>;
}
