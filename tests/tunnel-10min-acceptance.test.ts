import { beforeAll, afterAll, describe, it, expect, vi } from 'vitest';
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync, copyFileSync, existsSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { tmpdir } from 'node:os';
import { execFileSync } from 'node:child_process';
import { legacyDirectory } from '@/server/auth/directory';
import { DEFAULT_PROJECT_ID } from '@/contracts/access';
import { loadEngineeringAdapter } from '@/server/engineering-adapters/registry';
import { POST as uploadAPI } from '@/app/api/monitoring-files/route';
import { POST as runAPI } from '@/app/api/runs/route';

const base=resolve('final_test/tunnel-7day-10min/inputs');
const filename='SIMULATED_隧道监测_7天_10分钟_多工作表.xlsx';
const expected=existsSync(join(base,'预期逐条结果_SIMULATED.jsonl'))?readFileSync(join(base,'预期逐条结果_SIMULATED.jsonl'),'utf8').trim().split('\n').map(s=>JSON.parse(s)):[];
const expectedByKey=new Map(expected.map(r=>[`${r.point_id}|${r.timestamp}`,r]));
let root:string,fileId:string;const artifactDirs=new Set<string>();
const resultRoot=resolve('var/acceptance/tunnel-7day-10min');
const summaryPath=join(resultRoot,'验收汇总.json');
const results:Array<Record<string,unknown>>=existsSync(summaryPath)?JSON.parse(readFileSync(summaryPath,'utf8')):[];
interface Row {point_id:string;timestamp:string;metric_key:string;current:number;cumulative:number;single_change:number|null;rate:number|null;risk_level:string;needs_review:boolean;source_metadata:{source_sheet:string;source_row:number};}
interface Payload {items:Row[];period?:{daily_items:Row[];missing_dates:string[];observation_count:number};summary:unknown;}

function checkRows(rows:Row[],count:number) {
 expect(rows).toHaveLength(count);const seen=new Set<string>();
 for(const row of rows){
  const key=`${row.point_id}|${row.timestamp.slice(0,19)}`;const wanted=expectedByKey.get(key);
  expect(wanted,`未知观测${key}`).toBeTruthy();expect(seen.has(key)).toBe(false);seen.add(key);
  for(const field of ['current','cumulative','single_change','rate'] as const){
   if(wanted[field]===null)expect(row[field],`${key}/${field}`).toBeNull();
   else expect(row[field],`${key}/${field}`).toBeCloseTo(wanted[field],5);
  }
  expect(row.risk_level,`${key}/判级`).toBe(wanted.risk_level);
  expect(row.needs_review,`${key}/待核`).toBe(wanted.needs_review);
  expect(['地表沉降','建筑沉降','拱顶沉降','净空收敛']).toContain(row.source_metadata.source_sheet);
  expect(row.source_metadata.source_row).toBeGreaterThan(1);
 }
 return {checked_observations:count,matched_observations:seen.size,by_risk_level:Object.fromEntries(['正常','预警','未知'].map(level=>[level,rows.filter(r=>r.risk_level===level).length]))};
}

async function upload(name:string){
 const form=new FormData();form.set('file',new File([readFileSync(join(base,name))],name,{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}));
 const response=await uploadAPI(new Request('http://localhost/api/monitoring-files',{method:'POST',body:form}));
 expect(response.status).toBe(201);return response.json();
}

