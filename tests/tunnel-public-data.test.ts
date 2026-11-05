import {describe,it,expect} from 'vitest';
import {readFileSync,mkdirSync,writeFileSync,copyFileSync,existsSync} from 'node:fs';
import {resolve,basename} from 'node:path';
import {runJudgement} from '@/server/skills/evaluate-thresholds/runner';
import {executeAgentRun} from '@/server/agents/executor';
const root=resolve('测试数据/隧道公开实测_脱敏v1');
const file=resolve(root,'REAL_DW_2020-10-15至2022-08-30_未分类位移.csv');
const context={tunnel_system:'rail',construction_method:'mining',project_stage:'construction',special_condition:'none'};
type Row={point_id:string;timestamp:string;current:number;risk_level:string;needs_review:boolean;source_metadata:{source_line:number};abstain:string[]};
describe.skipIf(!existsSync('../sensors_public_dataset_v1.0.0/sensors_public_dataset/data/observations.csv'))('公开隧道真实观测的部分功能验证',()=>{
 for(const weekly of [false,true])it(weekly?'稀疏周报与原始来源保真':'日报不伪造专业判级',async()=>{
 const out=await runJudgement({adapterId:'tunnel-monitoring',context,filePath:file,...(weekly?{reportPeriod:{type:'weekly' as const,start_date:'2022-03-16',end_date:'2022-03-22'}}:{reportDate:'2022-03-22'})});
 const p=out.result as {items:Row[];period?:{daily_items:Row[];missing_dates:string[]};review_queue:Row[]};const rows=p.period?.daily_items??p.items;
 expect(rows.length).toBeGreaterThan(0);expect(rows.every(r=>r.risk_level==='未知'&&r.needs_review&&r.abstain.includes('UNKNOWN_METRIC'))).toBe(true);expect(p.review_queue).toHaveLength(rows.length);
 const original=readFileSync('../sensors_public_dataset_v1.0.0/sensors_public_dataset/data/observations.csv','utf8').trim().split(/\r?\n/);const header=original[0].split(',');
 for(const r of rows){const cells=original[r.source_metadata.source_line-1].split(',');expect(r.current).toBe(Number(cells[header.indexOf('engineering_value_signed')]));expect(r.point_id).toBe(cells[header.indexOf('sensor_id')]+'::'+cells[header.indexOf('channel_id')]);}
 if(weekly)expect(p.period!.missing_dates.length).toBeGreaterThan(0);else expect(rows.every(r=>r.timestamp.startsWith('2022-03-22'))).toBe(true);
 const execution=await executeAgentRun({enginePayload:p,reportMode:'template'});expect(execution.state.audit_result?.valid).toBe(true);
 const target=resolve(root,'outputs',weekly?'周报_2022-03-16至22':'日报_2022-03-22');mkdirSync(target,{recursive:true});writeFileSync(resolve(target,'计算结果.json'),JSON.stringify(p,null,2));writeFileSync(resolve(target,'文件审计.json'),JSON.stringify(execution.state.audit_result,null,2));for(const a of execution.state.report_draft!.artifacts)copyFileSync(resolve(a.relative_path),resolve(target,basename(a.file_name)));
 },120000);
});
