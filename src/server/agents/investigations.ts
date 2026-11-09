import 'server-only';
import type {ReportPlan} from '@/contracts/ai-report';
import {adapterIdFromPayload,readScenePolicy} from '@/server/engineering-adapters/registry';
import {readStandardCatalog,type CatalogStandard} from '@/server/evidence/standard-catalog';
import {standardVersionKey} from '@/server/evidence/standard-version';
import {relevantStandardEvidence,retainDiverseEvidence,type StandardSearchRequest} from '@/server/agents/standard-review';
import type {StandardEvidenceSkillResult} from '@/server/skills/retrieve-standard-evidence/runner';
export function validateInvestigations(plan:ReportPlan,facts:Record<string,unknown>,itemCount:number,topics:string[]){
 for(const check of plan.investigations??[]){if(!topics.includes(check.topic)||check.focus_indices.some(i=>i>=itemCount)||check.fact_paths.some(path=>!Object.hasOwn(facts,path)))throw new Error('INVALID_INVESTIGATION：查证任务必须绑定本次测项与冻结事实。');}
}
export async function executeInvestigations(input:{plan:ReportPlan;enginePayload:unknown;baselineIds:string[];catalog?:CatalogStandard[];search:(query:StandardSearchRequest)=>Promise<StandardEvidenceSkillResult>;onCheck?:(check:Record<string,unknown>)=>Promise<void>}){
 const adapterId=adapterIdFromPayload(input.enginePayload);const policy=readScenePolicy(adapterId);const parameters=(input.enginePayload as {project?:{professional_parameters?:Record<string,unknown>}})?.project?.professional_parameters??{};
 const allowed=new Set((input.catalog??readStandardCatalog(adapterId,parameters)).filter(s=>s.applicable!==false&&s.effective_status==='active').map(s=>standardVersionKey(s.standard_version)));
 const evidence=[];const checks=[];const gaps:string[]=[];const baseline=new Set(input.baselineIds);const seen=new Set<string>();
 for(const task of input.plan.investigations??[]){
  const query=`${policy.query_prefix} ${task.topic} ${task.question}`.slice(0,1000);if(seen.has(query))continue;seen.add(query);
  const result=await input.search({query,filters:{effective_status:'active'},limit:6});
  if(result.status==='abstained'&&result.code==='EVIDENCE_UNAVAILABLE')throw new Error('EVIDENCE_UNAVAILABLE：定向查证未完成，保留检查点，不能宣称完成。');
  const accepted=result.status==='success'?result.evidence.filter(e=>allowed.has(standardVersionKey(e.metadata.standard_version))&&relevantStandardEvidence(e,[task.topic],policy)):[];
  const additional=accepted.filter(e=>!baseline.has(e.id));for(const e of accepted)evidence.push(e);
  if(!accepted.length)gaps.push(`定向查证“${task.question}”未取得可用证据，不代表不存在相关要求。`);
  const check={...task,query,trace:result.trace,evidence_ids:accepted.map(e=>e.id),additional_evidence_ids:additional.map(e=>e.id),status:additional.length?'additional_candidates':accepted.length?'existing_candidates':'no_relevant_hit',requires_human_review:true};checks.push(check);await input.onCheck?.(check);
 }
 return {evidence:retainDiverseEvidence(evidence,18),gaps,review:{triggered:checks.length>0,max_checks:3,checks,notice:'Supervisor提出问题，程序验证与检索；候选不改变冻结判级，不证明因果。'}};
}
