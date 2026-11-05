import { buildReportModelContext, validateNarrativeGrounding } from "@/server/agents/report-model";
import { describe,it,expect } from 'vitest';
import { rmSync,readFileSync } from 'node:fs';
import { dirname,resolve } from 'node:path';
import { runJudgement } from '@/server/skills/evaluate-thresholds/runner';
import { executeAgentRun } from '@/server/agents/executor';
import { loadEngineeringAdapter } from '@/server/engineering-adapters/registry';
const context={value_semantics:'cumulative_settlement',control_source:'SIMULATED项目监测方案（非真实工程确认）',cumulative_limit_mm:12,rate_limit_mm_per_day:10,control_values_confirmed:true};
const records=[{point_id:'SIM-T1',timestamp:'2026-10-01 20:00:00',metric_key:'ground_settlement',value:4,unit:'mm',data_origin:'simulated'},{point_id:'SIM-T1',timestamp:'2026-10-02 08:00:00',metric_key:'ground_settlement',value:7,unit:'mm',data_origin:'simulated'}];
async function compute(ctx=context,rows:unknown[]=records){return runJudgement({adapterId:'tunnel-shield',context:ctx,records:rows,reportDate:'2026-10-02'});}
describe('真实盾构专业适配器：软件验收，不代表工程师确认',()=>{
 it('声明真实支持范围且不需要基坑工程参数',()=>{const {adapter}=loadEngineeringAdapter('tunnel-shield');expect(adapter.core_fields.some(f=>f.key==='excavation_depth_m')).toBe(false);expect(adapter.engineering_type).toBe('shield_tunnel');});
 it('按实际12小时间隔计算沉降速率，单位正确',async()=>{const out=await compute();expect((out.result as {items:unknown[]}).items).toMatchObject([{cumulative:7,single_change:3,interval_days:.5,rate:6,risk_level:'正常',unit:'mm'}]);});
 it('未确认控制值时弃权，不能因项目值存在就认定安全',async()=>{const out=await compute({...context,control_values_confirmed:false});expect((out.result as {items:unknown[]}).items).toMatchObject([{risk_level:'未知',abstain:['MISSING_CONFIRMED_PROJECT_CRITERIA']}]);});
 it('超过模拟项目控制值时触发预警，规范检索不改阈值',async()=>{const out=await compute({...context,cumulative_limit_mm:6});expect((out.result as {items:unknown[]}).items).toMatchObject([{risk_level:'预警',cumulative:7}]);});
 it('高程观测计算向下为正，m转换为mm',async()=>{const out=await compute({...context,value_semantics:'elevation'},records.map((r,i)=>({...r,value:i?9.995:9.997,baseline_value:10,unit:'m'})));expect((out.result as {items:unknown[]}).items).toMatchObject([{cumulative:5,rate:4,current:9995}]);});
 it('未知测项不得套用支持测项规则',async()=>{const out=await compute(context,records.map(r=>({...r,metric_key:'unsupported_convergence'})));expect((out.result as {items:unknown[]}).items).toMatchObject([{risk_level:'未知'}]);});
 it('上浮不得用正向沉降限值判正常，非有限高程基准拒绝',async()=>{
  const uplift=await compute(context,records.map(r=>({...r,value:-1})));expect((uplift.result as {items:Array<{risk_level:string;abstain:string[]}>}).items[0]).toMatchObject({risk_level:'未知',abstain:['UPLIFT_CONTROL_NOT_PROVIDED']});
  await expect(compute({...context,value_semantics:'elevation'},records.map(r=>({...r,baseline_value:'NaN'})))).rejects.toThrow('初始基准必须为有限数值');
 });
 it('真实模型暴露的速率单位混用由程序提前阻断',async()=>{
  const computed=await compute();const model=buildReportModelContext(computed.result);const p=(text='请工程师核验。')=>({text,evidence_ids:[]});
  const narrative={work_condition:p(),analysis:[p('{{fact:items.0.rate}}{{fact:items.0.unit}}')],recommendations:[p()],limitations:[p()],appendix_analysis:[{form:'S',analysis:p(),recommendation:p()}]};
  expect(()=>validateNarrativeGrounding(narrative,model.facts,[],model.forms)).toThrow('RATE_UNIT_MISMATCH');
  narrative.analysis=[p('{{fact:items.0.rate}}{{fact:items.0.source_metadata.units.rate}}')];expect(()=>validateNarrativeGrounding(narrative,model.facts,[],model.forms)).not.toThrow();
 });
 it('多日区间保留每日未知条目和复核队列，不被代表值掩盖',async()=>{
  const out=await runJudgement({adapterId:'tunnel-shield',context,records,reportDate:'2026-10-02',reportPeriod:{type:'custom',start_date:'2026-10-01',end_date:'2026-10-02'}});
  expect((out.result as {review_queue:unknown[]}).review_queue.length).toBeGreaterThan(0);
  const execution=await executeAgentRun({enginePayload:out.result,reportMode:'template'});const draft=execution.state.report_draft;
  try{expect(execution.state.audit_result?.valid).toBe(true);const cover=draft!.artifacts.find(a=>a.kind==='cover_markdown')!;expect(readFileSync(resolve(cover.relative_path),'utf8')).toContain('区间未知判定条目：1');}
  finally{if(draft?.artifacts[0])rmSync(dirname(resolve(draft.artifacts[0].relative_path)),{recursive:true,force:true});}
 });
 it('贯通三Agent模板和独立文件审计，使用隧道表式和项目依据',async()=>{
  const computed=await compute();const execution=await executeAgentRun({enginePayload:computed.result,reportMode:'template'});const draft=execution.state.report_draft;
  try{expect(execution.state.audit_result?.valid).toBe(true);expect(draft?.artifacts[0].sheets).toContain('沉降成果');const cover=draft!.artifacts.find(a=>a.kind==='cover_markdown')!;expect(readFileSync(resolve(cover.relative_path),'utf8')).toContain('SIMULATED项目监测方案');}
  finally{if(draft?.artifacts[0])rmSync(dirname(resolve(draft.artifacts[0].relative_path)),{recursive:true,force:true});}
 });
});
