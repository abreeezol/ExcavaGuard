import { callSkillScript } from "@/server/skills/python-bridge";
import { z } from "zod";
import { requireAccess, requireProjectAction } from "@/server/access";
import { apiOk, apiError, apiErrorFromException } from "@/server/api/respond";
import { listProjectContext, uploadProjectContext, setProjectContextActive,readProjectContextSource } from "@/server/context/library";
export const runtime="nodejs";
export const dynamic="force-dynamic";
export async function GET(request:Request) {
  try {
    const access=requireAccess(request);const kind=new URL(request.url).searchParams.get("sample");
    const download=new URL(request.url).searchParams.get("download");
    if(download){if(!z.uuid().safeParse(download).success)return apiError(400,"INVALID_REQUEST","资料编号无效。");const file=await readProjectContextSource(access.project_id,download);return new Response(new Uint8Array(file.bytes),{headers:{"Content-Type":"application/octet-stream","Content-Disposition":`attachment; filename="source-file"; filename*=UTF-8''${encodeURIComponent(file.name)}`,"Cache-Control":"no-store"}});}
    if(kind && ["case","work_condition","patrol"].includes(kind)) {
      const record=kind==="case"?{text:"SIMULATED：水平位移案例，仅用于关联测试",metric_keys:["wall_top_horizontal_displacement"]}:{timestamp:"2026-10-02 08:00:00",section:"A",text:"SIMULATED：现场记录，仅用于测试",recorder:"模拟记录人"};
      return new Response(JSON.stringify({kind,title:"SIMULATED辅助资料模板",records:[record]},null,2),{headers:{"Content-Type":"application/json; charset=utf-8","Content-Disposition":`attachment; filename="${kind}.json"`,"Cache-Control":"no-store"}});
    }
    return apiOk({documents:await listProjectContext(access.project_id)});
  }
  catch(error) {return apiErrorFromException(error);}
}
export async function POST(request:Request) {
  try {
    const access=requireProjectAction(request,"write");
    if(Number(request.headers.get('content-length'))>3_000_000) return apiError(413,"FILE_TOO_LARGE","辅助资料不能超过3MB。");
    let value:unknown;let original:{bytes:Uint8Array;name:string}|undefined;
    if(request.headers.get('content-type')?.startsWith('multipart/form-data')) {
      const form=await request.formData();const file=form.get('file');
      if(!(file instanceof File)) return apiError(400,"INVALID_REQUEST","请选择辅助资料文件。");
      if(file.size>3_000_000) return apiError(413,"FILE_TOO_LARGE","辅助资料不能超过3MB。");
      original={bytes:new Uint8Array(await file.arrayBuffer()),name:file.name};
      if(/\.(csv|pdf)$/i.test(file.name)) {
        const ext=file.name.toLowerCase().endsWith('.csv')?'.csv':'.pdf';
        const parsed=await callSkillScript('project-context-library','import_context.py',{bytes:Buffer.from(original.bytes).toString('base64'),extension:ext,kind:String(form.get('kind')||'case')});
        value={kind:String(form.get('kind')||'case'),title:String(form.get('title')||file.name),records:(parsed.result as {records:unknown[]}).records};
      } else {
      const text=await file.text();
      if(text.includes("\uFFFD"))return apiError(400,"INVALID_REQUEST","文件编码无法可靠读取，请转换为UTF-8后上传。");
      if(/\.json$/i.test(file.name)) {try{value=JSON.parse(text);}catch{return apiError(400,"INVALID_JSON","辅助资料JSON无法解析。");}}
      else if(/\.(txt|md)$/i.test(file.name) && form.get('kind')==='case') {
        value={kind:'case',title:String(form.get('title')||file.name),records:[{text}]};
      } else return apiError(415,"UNSUPPORTED_MEDIA_TYPE","案例支持结构化JSON、UTF-8 TXT/Markdown；工况和巡视使用带时间、区段的JSON。");
      }
    } else if(request.headers.get('content-type')?.startsWith('application/json')) {
      const text=await request.text();if(Buffer.byteLength(text)>3_000_000)return apiError(413,"FILE_TOO_LARGE","辅助资料不能超过3MB。");
      try{value=JSON.parse(text);}catch{return apiError(400,"INVALID_JSON","辅助资料JSON无法解析。");}
    } else return apiError(415,"UNSUPPORTED_MEDIA_TYPE","请使用JSON或文件上传。");
    return apiOk({document:await uploadProjectContext(access.project_id,value,access.actor?.id??access.owner_id,original)},201);
  } catch(error){return apiErrorFromException(error);}
}

export async function PATCH(request:Request) {
  try {const access=requireProjectAction(request,"write");const body=z.strictObject({document_id:z.uuid(),active:z.boolean()}).safeParse(await request.json().catch(()=>null));
    if(!body.success)return apiError(400,"INVALID_REQUEST","请指定资料和启停状态。");
    return apiOk({document:await setProjectContextActive(access.project_id,body.data.document_id,body.data.active)});
  }catch(error){return apiErrorFromException(error);}
}
