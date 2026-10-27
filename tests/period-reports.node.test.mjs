import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join, dirname } from 'node:path';
import { spawn } from 'node:child_process';
import { presetReportPeriod, reportPeriodSchema } from '@/contracts/report-period';
import { createRunRequestSchema } from '@/contracts/runs';
import { reviewRecurringWarnings } from '@/server/agents/period-evidence';

const sandbox=mkdtempSync(join(tmpdir(),'excavaguard-period-test-'));
process.env.EXCAVAGUARD_STORAGE_PROVIDER='local';
process.env.EXCAVAGUARD_UPLOAD_ROOT=join(sandbox,'uploads');
process.env.EXCAVAGUARD_RUN_ROOT=join(sandbox,'runs');
const localPythons=process.platform==='win32' ? ['.tools/windows-python/Scripts/python.exe','.venv/Scripts/python.exe'] : ['.venv/bin/python'];
process.env.EXCAVAGUARD_PYTHON ||= localPythons.map(p=>resolve(p)).find(existsSync) ?? (process.platform==='win32'?'python':'python3');
const artifacts=[];
after(()=> { rmSync(sandbox,{recursive:true,force:true}); for(const dir of artifacts) rmSync(dir,{recursive:true,force:true}); });
const spec={type:'weekly',start_date:'2026-10-02',end_date:'2026-10-08'};
const context={safety_level:'一级',support_type:'地下连续墙',excavation_depth_m:20};
const records=[0,5,12,22,35,52,60,62].map((value,index)=>({point_id:'W-01',metric_key:'wall_top_horizontal_displacement',timestamp:`2026-10-0${index+1}`,value,unit:'mm',data_origin:'simulated'}));
async function pythonPayload() {
 return new Promise((resolvePromise,reject)=>{
  const child=spawn(process.env.EXCAVAGUARD_PYTHON,['skills/evaluate-thresholds/scripts/run_judgement.py'],{stdio:['pipe','pipe','pipe'],env:process.env});
  let stdout='',stderr='';
  const timer=setTimeout(()=>{child.kill('SIGKILL');reject(new Error('Python period test timed out: '+stderr));},30000);
  child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');
  child.stdout.on('data',chunk=>stdout+=chunk);child.stderr.on('data',chunk=>stderr+=chunk);
  child.on('error',error=>{clearTimeout(timer);reject(error);});
  child.on('close',code=>{clearTimeout(timer);try{assert.equal(code,0,stdout+stderr);resolvePromise(JSON.parse(stdout).result);}catch(error){reject(error);}});
  child.stdin.end(JSON.stringify({records,context,options:{report_period:spec,report_date:spec.end_date,project:{name:'SIMULATED_周期验收'}}}));
 });
}
const recurringPayload=await pythonPayload();

function evidence(id='SIMULATED-extra', version='JGJ120-2012',status='active',text='水平位移连续出现预警时应加密监测频率，复测并进行现场复核。') {
 return { id,text,provider:'local',score:1,matched_terms:['水平位移'],metadata:{standard_name:'SIMULATED_测试规范',standard_version:version,clause:'SIMULATED-clause',source_location:'SIMULATED_仅供检索测试',applicability:['水平位移'],effective_status:status} };
}
function resultFor(request, items=[]) {
 return {status:'success',evidence:items,notice:'SIMULATED_test',trace:{provider:'local',query:request.query,filters:request.filters,limit:request.limit,hit_count:items.length,evidence_ids:items.map(x=>x.id)}};
}

test('weekly, natural month including leap year, custom and legacy API validation',()=> {
 assert.deepEqual(presetReportPeriod('weekly','2026-10-08'),spec);
 assert.deepEqual(presetReportPeriod('monthly','2024-02-15'),{type:'monthly',start_date:'2024-02-01',end_date:'2024-02-29'});
 assert.equal(reportPeriodSchema.safeParse({type:'custom',start_date:'2026-10-08',end_date:'2026-10-01'}).success,false);
 assert.equal(reportPeriodSchema.safeParse({...spec,end_date:'2026-10-09'}).success,false);
 assert.throws(()=>presetReportPeriod('monthly','2026-02-30'));
 const req={project_id:'11111111-1111-4111-8111-111111111111',monitoring_file_id:'22222222-2222-4222-8222-222222222222',report_date:spec.end_date,context};
 assert.equal(createRunRequestSchema.safeParse(req).success,true);
 assert.equal(createRunRequestSchema.safeParse({...req,report_period:spec}).success,true);
 assert.equal(createRunRequestSchema.safeParse({...req,report_date:'2026-10-07',report_period:spec}).success,false);
});

test('daily reports do not trigger extra searches', async()=> {
 let calls=0; const result=await reviewRecurringWarnings({schema:'excavaguard.daily_report_input/v1'},[],async(r)=>{calls++;return resultFor(r);});
 assert.equal(calls,0); assert.equal(result.review.triggered,false);
});