async function runReport(date:string,weekly:boolean,mode:'template'|'ai',generate=true){
 const at=Date.now();const response=await runAPI(new Request('http://localhost/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
  project_id:DEFAULT_PROJECT_ID,monitoring_file_id:fileId,report_date:date,context:{},
  ...(weekly?{report_period:{type:'weekly',start_date:'2026-11-11',end_date:'2026-11-17'}}:{}),
  options:{generate_report:generate,report_mode:mode},project:{name:'SIMULATED_七天十分钟隧道验收'},
 })}));const data=await response.json();expect(response.status,JSON.stringify(data.error)).toBe(200);
 const record=data.record;expect(record.error,JSON.stringify(record.error)).toBeNull();
 const payload=record.result.payload as Payload;
 const rows=weekly?payload.period!.daily_items:payload.items;
 const checked=checkRows(rows,weekly?24192:3456);
 expect(record.result.engine.source_records).toBe(24192);
 if(weekly)expect(payload.period!.missing_dates).toEqual([]);
 const label=weekly?`周报_${mode}`:`日报_${date}_${generate?mode:'计算'}`;
 const target=join(resultRoot,'outputs',label);mkdirSync(target,{recursive:true});
 writeFileSync(join(target,'计算结果.json'),JSON.stringify(payload,null,2));
 writeFileSync(join(target,'逐条核对.json'),JSON.stringify(checked,null,2));
 let coverage:unknown=null,modelCalls=0;
 if(generate){
  const state=record.result.agent_run.state;
  if(state.report_draft)for(const a of state.report_draft.artifacts){artifactDirs.add(dirname(resolve(a.relative_path)));copyFileSync(resolve(a.relative_path),join(target,a.file_name));}
  writeFileSync(join(target,'文件审计.json'),JSON.stringify(state.audit_result,null,2));
  expect(state.audit_result?.valid,JSON.stringify(record.result.agent_run.terminal_action)).toBe(true);
  const review=state.evidence_snapshot.artifact.payload;coverage=review.coverage;modelCalls=state.limits.model_calls_used;
  expect(review.coverage.catalogue_count).toBe(16);expect(review.coverage.standards).toHaveLength(16);expect(review.coverage.completed).toBe(true);
  expect(review.coverage.standards.every((s:{status:string})=>['matched','no_relevant_hit','skipped_scope','skipped_status'].includes(s.status))).toBe(true);
  const markdown=readFileSync(join(target,'隧道变形报告_封面.md'),'utf8');
  for(const entry of review.coverage.standards)expect(markdown).toContain(entry.standard_version);
  expect(state.report_draft.artifacts[0].sheets).toContain('规范检索覆盖');
  if(mode==='ai'){expect(modelCalls).toBeGreaterThanOrEqual(3);expect(state.audit_result.stages.semantic).toBe('passed');}
  writeFileSync(join(target,'规范逐本核查.json'),JSON.stringify(review,null,2));
 }
 const summary={label,...checked,elapsed_ms:Date.now()-at,model_calls:modelCalls,coverage};
 const previous=results.findIndex(r=>r.label===label);if(previous>=0)results.splice(previous,1);
 results.push(summary);writeFileSync(summaryPath,JSON.stringify(results,null,2));
 return {payload,target};
}

