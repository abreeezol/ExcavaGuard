import 'server-only';
import { dirname } from 'node:path';
import type { CreateRunRequest } from '@/contracts/runs';
import type { StoredFile } from '@/contracts/monitoring-files';
import { preparationSummarySchema } from '@/contracts/pre-agent-preparation';
import { projectParameters, projectEngineering } from '@/server/engineering-adapters/project';
import { publicEngineeringType } from '@/server/engineering-adapters/engineering-types';
import { selectProjectStandards } from '@/server/evidence/project-standard-library';
import { readStandardCatalog } from '@/server/evidence/standard-catalog';
import { effectiveProjectRules } from '@/server/standard-changes/service';
import { runJudgement } from '@/server/skills/evaluate-thresholds/runner';
import { callSkillScript } from '@/server/skills/python-bridge';
import { listProjectContext } from '@/server/context/library';
import { buildContextSnapshot } from '@/server/context/snapshot';
import { AppError } from '@/server/api/errors';

import { canonicalDigest as digest, handoffDigest, verifyPreparedFacts } from '@/server/preparation/fact-integrity';
export { verifyPreparedFacts } from '@/server/preparation/fact-integrity';

/** Block 1: pin project authority, professional capabilities and criteria sources once. */
export async function prepareEngineeringScene(projectId:string,context:unknown,documentIds?:string[]) {
  const scene=projectParameters(projectId,context);
  const documents=await selectProjectStandards(projectId,documentIds);
  const rules=await effectiveProjectRules(projectId,documents.map(d=>d.document_id),{engineering:scene,documents});
  const catalogue=readStandardCatalog(scene.adapter.id,scene.context);
  return {project_id:projectId,scene,documents,rules,settings_digest:digest(scene.parameters??null),
    summary:{engineering_name:publicEngineeringType(scene.adapter.id).name,adapter_id:scene.adapter.id,
      adapter_version:scene.adapter.version,adapter_digest:scene.snapshot.digest,
      settings_source:scene.parameters?'project' as const:'request' as const,
      public_standards:catalogue.map(s=>({name:s.standard_name,version:s.standard_version,status:s.effective_status,applicable:s.applicable!==false})),
      project_standards:documents.length,supplemental_rules:rules.rules.length,rule_version:rules.version}};
}
export type PreparedEngineeringScene=Awaited<ReturnType<typeof prepareEngineeringScene>>;
export function assertSceneUnchanged(prepared:PreparedEngineeringScene) {
  const current=projectEngineering(prepared.project_id);
  if(current.snapshot.digest!==prepared.scene.snapshot.digest || digest(current.parameters??null)!==prepared.settings_digest)
    throw new AppError(409,'ARTIFACT_CHANGED','计算期间工程配置或专业能力已变化，请重新运行，避免混用判据。');
}
type FactItem={point_id?:string;metric_key?:string;risk_level?:string;rule_id?:string|null;checks?:Record<string,unknown>[];effective_standard?:{source_label?:string};evidence?:{standard?:string;clause?:string}};
type FactPayload={schema:string;project:Record<string,unknown>;items:FactItem[];summary:Record<string,unknown>;review_queue:FactItem[];period?:{type:string;start_date:string;end_date:string;daily_items:FactItem[]}};
/** Block 2: execute registered Skills, collect provenance, then seal the Agent handoff. */
export async function prepareEngineeringFacts(prepared:PreparedEngineeringScene,input:CreateRunRequest,files:{path:string}[],standardPath:string|null,sources:StoredFile[]) {
  if(input.project_id!==prepared.project_id || sources.some(s=>s.project_id!==prepared.project_id))throw new AppError(403,'FORBIDDEN','输入来源不属于当前工程。');
  assertSceneUnchanged(prepared);
  const {scene,rules}=prepared;
  let envelope=await runJudgement({...(files.length===1?{filePath:files[0].path}:{filePaths:files.map(f=>f.path)}),
    standardsDir:standardPath?dirname(standardPath):null,context:scene.context,adapterId:scene.adapter.id,
    reportDate:input.report_date,reportPeriod:input.report_period,project:input.project??null,
    expectedIntervalDays:input.options?.expected_interval_days??null,valueRange:input.options?.value_range??null});
  const raw=envelope.result as FactPayload;
  if((raw.project.engineering_adapter as {digest?:string})?.digest!==scene.snapshot.digest)throw new AppError(409,'ARTIFACT_CHANGED','工程适配器已变化，请重新运行。');
  // Daily selection occurs after full-history computation, before project-rule checks and auxiliary matching.
  const selected=await callSkillScript('prepare-engineering-facts','finalize_facts.py',{payload:raw,report_date:input.report_date},{adapterId:scene.adapter.id});
  envelope={...envelope,result:selected.result};
  if(rules.rules.length||rules.gaps.length){
    const extra=await callSkillScript('review-standard-changes','apply_rules.py',{payload:envelope.result,context:scene.context,snapshot:rules},{adapterId:scene.adapter.id});
    envelope={...envelope,result:extra.result};
  }
  let supportingContext;
  try{supportingContext=buildContextSnapshot(prepared.project_id,envelope.result,await listProjectContext(prepared.project_id));}
  catch{const empty=buildContextSnapshot(prepared.project_id,envelope.result,[]);supportingContext={...empty,unavailable:true,
    case_retrieval:{...empty.case_retrieval,status:'unavailable'},work_analysis:{...empty.work_analysis,patrol_status:'unavailable',work_condition_status:'unavailable'},
    notice:'辅助资料未能可靠加载，本次未使用案例、工况或巡视资料；监测计算仍有效，需核对资料存储与配置。'};}
  const payload=envelope.result as FactPayload;
  payload.project={...payload.project,supporting_context:supportingContext};
  const rows=payload.period?.daily_items??payload.items;
  const criteria=new Map<string,{name:string;clause:string;rule_id:string|null}>();
  for(const row of rows){
    if(row.checks?.length){const adopted={name:row.effective_standard?.source_label??row.evidence?.standard??'来源待核',clause:row.evidence?.clause??'',rule_id:row.rule_id??null};criteria.set(JSON.stringify(adopted),adopted);}
    for(const check of row.checks??[]){const rule=rules.rules.find(r=>r.id===check.rule_id&&r.document_id===check.document_id);if(rule){const adopted={name:rule.source_label,clause:rule.clause,rule_id:rule.id};criteria.set(JSON.stringify(adopted),adopted);}}
  }
  const gaps=[...rules.gaps];
  if(rows.some(r=>r.risk_level==='未知'))gaps.push('存在未知判级，不能据此判断正常。');
  if(payload.review_queue.length)gaps.push('存在待核观测，需结合规则缺项与资料问题复核。');
  if('unavailable' in supportingContext && supportingContext.unavailable)gaps.push(supportingContext.notice);
  const info=preparationSummarySchema.parse({schema:'excavaguard.pre_agent_preparation/v1',scene:prepared.summary,
    facts:{report_kind:payload.period?.type??'daily',start_date:payload.period?.start_date??input.report_date,end_date:payload.period?.end_date??input.report_date,
      observations:rows.length,channels:new Set(rows.map(r=>JSON.stringify([r.point_id,r.metric_key]))).size,
      unknown:rows.filter(r=>r.risk_level==='未知').length,pending:payload.review_queue.length,adopted_criteria:[...criteria.values()],gaps},
    sources:sources.map(s=>({file_id:s.file_id,name:s.original_name,sha256:s.sha256})),fact_digest:'0'.repeat(64)});
  payload.project.pre_agent_preparation=info;
  info.fact_digest=handoffDigest(payload);
  assertSceneUnchanged(prepared);
  verifyPreparedFacts(payload);
  // Keep engine provenance/compatibility fields while refreshing counts for the selected report window.
  const engineSummary=envelope.summary&&typeof envelope.summary==='object'?envelope.summary:{};
  return {envelope:{...envelope,summary:{...engineSummary,...payload.summary},trace:{...envelope.trace,project_rule_version:rules.version,preparation:info}},supportingContext};
}