test('multi-day warning widens versions, retains active gate and records new evidence IDs',async()=> {
 const requests=[]; const result=await reviewRecurringWarnings(recurringPayload,['SIMULATED-old'],async(r)=>{requests.push(r);return resultFor(r,[evidence()]);});
 assert.equal(requests.length,1); assert.deepEqual(requests[0].filters,{effective_status:'active'});
 assert.match(requests[0].query,/连续多日/); assert.equal(result.review.status,'additional_candidates');
 assert.deepEqual(result.review.checks[0].additional_evidence_ids,['SIMULATED-extra']);
 assert.equal(result.review.checks[0].requires_human_review,true);
});

test('empty, irrelevant and inactive hits never prove absence of additional requirements',async()=> {
 for(const items of [[],[evidence('x','JGJ120-2012','inactive')],[evidence('x','JGJ120-2012','active','办公电脑应安装软件。')]]) {
  const result=await reviewRecurringWarnings(recurringPayload,[],async(r)=>resultFor(r,items));
  assert.equal(result.review.status,'no_additional_evidence'); assert.equal(result.evidence.length,0);
  assert.ok(result.gaps.length); assert.match(result.review.notice,/不代表/);
 }
});

test('retrieval unavailable is explicit failure and cannot be delivered as a completed review',async()=> {
 await assert.rejects(reviewRecurringWarnings(recurringPayload,[],async(r)=>({...resultFor(r),status:'abstained',code:'EVIDENCE_UNAVAILABLE',message:'SIMULATED failure'})),/EVIDENCE_UNAVAILABLE/);
});

test('only recurring days, not a single warning day, trigger expanded retrieval',async()=> {
 const p=structuredClone(recurringPayload);p.period.recurring_warnings=p.period.recurring_warnings.map(w=>({...w,warning_days:1}));
 const result=await reviewRecurringWarnings(p,[],async()=>{throw new Error('must not call');});assert.equal(result.review.triggered,false);
});

test('period facts can be grounded in model context and cannot be overwritten by model prose',async()=> {
 const {buildReportModelContext,validateNarrativeGrounding}=await import('@/server/agents/report-model');
 const ctx=buildReportModelContext(recurringPayload);
 assert.equal(ctx.facts['period.calendar_days'],7);assert.ok(ctx.facts['period.channels.0.warning_days']>=2);
 const paragraph={text:'周期覆盖{{fact:period.calendar_days}}天。',evidence_ids:[]};
 const narrative={work_condition:paragraph,analysis:[paragraph],recommendations:[paragraph],limitations:[paragraph],appendix_analysis:ctx.forms.map(form=>({form,analysis:paragraph,recommendation:paragraph}))};
 assert.doesNotThrow(()=>validateNarrativeGrounding(narrative,ctx.facts,[],ctx.forms));
 assert.throws(()=>validateNarrativeGrounding({...narrative,analysis:[{text:'全部七天已确认安全，无需人工复核。',evidence_ids:[]}]},ctx.facts,[],ctx.forms));
});

