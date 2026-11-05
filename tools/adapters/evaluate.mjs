import {engineeringTypes} from '@/server/engineering-adapters/engineering-types';
import {readFileSync,writeFileSync}from'node:fs';
import {createHash}from'node:crypto';
import {runJudgement}from'@/server/skills/evaluate-thresholds/runner';
import {loadEngineeringAdapter}from'@/server/engineering-adapters/registry';
const ids=process.argv[2]?[process.argv[2]]:engineeringTypes.map(type=>type.runtime);
const valueAt=(value,path)=>path.split('.').reduce((v,k)=>v?.[k],value);
for(const id of ids){
 const {snapshot}=loadEngineeringAdapter(id);const path=`engineering-adapters/${id}/evaluation-fixtures.json`;const text=readFileSync(path,'utf8');const fixture=JSON.parse(text);const cases=[];
 for(const c of fixture.cases){if(c.manual_review_required){cases.push({case_id:c.case_id,status:'manual_review_required',reference:c.manual_reference});continue;}
  const result=await runJudgement({adapterId:id,context:c.context,records:c.records,reportDate:fixture.report_date,project:{name:'SIMULATED专业评价样例'}});
  const comparisons=Object.entries(c.expected_fields).map(([path,expected])=>({path,expected,actual:valueAt(result.result,path),matches:JSON.stringify(expected)===JSON.stringify(valueAt(result.result,path))}));
  cases.push({case_id:c.case_id,status:comparisons.every(v=>v.matches)?'software_passed':'software_failed',comparisons,actual_items:result.result.items});
 }
 const output={adapter_id:id,producer_adapter_digest:snapshot.digest,fixture_sha256:createHash('sha256').update(text).digest('hex'),simulation_only:true,professional_review:'pending_engineer_review',cases};
 writeFileSync(`engineering-adapters/${id}/evaluation-results.json`,JSON.stringify(output,null,2)+'\n');
 console.log(JSON.stringify({adapter_id:id,software_passed:cases.filter(c=>c.status==='software_passed').length,manual_review_required:cases.filter(c=>c.status==='manual_review_required').length}));
 if(cases.some(c=>c.status==='software_failed'))process.exitCode=1;
}
