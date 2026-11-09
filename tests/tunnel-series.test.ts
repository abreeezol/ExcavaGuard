import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {validateReport} from '@/server/skills/validate-report/runner';
import {describe,it,expect} from 'vitest';
import {readFileSync,mkdirSync,writeFileSync,copyFileSync} from 'node:fs';
import {resolve,basename} from 'node:path';
import {runJudgement} from '@/server/skills/evaluate-thresholds/runner';
import {executeAgentRun} from '@/server/agents/executor';
const root=resolve('测试数据/隧道模拟_2026-11-01至14');
const context=JSON.parse(readFileSync(resolve(root,'工程参数_SIMULATED.json'),'utf8'));
const files=Array.from({length:14},(_,i)=>resolve(root,`SIMULATED_隧道监测_2026-11-${String(i+1).padStart(2,'0')}.csv`));
type Row={point_id:string;timestamp:string;rate:number|null;risk_level:string;cumulative:number;abstain:string[]};
type Payload={items:Row[];period?:{daily_items:Row[]};summary:unknown};
describe('隧道大样本日报周报',()=>{
 for(const spec of [...Array.from({length:14},(_,i)=>({name:`日报_2026-11-${String(i+1).padStart(2,'0')}`,date:`2026-11-${String(i+1).padStart(2,'0')}`,count:192,start:undefined as string|undefined})),{name:'周报_2026-11-01至07',start:'2026-11-01',date:'2026-11-07',count:1344},{name:'周报_2026-11-08至14',start:'2026-11-08',date:'2026-11-14',count:1344}]){
 it(spec.name,async()=>{
 const result=await runJudgement({adapterId:'tunnel-monitoring',context,filePaths:files,...(spec.start?{reportPeriod:{type:'weekly',start_date:spec.start,end_date:spec.date}}:{reportDate:spec.date})});
 const payload=result.result as Payload;const rows=payload.period?.daily_items??payload.items;
 expect(rows).toHaveLength(spec.count);expect(new Set(rows.map(r=>r.point_id)).size).toBe(24);
 if(spec.start || spec.date>='2026-11-06')expect(rows.some(r=>r.risk_level==='预警')).toBe(true);expect(rows.filter(r=>r.point_id.endsWith('P4')).every(r=>r.risk_level==='未知')).toBe(true);
 expect(rows.filter(r=>r.point_id.endsWith('P1')).every(r=>r.risk_level!=='预警')).toBe(true);
 if(!spec.start){expect(rows.every(r=>r.timestamp.startsWith(spec.date))).toBe(true);if(spec.date!=='2026-11-01')expect(rows.find(r=>r.point_id==='SIM-T1-P1')?.rate).toBeCloseTo(.16);else expect(rows.find(r=>r.point_id==='SIM-T1-P1')?.rate).toBeNull();}
 if(spec.start==='2026-11-01')expect(rows.find(r=>r.point_id==='SIM-T1-P3'&&r.timestamp.startsWith('2026-11-06 00:00'))?.risk_level).toBe('预警');
 const execution=await executeAgentRun({enginePayload:payload,reportMode:'template'});expect(execution.state.audit_result?.valid).toBe(true);
 const output=resolve(root,'outputs',spec.name);mkdirSync(output,{recursive:true});writeFileSync(resolve(output,'计算结果.json'),JSON.stringify(payload,null,2));writeFileSync(resolve(output,'文件审计.json'),JSON.stringify(execution.state.audit_result,null,2));
 for(const a of execution.state.report_draft!.artifacts)copyFileSync(resolve(a.relative_path),resolve(output,basename(a.file_name)));
 if(spec.start){
 const draft=execution.state.report_draft!;
 expect(draft.artifacts[0].sheets).toEqual(expect.arrayContaining(['每日汇总','通道变化','周期观测明细']));
 const md=readFileSync(resolve(output,'隧道变形报告_封面.md'),'utf8');expect(md).toContain('区间原始观测：1344条');expect(md).toContain('通道代表记录：24');expect(md).toContain('## 每日汇总');
 if(spec.start==='2026-11-01'){
 const workbook=draft.artifacts.find(a=>a.kind==='workbook')!;const path=resolve(workbook.relative_path);const original=readFileSync(path);
 try{execFileSync('.venv/bin/python',['-c',"import sys;from openpyxl import load_workbook;p=sys.argv[1];w=load_workbook(p);w['每日汇总']['B2']=0;w.save(p)",path]);
 const bytes=readFileSync(path);workbook.sha256=createHash('sha256').update(bytes).digest('hex');workbook.size_bytes=bytes.length;
 expect((await validateReport({draft,engineSnapshot:execution.state.engine_snapshot,analysisSnapshot:execution.state.analysis_snapshot,evidenceSnapshot:execution.state.evidence_snapshot})).audit.valid).toBe(false);
 }finally{writeFileSync(path,original);}
 }
 }

 },120000);
 }
});