test('upload -> period API -> actual Python artifacts -> audit -> download -> review and legacy daily compatibility',async()=> {
 const {POST:upload}=await import('@/app/api/monitoring-files/route');
 const {POST:run}=await import('@/app/api/runs/route');
 const {GET:download}=await import('@/app/api/report-artifacts/[draftId]/[fileName]/route');
 const {POST:review}=await import('@/app/api/runs/[runId]/review/route');
 const csv='point_id,timestamp,metric,value,unit,data_origin\n'+records.map(r=>`${r.point_id},${r.timestamp},${r.metric_key},${r.value},mm,simulated`).join('\n');
 const form=new FormData();form.set('file',new File([csv],'SIMULATED-period.csv',{type:'text/csv'}));
 const uploaded=await upload(new Request('http://localhost:3000/api/monitoring-files',{method:'POST',body:form}));
 assert.equal(uploaded.status,201);const file=(await uploaded.json()).file;
 const request={project_id:'11111111-1111-4111-8111-111111111111',monitoring_file_id:file.file_id,report_date:spec.end_date,report_period:spec,context,project:{name:'SIMULATED_周期API验收'},options:{generate_report:true,report_mode:'template'}};
 const response=await run(new Request('http://localhost:3000/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)}));
 const body=await response.json();assert.equal(response.status,200,JSON.stringify(body));
 assert.equal(body.payload.schema,'excavaguard.period_report_input/v1');
 assert.ok(body.record.result.agent_run.state.audit_result,JSON.stringify({terminal:body.record.result.agent_run.terminal_action,trace:body.record.result.agent_run.state.trace}));
 assert.equal(body.record.result.agent_run.state.audit_result.valid,true);
 const draft=body.record.result.agent_run.state.report_draft;
 artifacts.push(dirname(resolve(draft.artifacts[0].relative_path)));
 const book=draft.artifacts.find(a=>a.kind==='workbook');assert.match(book.file_name,/监测周报_2026-10-02_2026-10-08/);
 const downloadResponse=await download(new Request('http://localhost:3000'+body.record.result.agent_run.downloads[0].url),{params:Promise.resolve({draftId:draft.ref.artifact_id,fileName:book.file_name})});
 assert.equal(downloadResponse.status,200);assert.ok((await downloadResponse.arrayBuffer()).byteLength>1000);
 const approved=await review(new Request(`http://localhost:3000/api/runs/${body.run_id}/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_revision:body.record.revision,draft_ref:draft.ref,decision:'accepted',reason:'SIMULATED_自动化验收，不是工程签发'})}),{params:Promise.resolve({runId:body.run_id})});
 assert.equal(approved.status,200);
 const dailyRequest={...request};delete dailyRequest.report_period;dailyRequest.options={generate_report:false,report_mode:'template'};
 const dailyResponse=await run(new Request('http://localhost:3000/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(dailyRequest)}));
 assert.equal(dailyResponse.status,200);assert.equal((await dailyResponse.json()).payload.schema,'excavaguard.daily_report_input/v1');
 const invalidResponse=await run(new Request('http://localhost:3000/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...request,report_date:'2026-10-07'})}));
 assert.equal(invalidResponse.status,400);
});

// External models and retrieval use explicit SIMULATED doubles; renderer/auditor are real.
test('AI chain keeps baseline retrieval, adds multi-day review and audits real period artifacts',async()=> {
 const {executeAgentRun}=await import('@/server/agents/executor');
 const calls=[], searches=[];
 const paragraph=(text='请工程师结合现场工况复核。',ids=[])=>({text,evidence_ids:ids});
 const result=await executeAgentRun({enginePayload:recurringPayload,reportMode:'ai'}, {
  retrieve:async request=> { searches.push(request);return resultFor(request,request.query.includes('连续多日') ? [evidence()] : []); },
  model:async request=> {
   calls.push(request);
   const ctx=request.context;
   const object=request.role==='supervisor' ? {focus_indices:[0],evidence_topics:ctx.evidence_topics} : request.role==='audit' ? {issues:[]} : {
    work_condition:paragraph('施工日志未提供，工况信息不足。'),
    analysis:[paragraph('本周期覆盖{{fact:period.calendar_days}}天，预警情况应结合逐日明细复核。')],
    recommendations:[paragraph('补充条文提示应加密监测并复测，具体适用性由工程师确认。',['SIMULATED-extra'])],
    limitations:[paragraph('仅核查现有知识库，不代表确认无其他规范要求。')],
    appendix_analysis:ctx.forms.map(form=>({form,analysis:paragraph(),recommendation:paragraph()})),
   };
   return {object,model:'SIMULATED-offline-test',usage:{input_tokens:10,output_tokens:20}};
  },
 });
 if(result.state.report_draft) artifacts.push(dirname(resolve(result.state.report_draft.artifacts[0].relative_path)));
 assert.equal(result.terminalAction.reason_code,'AUDIT_PASSED',JSON.stringify({terminal:result.terminalAction,trace:result.state.trace}));
 assert.deepEqual(calls.map(x=>x.role),['supervisor','report-delivery','audit']);
 assert.ok(searches.some(r=>r.filters.standard_versions?.includes('GB50497-2019')));
 assert.ok(searches.some(r=>!r.filters.standard_versions && !r.query.includes('连续多日')));
 assert.equal(searches.filter(r=>r.query.includes('连续多日')).length,1);
 assert.equal(result.state.evidence_snapshot.artifact.payload.coverage.queried_count,29);
 assert.equal(result.state.evidence_snapshot.artifact.payload.extended_review.status,'additional_candidates');
 assert.ok(calls.find(c=>c.role==='audit').context.evidence.evidence.some(e=>e.id==='SIMULATED-extra'));
 assert.equal(result.state.audit_result.valid,true);
 assert.deepEqual(result.state.engine_snapshot.payload,recurringPayload);
 assert.match(result.state.report_draft.payload.markdown,/补充条文候选/);
});

test('month and custom APIs generate audited downloadable reports and preserve missing coverage',async()=> {
 const {POST:upload}=await import('@/app/api/monitoring-files/route');
 const {POST:run}=await import('@/app/api/runs/route');
 const {GET:download}=await import('@/app/api/report-artifacts/[draftId]/[fileName]/route');
 const form=new FormData();form.set('file',new File(['point_id,timestamp,metric,value,unit,data_origin\n'+records.map(r=>`${r.point_id},${r.timestamp},${r.metric_key},${r.value},mm,simulated`).join('\n')],'SIMULATED-month.csv'));
 const uploaded=await upload(new Request('http://localhost/api/monitoring-files',{method:'POST',body:form}));
 assert.equal(uploaded.status,201);const file=(await uploaded.json()).file;
 for(const period of [{type:'monthly',start_date:'2026-10-01',end_date:'2026-10-31'},{type:'custom',start_date:'2026-10-03',end_date:'2026-10-09'}]) {
  const response=await run(new Request('http://localhost/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:'11111111-1111-4111-8111-111111111111',monitoring_file_id:file.file_id,report_date:period.end_date,report_period:period,context,options:{generate_report:true,report_mode:'template'}})}));
  const body=await response.json();assert.equal(response.status,200,JSON.stringify(body));
  const state=body.record.result.agent_run.state;
  if(state.report_draft) artifacts.push(dirname(resolve(state.report_draft.artifacts[0].relative_path)));
  assert.equal(state.audit_result?.valid,true,JSON.stringify(state.trace));
  assert.ok(body.payload.period.missing_dates.includes(period.end_date));
  for(const artifact of state.report_draft.artifacts) {
   const response=await download(new Request('http://localhost/api/report-artifacts/test'),{params:Promise.resolve({draftId:state.report_draft.ref.artifact_id,fileName:artifact.file_name})});
   assert.equal(response.status,200,artifact.file_name);
  }
 }
});

test('85-channel mixed wide workbook uses daily history without resetting cumulative values',async()=> {
 const {POST:upload}=await import('@/app/api/monitoring-files/route');
 const {POST:run}=await import('@/app/api/runs/route');
 const widePeriod={type:'weekly',start_date:'2026-10-05',end_date:'2026-10-11'};
 const form=new FormData();form.set('file',new File([readFileSync(resolve('final_test/监测数据整合_7天_10分钟输入.xlsx'))],'SIMULATED-wide-fixture.xlsx'));
 const uploaded=await upload(new Request('http://localhost/api/monitoring-files',{method:'POST',body:form}));
 assert.equal(uploaded.status,201);const file=(await uploaded.json()).file;
 const response=await run(new Request('http://localhost/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:'11111111-1111-4111-8111-111111111111',monitoring_file_id:file.file_id,report_date:widePeriod.end_date,report_period:widePeriod,context,options:{generate_report:true,report_mode:'template'}})}));
 const body=await response.json();assert.equal(response.status,200,JSON.stringify(body));
 const state=body.record.result.agent_run.state;
 if(state.report_draft) artifacts.push(dirname(resolve(state.report_draft.artifacts[0].relative_path)));
 assert.equal(state.audit_result?.valid,true,JSON.stringify({terminal:body.record.result.agent_run.terminal_action,trace:state.trace}));
 assert.equal(body.payload.period.channel_count,85);
 assert.equal(body.payload.period.observed_days,7);
 assert.equal(body.payload.period.daily_items.length,595);
 assert.ok(body.payload.period.unknown_observation_count>0);
 assert.match(body.payload.note,/日内极值未经独立风险判定/);
 const cumulative=body.payload.period.daily_items.find(i=>i.point_id==='B-DP-01');
 assert.equal(cumulative.baseline,0);
 assert.equal(cumulative.cumulative,cumulative.current);
});

test('general excavation monitoring frequency clauses are retained without forcing metric wording',async()=> {
 const clause=evidence('SIMULATED-general','JGJ120-2012','active','基坑工程出现监测报警时应加密监测频率并复测。');
 clause.metadata.applicability=['基坑工程'];
 const result=await reviewRecurringWarnings(recurringPayload,[],async r=>resultFor(r,[clause]));
 assert.equal(result.evidence[0]?.id,'SIMULATED-general');
});

test('expanded retrieval outage stops real AI orchestration before report rendering',async()=> {
 const {executeAgentRun}=await import('@/server/agents/executor');
 const calls=[];
 const result=await executeAgentRun({enginePayload:recurringPayload,reportMode:'ai'}, {
  model:async request=>{calls.push(request.role);return {object:{focus_indices:[0],evidence_topics:request.context.evidence_topics},model:'SIMULATED-offline-test',usage:{input_tokens:1,output_tokens:1}};},
  retrieve:async request=>!request.query.includes('连续多日') ? resultFor(request) : {...resultFor(request),status:'abstained',code:'EVIDENCE_UNAVAILABLE',message:'SIMULATED outage'},
 });
 assert.equal(result.terminalAction.type,'wait_for_capability');
 assert.equal(result.state.report_draft,null);
 assert.deepEqual(calls,['supervisor']);
 assert.deepEqual(result.state.engine_snapshot.payload,recurringPayload);
 assert.match(JSON.stringify(result.state.trace),/EVIDENCE_UNAVAILABLE/);
});
