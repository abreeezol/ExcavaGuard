import {test,after} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,rmSync,existsSync,copyFileSync,mkdirSync,writeFileSync,mkdtempSync,symlinkSync,renameSync,unlinkSync} from 'node:fs';
import {resolve,dirname,join} from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import {readStandardCatalog} from '@/server/evidence/standard-catalog';
import {reviewAllStandards,retainDiverseEvidence} from '@/server/agents/standard-review';
import {standardCitation,evidenceReferences,evidenceSourceLocation} from '@/contracts/evidence-display';
import {runJudgement} from '@/server/skills/evaluate-thresholds/runner';
import {executeAgentRun} from '@/server/agents/executor';
import {validateReport} from '@/server/skills/validate-report/runner';
import {spawn} from 'node:child_process';
import {tmpdir} from 'node:os';
import {readReportFile} from '@/server/storage/report-files';

const catalog=readStandardCatalog();
const topics=['监测预警值设计方确认','A：水平位移、竖向位移','D：支撑轴力、锚杆轴力'];
const dirs=[];
after(()=>{for(const dir of dirs)rmSync(dir,{recursive:true,force:true});});
const localPythons=process.platform==='win32' ? ['.tools/windows-python/Scripts/python.exe','.venv/Scripts/python.exe'] : ['.venv/bin/python'];
process.env.EXCAVAGUARD_PYTHON ||= localPythons.map(p=>resolve(p)).find(existsSync) ?? (process.platform==='win32'?'python':'python3');
const payload={project:{safety_level:'一级',support_type:'地下连续墙'},summary:{overall_risk_level:'预警'}};
function item(code='GB50497-2019',id='SIMULATED-hidden-chunk-0001',text='基坑水平位移监测应复测并核对预警值。',score=1) {
 return {id,text,score,matched_terms:[],provider:'local',metadata:{standard_name:catalog.find(s=>s.standard_version===code)?.standard_name ?? 'SIMULATED-规范',standard_version:code,clause:'SIMULATED-clause',source_location:`SIMULATED-source.txt#chunk=${id}`,effective_status:'active',applicability:['SIMULATED_仅测试，不是规范原文']}};
}
function response(request,evidence=[]) {
 return {status:'success',evidence,notice:'SIMULATED_response',trace:{provider:'local',query:request.query,filters:request.filters,limit:request.limit,hit_count:evidence.length,evidence_ids:evidence.map(e=>e.id)}};
}

test('catalog covers all 29 unique registered codes and resolves duplicated source category',()=>{
 assert.equal(catalog.length,29);assert.equal(new Set(catalog.map(s=>s.standard_version)).size,29);
 const registry=JSON.parse(readFileSync('确定性计算层/standards/default/规范库索引.json','utf8'));
 assert.deepEqual(new Set(catalog.map(s=>s.standard_version)),new Set(registry.standards.map(s=>s.code)));
 assert.ok(catalog.every(s=>s.standard_name && s.effective_status==='active'));
});

test('every standard receives an independent filter plus all unfiltered metric themes',async()=>{
 const requests=[];let active=0,peak=0;
 const result=await reviewAllStandards({topics,enginePayload:payload,search:async request=>{
  active++;peak=Math.max(peak,active);await new Promise(r=>setTimeout(r,1));active--;requests.push(request);
  const code=request.filters.standard_versions?.[0];return response(request,code?[item(code,'SIMULATED-'+code)]:[]);
 }});
 assert.equal(requests.length,29+topics.length);assert.ok(peak<=8 && peak>4);
 assert.deepEqual(new Set(requests.flatMap(r=>r.filters.standard_versions??[])),new Set(catalog.map(s=>s.standard_version)));
 assert.equal(result.coverage.queried_count,29);assert.equal(result.coverage.completed,true);
 assert.equal(new Set(result.evidence.map(e=>e.metadata.standard_version)).size,29);
 assert.equal(result.coverage.standards.filter(s=>s.status==='matched').length,29);
 assert.ok(requests.filter(r=>!r.filters.standard_versions).every(r=>r.filters.effective_status==='active'));
});