describe.skipIf(!existsSync(join(base,filename)))('七天十分钟多Sheet隧道：真实API与本地规范全目录验收',()=>{
 beforeAll(async()=>{
  root=mkdtempSync(join(tmpdir(),'tunnel-10min-'));mkdirSync(resultRoot,{recursive:true});
  for(const [key,value] of Object.entries({EXCAVAGUARD_ACCESS_FILE:join(root,'access.json'),EXCAVAGUARD_ACCESS_PASSWORD:'',EXCAVAGUARD_PROJECT_ID:DEFAULT_PROJECT_ID,EXCAVAGUARD_STORAGE_PROVIDER:'local',EXCAVAGUARD_UPLOAD_ROOT:join(root,'uploads'),EXCAVAGUARD_RUN_ROOT:join(root,'runs'),EXCAVAGUARD_STANDARD_CHANGES_ROOT:join(root,'changes'),EXCAVAGUARD_PROJECT_STANDARDS_ROOT:join(root,'standards'),EXCAVAGUARD_PROJECT_CONTEXT_ROOT:join(root,'context')}))vi.stubEnv(key,value);
  const directory=legacyDirectory();directory.projects[0].engineering={adapter_id:'tunnel-monitoring',adapter_version:loadEngineeringAdapter('tunnel-monitoring').adapter.version,parameters:JSON.parse(readFileSync(join(base,'工程参数_SIMULATED.json'),'utf8'))};writeFileSync(join(root,'access.json'),JSON.stringify(directory));
  const uploaded=await upload(filename);fileId=uploaded.file.file_id;
  expect(uploaded.read_report.ok,JSON.stringify(uploaded.read_report)).toBe(true);
  expect(uploaded.read_report.expanded_records).toBe(24192);
  expect(uploaded.read_report.data_sheets).toHaveLength(4);
  writeFileSync(join(resultRoot,'上传解析结果.json'),JSON.stringify(uploaded.read_report,null,2));
 },60000);
 afterAll(()=>{vi.unstubAllEnvs();if(root)rmSync(root,{recursive:true,force:true});for(const dir of artifactDirs)rmSync(dir,{recursive:true,force:true});});
 it('四个监测类型分别上传四个文件，合并分析与多sheet单文件一致',async()=>{
  const split=join(root,'split');mkdirSync(split);
  execFileSync(resolve('.venv/bin/python'),['-c',[
   'import sys;from pathlib import Path;from openpyxl import load_workbook,Workbook',
   'source=load_workbook(sys.argv[1],read_only=True,data_only=True)',
   'for name in ["地表沉降","建筑沉降","拱顶沉降","净空收敛"]:',
   ' w=Workbook();w.active.title=name',
   ' for row in source[name].iter_rows(values_only=True):w.active.append(row)',
   ' w.save(Path(sys.argv[2])/("SIMULATED_"+name+".xlsx"))',
   'source.close()',
  ].join('\n'),join(base,filename),split]);
  const ids:string[]=[];
  for(const name of ['地表沉降','建筑沉降','拱顶沉降','净空收敛']){
   const originalName=`SIMULATED_${name}.xlsx`;const form=new FormData();
   form.set('file',new File([readFileSync(join(split,originalName))],originalName));
   const response=await uploadAPI(new Request('http://localhost/api/monitoring-files',{method:'POST',body:form}));
   expect(response.status).toBe(201);const uploaded=await response.json();
   expect(uploaded.read_report.ok).toBe(true);expect(uploaded.read_report.expanded_records).toBe(6048);
   ids.push(uploaded.file.file_id);
  }
  const response=await runAPI(new Request('http://localhost/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
   project_id:DEFAULT_PROJECT_ID,monitoring_file_id:ids[0],additional_monitoring_file_ids:ids.slice(1),
   report_date:'2026-11-17',report_period:{type:'weekly',start_date:'2026-11-11',end_date:'2026-11-17'},context:{},options:{generate_report:false},
  })}));const data=await response.json();expect(response.status,JSON.stringify(data.error)).toBe(200);
  expect(data.record.error).toBeNull();expect(data.record.source_files).toHaveLength(4);
  expect(data.record.result.engine.source_records).toBe(24192);
  const checked=checkRows(data.record.result.payload.period.daily_items,24192);
  writeFileSync(join(resultRoot,'四文件独立上传合并核验.json'),JSON.stringify({passed:true,files:4,records_per_file:6048,...checked},null,2));
 },120000);
 it('多sheet读取回归',()=>{execFileSync(resolve('.venv/bin/python'),['-B','tests/test_excel_multisheet.py']);});
 it('七天每条观测与预期一致，周报逐本覆盖全部16本规范',async()=>{await runReport('2026-11-17',true,'template');},240000);
 for(let day=11;day<=17;day++)it(`11月${day}日日报：3456条全部解析和判定`,async()=>{await runReport(`2026-11-${day}`,false,'template',day===17);},180000);
 for(const name of ['缺少单位列','后续工作表缺列'])it(`挑战：${name}不得静默接收部分数据`,async()=>{const data=await upload(`SIMULATED_挑战_${name}.xlsx`);expect(data.read_report.ok).toBe(false);expect(data.read_report.errors.length).toBeGreaterThan(0);});
 it('挑战：重复观测须拒绝分析',async()=>{const uploaded=await upload('SIMULATED_挑战_重复观测.xlsx');const response=await runAPI(new Request('http://localhost/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:DEFAULT_PROJECT_ID,monitoring_file_id:uploaded.file.file_id,report_date:'2026-11-11',context:{},options:{generate_report:false}})}));const data=await response.json();expect(response.status).toBe(400);expect(data.error.engine_code).toBe('INVALID_INPUT');expect(data.error.message).toContain('重复观测');});
 it.skipIf(process.env.EXCAVAGUARD_TEST_TUNNEL_10MIN_LLM!=='1')('真实模型高频日报：3456条计算明细全部交付、正文选取原观测',async()=>{await runReport('2026-11-17',false,'ai');},360000);
 it.skipIf(process.env.EXCAVAGUARD_TEST_TUNNEL_10MIN_LLM!=='1')('真实模型周报：完整计算、RAG、三角色及独立语义审查',async()=>{await runReport('2026-11-17',true,'ai');},360000);
});
