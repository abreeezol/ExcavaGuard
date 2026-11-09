import { readFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createHash } from "node:crypto";
import { z } from "zod";
import { requireAccess,requireProjectAction } from "@/server/access";
import { projectEngineering } from "@/server/engineering-adapters/project";
import { adapterAssetPath } from "@/server/engineering-adapters/registry";
import { atomicJson,withFileLock } from "@/server/storage/atomic";
import { apiOk,apiError,apiErrorFromException } from "@/server/api/respond";
export const runtime='nodejs';export const dynamic='force-dynamic';
function context(projectId:string){
 const {adapter,snapshot}=projectEngineering(projectId);const text=readFileSync(adapterAssetPath(`engineering-adapters/${adapter.id}/evaluation.json`),'utf8');const suite=JSON.parse(text);const hash=createHash('sha256').update(text).digest('hex');
 const path=resolve(/* turbopackIgnore: true */ process.env.EXCAVAGUARD_REVIEW_ROOT||'var/professional-reviews',projectId,snapshot.digest,hash+'.json');return {suite,hash,path,snapshot};
}
export async function GET(request:Request){try{const access=requireAccess(request);const {suite,hash,path,snapshot}=context(access.project_id);
 const selection=new URL(request.url).searchParams;
 if(selection.has('fixtures')||selection.has('results')){const kind=selection.has('fixtures')?'evaluation-fixtures':'evaluation-results';const text=readFileSync(adapterAssetPath(`engineering-adapters/${snapshot.id}/${kind}.json`),'utf8');return new Response(text,{headers:{'Content-Type':'application/json; charset=utf-8','Content-Disposition':`attachment; filename="${snapshot.id}-${kind}.json"`,'Cache-Control':'no-store'}});}
 let review=null;try{review=JSON.parse(await readFile(path,'utf8'));}catch(e){if((e as NodeJS.ErrnoException).code!=='ENOENT')throw e;}return apiOk({suite,suite_hash:hash,adapter_digest:snapshot.digest,review,status:review?.status??'pending_engineer_review'});}catch(e){return apiErrorFromException(e);}}
export async function POST(request:Request){try{
 const access=requireProjectAction(request,'review');const body=z.strictObject({suite_hash:z.string(),adapter_digest:z.string(),expected_revision:z.number().int().nonnegative(),source_reference:z.string().trim().min(1).max(1000),evaluations:z.array(z.strictObject({case_id:z.string(),decision:z.enum(['pass','needs_changes']),comment:z.string().max(2000)})).min(1).max(100)}).safeParse(await request.json());
 if(!body.success)return apiError(400,'INVALID_REQUEST','请逐项填写评价，并提供复核依据。');const current=context(access.project_id);
 if(body.data.suite_hash!==current.hash||body.data.adapter_digest!==current.snapshot.digest)return apiError(409,'INVALID_REQUEST','评价样例或能力版本已变化，请刷新。');
 const ids=current.suite.cases.map((c:{case_id:string})=>c.case_id).sort();const actual=body.data.evaluations.map(c=>c.case_id).sort();if(JSON.stringify(ids)!==JSON.stringify(actual)||new Set(actual).size!==actual.length)return apiError(400,'INVALID_REQUEST','评价须逐项覆盖全部样例。');
 if(body.data.evaluations.some(c=>c.decision==='needs_changes'&&!c.comment.trim()))return apiError(400,'INVALID_REQUEST','需修改项目必须填写问题。');
 return withFileLock(current.path+'.lock',async()=>{let previous;try{previous=JSON.parse(await readFile(current.path,'utf8'));}catch(e){if((e as NodeJS.ErrnoException).code!=='ENOENT')throw e;}
 if((previous?.revision??0)!==body.data.expected_revision)return apiError(409,'INVALID_REQUEST','评价已更新，请刷新。');
 const review={...body.data,project_id:access.project_id,revision:body.data.expected_revision+1,reviewer:access.actor??{id:access.owner_id,name:'本地复核人'},created_at:new Date().toISOString(),status:body.data.evaluations.every(c=>c.decision==='pass')?'engineer_review_recorded':'needs_changes'};
 await atomicJson(current.path+`.revision-${review.revision}.json`,review,true);await atomicJson(current.path,review);return apiOk({review});});
}catch(e){return apiErrorFromException(e);}}