test('rolling workers refill behind a slow request and serialize progress callbacks',async()=>{
 let launched=0,progressActive=0,progressPeak=0,reachedNinth=false,release;
 const slow=new Promise(resolvePromise=>{release=resolvePromise;});
 const timer=setTimeout(()=>release(),200);
 try {
  await reviewAllStandards({topics,enginePayload:payload,search:async request=>{
   const number=++launched;
   if(number===1)await slow;
   if(number===9){reachedNinth=true;release();}
   return response(request);
  },onQuery:async()=>{progressActive++;progressPeak=Math.max(progressPeak,progressActive);await new Promise(r=>setTimeout(r,1));progressActive--;}});
  assert.equal(reachedNinth,true);assert.equal(progressPeak,1);assert.ok(launched>8);
 } finally {clearTimeout(timer);release();}
});

test('checkpoint failure stops scheduling and drains in-flight reads',async()=>{
 let launched=0;
 await assert.rejects(reviewAllStandards({topics,enginePayload:payload,search:async request=>{launched++;return response(request);},onQuery:async()=>{throw new Error('SIMULATED checkpoint failure');}}),/checkpoint failure/);
 assert.equal(launched,8);
});

test('no hit, irrelevant, inactive, wrong-version and non-normative candidates are disclosed',async()=>{
 const only=catalog.slice(0,1),code=only[0].standard_version;
 for(const candidates of [[],[item(code,'bad','办公电脑应安装软件。')],[{...item(code),metadata:{...item(code).metadata,effective_status:'inactive'}}],[item('GB50497-2019')],[item(code,'bad','水平位移观测记录在表中。')]]) {
  const result=await reviewAllStandards({topics,enginePayload:payload,catalog:only,search:async request=>response(request,candidates)});
  assert.equal(result.evidence.length,0);assert.equal(result.coverage.standards[0].status,'no_relevant_hit');
  assert.match(result.gaps.join(' '),/不能认定无要求/);
 }
});

test('inactive and unknown catalog entries are not cited even if a provider labels them active',async()=>{
 const list=catalog.slice(0,2).map((s,i)=>({...s,effective_status:i?'unknown':'inactive'}));const requests=[];
 const result=await reviewAllStandards({topics,enginePayload:payload,catalog:list,search:async request=>{requests.push(request);return response(request,list.map(s=>item(s.standard_version)));}});
 assert.equal(requests.filter(r=>r.filters.standard_versions).length,0);assert.equal(result.evidence.length,0);
 assert.equal(result.coverage.queried_count,0);assert.ok(result.coverage.standards.every(s=>s.status==='skipped_status'));
});

test('round-robin retains minority standard, deduplicates and records bounded output',async()=>{
 const many=[...Array.from({length:105},(_,i)=>item('GB50497-2019','SIMULATED-gb-'+i,'水平位移监测应复测。',100-i)),item('JGJ120-2012','SIMULATED-jgj','基坑支护应复核。',.01)];
 const retained=retainDiverseEvidence([...many,many[0]],10);
 assert.equal(retained.length,10);assert.ok(retained.some(e=>e.metadata.standard_version==='JGJ120-2012'));
 assert.equal(new Set(retained.map(e=>e.id)).size,10);
 const result=await reviewAllStandards({topics:Array.from({length:26},(_,i)=>'主题'+i),enginePayload:payload,catalog:[catalog[0]],search:async request=>response(request,Array.from({length:4},(_,i)=>item(catalog[0].standard_version,'SIMULATED-'+randomUUID()+i)))});
 assert.equal(result.evidence.length,96);assert.ok(result.coverage.omitted_count>0);
});

test('one ID with conflicting content or source is rejected',()=>{
 assert.throws(()=>retainDiverseEvidence([item(),item('JGJ120-2012')]),/EVIDENCE_CONFLICT/);
});

