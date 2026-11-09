import { canonicalProjectAdapterId } from "@/server/engineering-adapters/engineering-types";
import "server-only";
import { createHash, randomUUID } from "node:crypto";
import { readdir, readFile, writeFile, rm } from "node:fs/promises";
import { resolve } from "node:path";
import { z } from "zod";
import { contextDocumentSchema, contextUploadSchema, type ContextDocument } from "@/contracts/project-context";
import { atomicJson, withFileLock } from "@/server/storage/atomic";
import { projectEngineering } from "@/server/engineering-adapters/project";
import { AppError } from "@/server/api/errors";
const root = () => resolve(/* turbopackIgnore: true */ process.env.EXCAVAGUARD_PROJECT_CONTEXT_ROOT || "var/project-context");
export async function listProjectContext(projectId: string): Promise<ContextDocument[]> {
  z.uuid().parse(projectId);
  const adapterId = projectEngineering(projectId).adapter.id;
  const folder = resolve(root(), projectId);
  let names: string[];
  try { names = await readdir(folder); } catch (e) { if ((e as NodeJS.ErrnoException).code === "ENOENT") return []; throw e; }
  const documents = await Promise.all(names.filter(n => /^[a-f0-9-]{36}\.json$/.test(n)).map(async name => {
    const doc = contextDocumentSchema.parse(JSON.parse(await readFile(resolve(folder,name),"utf8")));
    if (doc.project_id !== projectId || canonicalProjectAdapterId(doc.adapter_id) !== canonicalProjectAdapterId(adapterId)) throw new AppError(409,"INVALID_REQUEST","项目辅助资料的工程或场景不一致。");
    if(doc.source_sha256 && createHash("sha256").update(await readFile(resolve(folder,doc.document_id+".source"))).digest("hex")!==doc.source_sha256)throw new AppError(409,"INVALID_REQUEST","辅助资料原文件指纹不一致。");
    const {kind,title,records} = doc;
    if (createHash("sha256").update(JSON.stringify({kind,title,records})).digest("hex") !== doc.sha256) throw new AppError(409,"INVALID_REQUEST","辅助资料指纹不一致。");
    return {...doc,adapter_id:adapterId};
  }));
  return documents.sort((a,b) => b.created_at.localeCompare(a.created_at));
}
export async function uploadProjectContext(projectId: string, value: unknown, actor: string, source?: {bytes:Uint8Array;name:string}) {
  z.uuid().parse(projectId);
  const parsed = contextUploadSchema.safeParse(value);
  if (!parsed.success) throw new AppError(400,"INVALID_REQUEST",parsed.error.issues.map(i=>i.message).slice(0,3).join("；"));
  return withFileLock(resolve(root(),projectId,".write.lock"), async () => {
  const existing = await listProjectContext(projectId);
  if (existing.length >= 200) throw new AppError(400,"INVALID_REQUEST","当前项目辅助资料最多200份。");
  const sha256 = createHash("sha256").update(JSON.stringify(parsed.data)).digest("hex");
  const duplicate = existing.find(d=>d.sha256===sha256);
  if (duplicate) return duplicate;
  if(existing.filter(d=>d.active).length>=50 || existing.filter(d=>d.active).reduce((n,d)=>n+JSON.stringify(d).length,0)+JSON.stringify(parsed.data).length>900000) throw new AppError(400,"INVALID_REQUEST","启用的辅助资料超过50份或运行预算，请先停用不需要的资料。");
  const doc = contextDocumentSchema.parse({...parsed.data,sha256,document_id:randomUUID(),project_id:projectId,
    ...(source?{original_name:source.name.slice(0,300),source_sha256:createHash("sha256").update(source.bytes).digest("hex")}:{}),
    adapter_id:projectEngineering(projectId).adapter.id,created_at:new Date().toISOString(),uploaded_by:actor});
  const rawPath=resolve(root(),projectId,doc.document_id+".source");
  if(source)await writeFile(rawPath,source.bytes,{mode:0o600,flag:"wx"});
  try{await atomicJson(resolve(root(),projectId,doc.document_id+".json"),doc,true);}catch(error){if(source)await rm(rawPath,{force:true});throw error;}
  return doc;
  });
}

export async function setProjectContextActive(projectId:string,documentId:string,active:boolean) {
  z.uuid().parse(documentId);
  return withFileLock(resolve(root(),projectId,".write.lock"),async()=>{
    const documents=await listProjectContext(projectId);const doc=documents.find(d=>d.document_id===documentId);
    if(!doc)throw new AppError(404,"FILE_NOT_FOUND","未找到当前工程辅助资料。");
    if(active&&!doc.active&&documents.filter(d=>d.active).length>=50)throw new AppError(400,"INVALID_REQUEST","最多同时启用50份辅助资料。");
    if(active&&documents.filter(d=>d.active&&d.document_id!==documentId).reduce((n,d)=>n+JSON.stringify(d).length,0)+JSON.stringify(doc).length>900000)throw new AppError(400,"INVALID_REQUEST","启用资料超过运行预算。");
    const next={...doc,active};await atomicJson(resolve(root(),projectId,documentId+".json"),next);return next;
  });
}

export async function readProjectContextSource(projectId:string,documentId:string){
 z.uuid().parse(documentId);const doc=(await listProjectContext(projectId)).find(d=>d.document_id===documentId);
 if(!doc)throw new AppError(404,"FILE_NOT_FOUND","辅助资料不存在。");
 return {name:doc.original_name??doc.title+'.json',bytes:doc.source_sha256?await readFile(resolve(root(),projectId,documentId+'.source')):Buffer.from(JSON.stringify({kind:doc.kind,title:doc.title,records:doc.records},null,2))};
}
