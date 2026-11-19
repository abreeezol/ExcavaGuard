import { beforeAll, afterAll, it, expect, vi } from 'vitest';
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync, copyFileSync, readdirSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { tmpdir } from 'node:os';
import { createHash } from 'node:crypto';
import { legacyDirectory } from '@/server/auth/directory';
import { DEFAULT_PROJECT_ID } from '@/contracts/access';
import { loadEngineeringAdapter } from '@/server/engineering-adapters/registry';
import { POST as uploadAPI } from '@/app/api/monitoring-files/route';
import { POST as runAPI } from '@/app/api/runs/route';
import { POST as reviewAPI } from '@/app/api/runs/[runId]/review/route';
import { GET as runGET } from '@/app/api/runs/[runId]/route';
import { GET as downloadAPI } from '@/app/api/report-artifacts/[draftId]/[fileName]/route';

const enabled=process.env.EXCAVAGUARD_TEST_ENGINEER_FEEDBACK==='1';
const base=resolve('final_test/tunnel-7day-10min/inputs');
const output=resolve('var/acceptance/tunnel-engineer-feedback',new Date().toISOString().replace(/[:.]/g,'-'));
let root:string;const artifacts=new Set<string>();
const hash=(v:unknown)=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
const request=(url:string,body:unknown)=>new Request('http://localhost'+url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const reason='模拟土木工程师复核意见（仅测试，不是专业签认）：\n一、请明确整体风险等级与各等级观测次数是不同口径，观测次数不是测点数量；未知原因要用中文说明为未提供反向控制要求，不能把弃权次数写成原因。\n二、这是日报，附表S保留当日全部观测明细，不能描述成周期最严重原观测或期末值；正文只是从原始明细选取关键观测，不能代表已完整分析日内过程。\n三、结论附近概括规范目录已逐本核查，区分本工程适用候选与范围或效力受限项，引用仍须原页复核；不得说所有目录规范均作为数值阈值。\n四、简化重复工况描述，保留模拟属性和缺少施工日志、巡视资料的限制。所有意见仅要求改进报告表达与复核建议，不要求擅改实测值、等级、控制值或伪造现场核验。';

beforeAll(()=>{
 if(!enabled)return;
 root=mkdtempSync(join(tmpdir(),'tunnel-engineer-feedback-'));mkdirSync(output,{recursive:true});
 for(const [key,value] of Object.entries({EXCAVAGUARD_ACCESS_FILE:join(root,'access.json'),EXCAVAGUARD_ACCESS_PASSWORD:'',EXCAVAGUARD_PROJECT_ID:DEFAULT_PROJECT_ID,EXCAVAGUARD_STORAGE_PROVIDER:'local',EXCAVAGUARD_UPLOAD_ROOT:join(root,'uploads'),EXCAVAGUARD_RUN_ROOT:join(root,'runs'),EXCAVAGUARD_STANDARD_CHANGES_ROOT:join(root,'changes'),EXCAVAGUARD_PROJECT_STANDARDS_ROOT:join(root,'standards'),EXCAVAGUARD_PROJECT_CONTEXT_ROOT:join(root,'context')}))vi.stubEnv(key,value);
 const directory=legacyDirectory();directory.projects[0].name='SIMULATED_工程师反馈修订测试';directory.projects[0].engineering={adapter_id:'tunnel-monitoring',adapter_version:loadEngineeringAdapter('tunnel-monitoring').adapter.version,parameters:JSON.parse(readFileSync(join(base,'工程参数_SIMULATED.json'),'utf8'))};
 writeFileSync(join(root,'access.json'),JSON.stringify(directory));
});
afterAll(()=>{if(!enabled)return;vi.unstubAllEnvs();if(root)rmSync(root,{recursive:true,force:true});for(const dir of artifacts)rmSync(dir,{recursive:true,force:true});});

it.skipIf(!enabled)('模拟工程师真实退回、关联AI重编、逐项回应、历史不可变和修订报告下载',async()=>{
 const at=Date.now();const name='SIMULATED_隧道监测_7天_10分钟_多工作表.xlsx';
 const form=new FormData();form.set('file',new File([readFileSync(join(base,name))],name));
 const uploaded=await uploadAPI(new Request('http://localhost/api/monitoring-files',{method:'POST',body:form}));expect(uploaded.status).toBe(201);const file=(await uploaded.json()).file;
 const body={project_id:DEFAULT_PROJECT_ID,monitoring_file_id:file.file_id,report_date:'2026-11-17',context:{},options:{generate_report:true,report_mode:'ai'}};
 async function run(input:unknown,label:string){
  const response=await runAPI(request('/api/runs',input));const data=await response.json();
  expect(response.status,JSON.stringify(data.error)).toBe(200);const record=data.record;
  const state=record.result?.agent_run?.state;
  const target=join(output,label);mkdirSync(target,{recursive:true});
  if(state?.report_draft)for(const a of state.report_draft.artifacts){artifacts.add(dirname(resolve(a.relative_path)));copyFileSync(resolve(a.relative_path),join(target,a.file_name));}
  writeFileSync(join(target,'运行与审查.json'),JSON.stringify({run_id:record.run_id,revision:record.revision,error:record.error,terminal:record.result?.agent_run?.terminal_action,audit:state?.audit_result,trace:state?.trace,feedback:state?.revision_feedback,analysis:state?.analysis_snapshot?.artifact?.payload},null,2));
  expect(record.error,JSON.stringify(record.error)).toBeNull();
  expect(state?.audit_result?.valid,JSON.stringify(record.result?.agent_run?.terminal_action)).toBe(true);
  expect(state.audit_result.stages).toEqual({deterministic:'passed',semantic:'passed'});
  expect(state.evidence_snapshot.artifact.payload.coverage.standards).toHaveLength(16);
  writeFileSync(join(target,'正文结构.json'),JSON.stringify(state.report_draft.payload.sections.narrative,null,2));
  return record;
 }
 const parent=await run(body,'修订前');const draft=parent.result.agent_run.state.report_draft;
 const immutablePath=join(root,'runs',parent.run_id,`${parent.revision}.json`);const originalRevision=readFileSync(immutablePath);
 const originalFiles=draft.artifacts.map((a:{relative_path:string})=>({path:a.relative_path,bytes:readFileSync(resolve(a.relative_path))}));
 const evaluations=['SIM10-T1-P2','SIM10-T1-P5','SIM10-T4-P6'].map((point,index)=>{
  const risk_item_index=parent.result.payload.items.findIndex((r:{point_id:string;timestamp:string})=>r.point_id===point&&r.timestamp.includes('23:50:00'));
  expect(risk_item_index).toBeGreaterThanOrEqual(0);
  return {risk_item_index,disposition:'follow_up_required',comment:[
   '请对该末次地表沉降分别说明累计值已触发项目测试控制要求、变化速率未触发，避免将该点概括成累计与速率均超限；使用冻结事实，不重新定级。',
   '该点为厘米输入，规范化后的累计值仍超限；请说明本次变化为零并不等于累计风险解除，不能以平台不再变化判为安全。',
   '请对收敛预警提出核对原始观测、测向和现场工况的复核建议；未提供现场资料，不推断已经支护失稳，不伪造已复测或已处置。',
  ][index]};
 });
 const reviewBody={expected_revision:parent.revision,draft_ref:draft.ref,decision:'needs_changes',reason,evaluations};
 writeFileSync(join(output,'模拟工程师意见.json'),JSON.stringify(reviewBody,null,2));
 writeFileSync(join(output,'模拟工程师意见.md'),'# 模拟土木工程师复核意见\n\n'+reason+'\n\n'+evaluations.map((e,i)=>`意见${i+1}：${e.comment}`).join('\n\n'));
 const response=await reviewAPI(request(`/api/runs/${parent.run_id}/review`,reviewBody),{params:Promise.resolve({runId:parent.run_id})});const reviewed=await response.json();
 expect(response.status,JSON.stringify(reviewed.error)).toBe(200);expect(reviewed.record.review.decision).toBe('needs_changes');
 const stale=await reviewAPI(request(`/api/runs/${parent.run_id}/review`,reviewBody),{params:Promise.resolve({runId:parent.run_id})});expect(stale.status).toBe(409);
 const oldDownload=await downloadAPI(new Request('http://localhost/api/report-artifacts/test'),{params:Promise.resolve({draftId:draft.ref.artifact_id,fileName:draft.artifacts[0].file_name})});expect(oldDownload.status).toBe(404);
 const child=await run({...body,parent_run_id:parent.run_id},'修订后');const state=child.result.agent_run.state;
 expect(child.request.parent_run_id).toBe(parent.run_id);
 const feedback=state.revision_feedback.payload;expect(feedback.parent_run_id).toBe(parent.run_id);expect(feedback.parent_revision).toBe(reviewed.record.revision);expect(feedback.items).toHaveLength(4);
 const responses=state.analysis_snapshot.artifact.payload.narrative.feedback_responses;
 expect(responses.map((r:{feedback_id:string})=>r.feedback_id).sort()).toEqual(feedback.items.map((r:{feedback_id:string})=>r.feedback_id).sort());
 expect(responses.every((r:{status:string})=>r.status==='addressed')).toBe(true);
 expect(child.result.payload.items).toEqual(parent.result.payload.items);expect(child.result.payload.summary).toEqual(parent.result.payload.summary);
 expect(child.result.payload.project.professional_parameters).toEqual(parent.result.payload.project.professional_parameters);
 expect(state.report_draft.payload.sections.narrative).not.toEqual(draft.payload.sections.narrative);
 expect(state.report_draft.artifacts[0].sheets).toEqual(expect.arrayContaining(['工程师意见回应','修订前后对照','规范检索覆盖']));
 const fetched=await runGET(new Request('http://localhost/api/runs/test'),{params:Promise.resolve({runId:parent.run_id})});const previous=await fetched.json();expect(previous.record.revision).toBe(reviewed.record.revision);
 expect(readFileSync(immutablePath).equals(originalRevision)).toBe(true);for(const old of originalFiles)expect(readFileSync(resolve(old.path)).equals(old.bytes)).toBe(true);
 for(const a of state.report_draft.artifacts){const download=await downloadAPI(new Request('http://localhost/api/report-artifacts/test'),{params:Promise.resolve({draftId:state.report_draft.ref.artifact_id,fileName:a.file_name})});expect(download.status,await download.clone().text()).toBe(200);expect(createHash('sha256').update(new Uint8Array(await download.arrayBuffer())).digest('hex')).toBe(a.sha256);}
 const check={passed:true,mode:'真实模型与真实本地RAG，工程师身份为测试模拟',parent_run_id:parent.run_id,parent_revision:reviewed.record.revision,child_run_id:child.run_id,feedback_items:feedback.items.length,addressed_items:responses.length,observations:child.result.payload.items.length,facts_unchanged:hash(child.result.payload.items)===hash(parent.result.payload.items),risk_summary:child.result.payload.summary,original_revision_unchanged:true,original_report_files_unchanged:true,stale_review_rejected:true,returned_report_download_blocked:true,revised_artifacts_downloaded:3,standards_count:state.evidence_snapshot.artifact.payload.coverage.catalogue_count,model_calls_before:parent.result.agent_run.state.limits.model_calls_used,model_calls_after:state.limits.model_calls_used,elapsed_ms:Date.now()-at,parent_revision_files:readdirSync(join(root,'runs',parent.run_id)).filter(n=>n.endsWith('.json')).length};
 writeFileSync(join(output,'路线验收结果.json'),JSON.stringify(check,null,2));
},600000);