test('unavailable query retains completed callbacks and never returns complete coverage',async()=>{
 const traces=[];
 await assert.rejects(reviewAllStandards({topics,enginePayload:payload,search:async request=>({...response(request),status:'abstained',code:'EVIDENCE_UNAVAILABLE',message:'SIMULATED outage'}),onQuery:async r=>{traces.push(r);}}),/EVIDENCE_UNAVAILABLE/);
 assert.equal(traces.length,8);assert.ok(traces.every(q=>q.code==='EVIDENCE_UNAVAILABLE'));
});

test('display labels retain standard name, code and clause while hiding chunk IDs',()=>{
 const evidence=item();const label=standardCitation(evidence.metadata);
 assert.match(label,/建筑基坑工程监测技术标准/);assert.match(label,/GB50497-2019/);
 assert.equal(evidenceReferences([evidence.id],[evidence]),label);
 assert.equal(evidenceReferences(['missing'],[evidence]),'规范来源待复核');
 assert.equal(evidenceSourceLocation(evidence.metadata.source_location),'SIMULATED-source.txt');
});

function modelResponse(request) {
 const ctx=request.context;
 const refs=ctx.evidence?.evidence?.slice(0,2).map(e=>e.id)??[];
 const p=(text='请工程师复核规范适用性。')=>({text,evidence_ids:refs});
 return {object:request.role==='supervisor'?{focus_indices:[0],evidence_topics:ctx.evidence_topics}:request.role==='audit'?{issues:[]}:{
  work_condition:p('施工日志未提供，不能确认现场工况。'),
  analysis:[p('{{fact:items.0.point_id}}成果见冻结事实，本期风险为{{fact:summary.overall_risk_level}}，需核对多规范适用条件。')],
  recommendations:[p()],limitations:[p('仅核查已配置知识库候选，无命中项目仍需人工查证。')],
  appendix_analysis:ctx.forms.map(form=>({form,analysis:p('本表成果和风险来自冻结事实。'),recommendation:p()})),
 },model:'SIMULATED-offline-model',usage:{input_tokens:1,output_tokens:1}};
}

