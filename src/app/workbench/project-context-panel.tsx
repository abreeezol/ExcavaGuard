"use client";
import { useEffect, useState } from "react";
type Doc={document_id:string;title:string;kind:string;records:unknown[];active:boolean};
export function ProjectContextPanel({apiFetch,start,finish}:{apiFetch:(url:string,init?:RequestInit)=>Promise<Response>;start:()=>boolean;finish:()=>void}) {
  const [documents,setDocuments]=useState<Doc[]>([]);
  const [kind,setKind]=useState('case');const [title,setTitle]=useState('');const [file,setFile]=useState<File|null>(null);const [message,setMessage]=useState('');
  useEffect(()=>{let cancelled=false;void apiFetch('/api/project-context').then(async r=>{const b=await r.json();if(!r.ok)throw new Error(b.error?.message||'读取辅助资料失败');return b;}).then(b=>{if(!cancelled)setDocuments(b.documents);}).catch(e=>{if(!cancelled)setMessage(e.message);});return()=>{cancelled=true;};},[apiFetch]);
  return <section className="wb-card"><div className="wb-card-head"><h2>案例、工况与巡视资料（可选）</h2></div>
    <p className="wb-hint">仅用于当前工程的关联线索，不改变监测判据。无资料时仍可生成报告；新上传资料用于后续新建运行。</p>
    <select aria-label="辅助资料类型" value={kind} onChange={e=>setKind(e.target.value)}><option value="case">相似案例</option><option value="work_condition">工况记录</option><option value="patrol">巡视记录</option></select>
    <a className="wb-btn wb-btn-sm" href={`/api/project-context?sample=${kind}`} download>下载当前类型JSON模板</a>
    <input aria-label="辅助资料标题" value={title} onChange={e=>setTitle(e.target.value)} placeholder="资料标题（文本案例使用）"/>
    <input aria-label="辅助资料文件" type="file" accept=".json,.txt,.md,.csv,.pdf" onChange={e=>setFile(e.target.files?.[0]??null)}/>
    <p className="wb-hint">JSON文件需包含kind、title、records；记录使用text、timestamp、section、recorder等字段。案例也支持可搜索PDF和UTF-8文本；工况/巡视支持CSV。</p>
    <button className="wb-btn wb-btn-sm" type="button" disabled={!file} onClick={()=>{if(!file||!start())return;setMessage('');void(async()=>{try{const form=new FormData();form.set('file',file);form.set('kind',kind);form.set('title',title);const response=await apiFetch('/api/project-context',{method:'POST',body:form});const body=await response.json();if(!response.ok)throw new Error(body.error?.message||'上传失败');setDocuments(current=>[body.document,...current.filter(d=>d.document_id!==body.document.document_id)]);setMessage('辅助资料已保存，生成下一份报告时自动参与分析。');}catch(e){setMessage(e instanceof Error?e.message:'上传失败');}finally{finish();}})();}}>上传辅助资料</button>
    {message&&<p role="status">{message}</p>}
    <ul>{documents.map(d=><li key={d.document_id}>{d.title} · {({case:'案例',work_condition:'工况',patrol:'巡视'} as Record<string,string>)[d.kind]} · {d.records.length}条 <a href={`/api/project-context?download=${d.document_id}`} download>下载原资料</a> · {d.active ? "已启用" : "已停用"} <button type="button" className="wb-btn wb-btn-sm" onClick={()=>{if(!start())return;void apiFetch("/api/project-context",{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({document_id:d.document_id,active:!d.active})}).then(async r=>{const body=await r.json();if(!r.ok)throw new Error(body.error?.message||"更新失败");setDocuments(rows=>rows.map(row=>row.document_id===d.document_id?body.document:row));}).catch(e=>setMessage(e.message)).finally(finish);}}>{d.active ? "停用" : "启用"}</button></li>)}</ul>
  </section>;
}