async function realArtifacts(period=false,live=false,realModel=false) {
 const engine=await runJudgement({filePath:resolve('final_test/监测数据整合_7天_10分钟输入.xlsx'),reportDate:period?'2026-10-11':'2026-10-08',
  ...(period?{reportPeriod:{type:'weekly',start_date:'2026-10-05',end_date:'2026-10-11'}}:{}),
  context:{safety_level:'一级',support_type:'地下连续墙',excavation_depth_m:20},project:{name:live?'SIMULATED_多规范真实RAG验收':'SIMULATED_多规范离线验收'}});
 const calls=[];
 const result=await executeAgentRun({enginePayload:engine.result,reportMode:'ai'}, {
  ...(!live?{retrieve:async request=>{const code=request.filters?.standard_versions?.[0]??'JGJ120-2012';return response(request,[item(code,'SIMULATED-'+code)]);}}:{}),
  ...(!realModel?{model:async request=>{calls.push(request);return modelResponse(request);}}:{}),
 });
 const draft=result.state.report_draft;if(draft)dirs.push(dirname(resolve(draft.artifacts[0].relative_path)));
 assert.equal(result.terminalAction.reason_code,'AUDIT_PASSED',JSON.stringify({terminal:result.terminalAction,trace:result.state.trace.map(t=>({capability:t.capability,error:t.error}))}));
 assert.deepEqual(result.state.engine_snapshot.payload,engine.result);
 const frozen=result.state.evidence_snapshot.artifact.payload;
 assert.equal(frozen.coverage.queried_count,29);assert.ok(new Set(frozen.evidence.map(e=>e.metadata.standard_version)).size>1);
 if(live) {
  const {buildPineconeStandardRecords,readChunksJsonl,readRegistry,readStatusManifest}=await import('../tools/rag/standard-records.ts');
  const source=buildPineconeStandardRecords({chunks:readChunksJsonl(resolve('data/chunks.jsonl')),registry:readRegistry(resolve('确定性计算层/standards/default/规范库索引.json')),statusManifest:readStatusManifest(resolve('rag/standard-status.json'))});
  const byId=new Map(source.records.map(r=>[r._id,r]));
  for(const evidence of frozen.evidence) {
   const original=byId.get(evidence.id);assert.ok(original,'RAG ID must exist in the audited source corpus');
   assert.equal(evidence.text,original.chunk_text);
   for(const field of ['standard_name','standard_version','clause','source_location','applicability','effective_status']) assert.deepEqual(evidence.metadata[field],original[field]);
  }
 }
 const book=draft.artifacts.find(a=>a.kind==='workbook');assert.ok(book.sheets.includes('规范证据索引'));assert.ok(book.sheets.includes('规范检索覆盖'));assert.ok(book.sheets.includes('多规范要求对照'));
 for(const id of frozen.evidence.map(e=>e.id)) assert.ok(!draft.payload.markdown.includes(id),`hidden ID leaked: ${id}`);
 const appendix=readFileSync(resolve(draft.artifacts.find(a=>a.kind==='appendices_markdown').relative_path),'utf8');
 for(const id of frozen.evidence.map(e=>e.id)) assert.ok(!appendix.includes(id),`hidden ID leaked into appendix: ${id}`);
 assert.match(appendix,/建筑基坑工程监测技术标准/);
 if(!realModel) {
  assert.deepEqual(calls.map(r=>r.role),['supervisor','report-delivery','audit']);
  const audit=calls.find(r=>r.role==='audit').context;
  assert.ok(!audit.draft.markdown.includes('按附表分项统计'));
  assert.ok(!audit.draft.markdown.includes('规范目录覆盖'));
  assert.ok(audit.draft.markdown.includes('work_condition'));
  assert.ok(audit.numeric_judgment_sources.length>0);
  assert.equal(audit.facts['items.0.risk_level'],engine.result.items[0].risk_level,'a referenced point must retain its full risk context, even when prose only binds its ID');
  assert.ok(!Object.keys(audit.facts).some(p=>p.startsWith('items.84.')),'unused point facts must not invite a recount');
 }
 if(live && process.env.EXCAVAGUARD_KEEP_STANDARD_PREVIEW==='1') {
  const folder=resolve('../process_file/多规范检索验收',realModel?'真实模型与RAG':'真实RAG_模型模拟');mkdirSync(folder,{recursive:true});
  for(const artifact of draft.artifacts)copyFileSync(resolve(artifact.relative_path),resolve(folder,artifact.file_name));
  writeFileSync(resolve(folder,'检索与审计结果.json'),JSON.stringify({coverage:frozen.coverage,evidence:frozen.evidence,comparisons:frozen.comparisons,audit:result.state.audit_result,trace:result.state.trace},null,2));
 }
 if(live)console.info(JSON.stringify({period,realModel,queried:frozen.coverage.queried_count,evidence:frozen.evidence.length,standards:[...new Set(frozen.evidence.map(e=>e.metadata.standard_version))],draft_id:draft.ref.artifact_id,audit:result.state.audit_result.valid}));
 return {result,engine};
}

test('85-channel daily AI orchestration uses diverse sources with real Python renderer and auditor',async()=>{await realArtifacts();});
test('85-channel weekly report preserves period facts and readable evidence in all artifacts',async()=>{await realArtifacts(true);});
async function python(code,args) {
 return new Promise((resolvePromise,reject)=>{
  const child=spawn(process.env.EXCAVAGUARD_PYTHON,['-c',code,...args],{stdio:['ignore','pipe','pipe']});let stdout='',stderr='';
  const timer=setTimeout(()=>{child.kill('SIGKILL');reject(new Error('Python workbook check timed out'));},30000);
  child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');child.stdout.on('data',s=>stdout+=s);child.stderr.on('data',s=>stderr+=s);
  child.on('error',error=>{clearTimeout(timer);reject(error);});child.on('close',exit=>{clearTimeout(timer);try{assert.equal(exit,0,stderr);resolvePromise(JSON.parse(stdout));}catch(error){reject(error);}});
 });
}

test('Excel and appendix references hide IDs; a changed source name fails independent cell audit',async()=>{
 const {result}=await realArtifacts();const draft=structuredClone(result.state.report_draft);
 const book=draft.artifacts.find(a=>a.kind==='workbook');
 const ids=result.state.evidence_snapshot.evidence_ids;
 const inspection=await python(`import sys,json,openpyxl
p=sys.argv[1];ids=json.loads(sys.argv[2]);w=openpyxl.load_workbook(p)
leaks=[(s.title,c.coordinate) for s in w for row in s for c in row if isinstance(c.value,str) and any(i in c.value for i in ids)]
names=[w['规范证据索引'].cell(r,1).value for r in range(3,w['规范证据索引'].max_row+1)]
w['规范证据索引']['A3']='错误规范名称';w.save(p);w.close()
print(json.dumps({'leaks':leaks,'names':names},ensure_ascii=False))`,[resolve(book.relative_path),JSON.stringify(ids)]);
 assert.deepEqual(inspection.leaks,[]);assert.ok(inspection.names.every(n=>n.startsWith('《')));
 const bytes=readFileSync(resolve(book.relative_path));book.sha256=createHash('sha256').update(bytes).digest('hex');book.size_bytes=bytes.length;
 const {audit}=await validateReport({draft,engineSnapshot:result.state.engine_snapshot,evidenceSnapshot:result.state.evidence_snapshot,analysisSnapshot:result.state.analysis_snapshot});
 assert.equal(audit.valid,false);assert.ok(audit.issues.some(issue=>issue.code==='WORKBOOK_CELL_MISMATCH'));
});

test('changed report source metadata is rejected against frozen evidence snapshot',async()=>{
 const {result}=await realArtifacts();const draft=structuredClone(result.state.report_draft);
 draft.payload.sections.standard_evidence.items[0].metadata.standard_name='错配规范名称';
 const {audit}=await validateReport({draft,engineSnapshot:result.state.engine_snapshot,evidenceSnapshot:result.state.evidence_snapshot,analysisSnapshot:result.state.analysis_snapshot});
 assert.equal(audit.valid,false);assert.ok(audit.issues.length);
});

test('canonical workspace aliases can download while report-file symlinks remain blocked',{skip:process.platform==='win32'?'POSIX symlink probe; Windows mapped-drive download covered by Vitest':false},async()=>{
 const {result}=await realArtifacts();const book=result.state.report_draft.artifacts.find(a=>a.kind==='workbook');
 const originalCwd=process.cwd();const temp=mkdtempSync(join(tmpdir(),'excavaguard-root-alias-'));dirs.push(temp);
 const alias=join(temp,'repo');symlinkSync(originalCwd,alias,'dir');
 const oldProvider=process.env.EXCAVAGUARD_STORAGE_PROVIDER;process.env.EXCAVAGUARD_STORAGE_PROVIDER='local';
 try {
  process.chdir(alias);assert.ok((await readReportFile(book)).length>1000);process.chdir(originalCwd);
  const path=resolve(book.relative_path),original=path+'.original';renameSync(path,original);
  try { symlinkSync(original,path);await assert.rejects(readReportFile(book),error=>error.code==='FILE_NOT_FOUND'); }
  finally { unlinkSync(path);renameSync(original,path); }
 } finally {process.chdir(originalCwd);if(oldProvider===undefined)delete process.env.EXCAVAGUARD_STORAGE_PROVIDER;else process.env.EXCAVAGUARD_STORAGE_PROVIDER=oldProvider;}
});

test('real Pinecone catalog retrieval and report audit (external model explicitly simulated)',{skip:process.env.EXCAVAGUARD_TEST_STANDARD_LIVE!=='1'},async()=>{await realArtifacts(false,true);});
test('real models and real Pinecone end-to-end',{skip:process.env.EXCAVAGUARD_TEST_STANDARD_MODEL!=='1'},async()=>{await realArtifacts(false,true,true);});
