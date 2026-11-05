import "server-only";
import { createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { z } from "zod";
import { changeProposalSchema, changePlanSchema, changeAuditSchema, type ProposedRule, type StandardChange, type StandardChangeState, type ChangeDecision } from "@/contracts/standard-changes";
import { projectStandardReviewSource, listProjectStandards } from "@/server/evidence/project-standard-library";
import type { ProjectStandardDocument } from "@/contracts/project-standards";
import { projectEngineering } from "@/server/engineering-adapters/project";
import { adapterAssetPath } from "@/server/engineering-adapters/registry";
import { atomicJson, withFileLock } from "@/server/storage/atomic";
import { AppError } from "@/server/api/errors";
import { readStandardCatalog } from "@/server/evidence/standard-catalog";
import { standardVersionKey } from "@/server/evidence/standard-version";
import { standardChangeModel, type ChangeModel } from "./model";
import type { LocalAccess } from "@/contracts/access";
import { readRun } from "@/server/storage/run-store";
import { callSkillScript } from "@/server/skills/python-bridge";
const hash = (v: unknown) => createHash("sha256").update(JSON.stringify(v)).digest("hex");
const executionContract={
  output:"仅生成供工程师复核的草稿，control是软件固定阈值核查规则，不代表自动签发或现场处置指令。",
  combination:"新增规则与原判据并行执行，取已有与新增提醒的较高等级；绝不覆盖原控制值、不解除原等级或弃权。6mm提醒与12mm原控制可以同时存在，单纯数值不同不等于互相矛盾。",
  review:"确认是工程师对当前项目采用的规则作出决定；仍需审查适用范围、方向、数值、单位与原文。只能报告有原文依据的具体问题，不以想象的歧义阻断明确条文。",
};
function directory(projectId: string) {
  z.uuid().parse(projectId);
  return join(/* turbopackIgnore: true */ resolve(/* turbopackIgnore: true */ process.env.EXCAVAGUARD_STANDARD_CHANGES_ROOT || "var/standard-changes"), projectId);
}
export async function readStandardChanges(projectId: string): Promise<StandardChangeState> {
  try {
    const head = JSON.parse(await readFile(join(directory(projectId), "head.json"), "utf8"));
    const bytes = await readFile(join(directory(projectId), `revision-${z.number().int().positive().parse(head.version)}.json`), "utf8");
    const state = JSON.parse(bytes) as StandardChangeState;
    if (hash(state) !== head.sha256 || state.project_id !== projectId || state.version !== head.version) throw new Error("RULE_HISTORY_CORRUPT");
    return state;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    // A missing immutable revision must never silently become an empty rule set.
    try { await readFile(join(directory(projectId), "head.json")); }
    catch (headError) { if ((headError as NodeJS.ErrnoException).code === "ENOENT") return { version: 0, project_id: projectId, changes: [], updated_at: "", updated_by: "" }; throw headError; }
    throw new Error("RULE_HISTORY_MISSING");
  }
}
async function write(projectId: string, version: number, actor: string, update: (state: StandardChangeState) => Promise<void>) {
  return withFileLock(join(directory(projectId), "write.lock"), async () => {
    const state = await readStandardChanges(projectId);
    if (state.version !== version) throw new AppError(409, "RUN_CONFLICT", "规则变更已更新，请刷新后重试。");
    await update(state);
    state.version++; state.updated_at = new Date().toISOString(); state.updated_by = actor;
    // Each immutable file has a unique name; abandoned writes cannot block a retry.
    const revision = `revision-${state.version}.json`;
    await atomicJson(join(directory(projectId), revision), state);
    await atomicJson(join(directory(projectId), "head.json"), { version: state.version, sha256: hash(state) });
    return state;
  });
}
function professional(projectId: string, engineering?:ReturnType<typeof projectEngineering>) {
  const p = engineering ?? projectEngineering(projectId);
  const rules = JSON.parse(readFileSync(adapterAssetPath(p.adapter.assets.rules), "utf8"));
  const schema = JSON.parse(readFileSync(adapterAssetPath(p.adapter.context_schema), "utf8"));
  return { p, metrics: rules.metrics as Record<string, {unit?:string}>, keys: Object.keys(schema.properties ?? {}), rules,
    configuration_hash: hash(p.parameters ?? null) };
}
function checkDocumentScope(source: Source, prof: ReturnType<typeof professional>) {
  const known=readStandardCatalog(prof.p.adapter.id,prof.p.parameters ?? {}).find(s=>standardVersionKey(s.standard_version)===standardVersionKey(source.document.standard_version));
  if(known && (known.effective_status!=="active" || known.applicable===false)) throw new AppError(400,"INVALID_STANDARD","该规范效力未确认、已失效或不适用于当前工程，不能发布计算判据。");
}
type Source = Awaited<ReturnType<typeof projectStandardReviewSource>>;
export function validateProposedRules(proposal: z.infer<typeof changeProposalSchema>, source: Source, metrics: Record<string,{unit?:string}>, keys: string[]) {
  const result: Record<string, string[]> = Object.create(null);
  const ids = proposal.rules.map(r => r.id);
  for (const rule of proposal.rules) {
    const issues: string[] = [];
    const chunk = source.chunks.find(c => c.id === rule.source_chunk_id);
    if (!chunk || !chunk.text.includes(rule.quote)) issues.push("原文摘录不能对应当前文件切片");
    if (ids.filter(id => id === rule.id).length > 1) issues.push("规则标识重复");
    if (!metrics[rule.metric_key]) issues.push("当前工程不支持此测项");
    if (rule.kind !== "control") issues.push("建议区间、频率及其他要求仅供查证，不自动判级");
    if (metrics[rule.metric_key]?.unit !== "mm") issues.push("当前执行器仅支持毫米变形测项");
    if (rule.unit !== (rule.field === "rate" ? "mm/d" : "mm")) issues.push("指标与单位不一致");
    const numbers = [...rule.quote.matchAll(/\d+(?:\.\d+)?/g)].map(x => Number(x[0]));
    if (!numbers.includes(rule.threshold)) issues.push("阈值未在原文中找到，不执行隐含换算或推断");
    const levels:string[]=rule.quote.match(/危险报警|报警|预警|关注/g)??[];
    if (!levels.includes(rule.risk_level)) issues.push("所选等级不能对应原文，请核对分级名称");
    if (Object.keys(rule.conditions).some(k => !keys.includes(k) || ["__proto__", "constructor", "prototype", "metric_controls"].includes(k))) issues.push("适用条件字段不在本工程参数契约中");
    result[rule.id] = issues;
  }
  return result;
}
export async function analyzeStandardChange(projectId: string, documentId: string, actor: string, version: number, previousId?: string, model: ChangeModel = standardChangeModel) {
  const start = await readStandardChanges(projectId);
  if (start.version !== version) throw new AppError(409,"RUN_CONFLICT","规则变更已更新，请刷新。");
  const previous = previousId ? start.changes.find(c => c.id === previousId) : undefined;
  if (previousId && (!previous || previous.status !== "returned" || previous.document_id !== documentId)) throw new AppError(409,"INVALID_TRANSITION","请先退回当前提案，再修订。");
  if (previous && previous.revision_round >= 2) throw new AppError(409,"INVALID_TRANSITION","已达两轮修订上限，请人工修改候选规则或拒绝本提案。");
  const source = await projectStandardReviewSource(projectId, documentId);
  const prof = professional(projectId);
  checkDocumentScope(source,prof);
  // No silent truncation: do not claim a whole document review when a model cannot receive it.
  if (JSON.stringify(source.chunks).length > 90000) throw new AppError(400,"INVALID_STANDARD","规范全文超出单次规则审查范围，请按章节拆分后上传；全文RAG索引仍可使用。");
  const context = { source, execution_contract:executionContract, engineering: prof.p.parameters, adapter_id: prof.p.adapter.id,
    supported_metrics: prof.metrics, parameter_keys: prof.keys, existing_rules: prof.rules,
    active_changes: start.changes.filter(c => c.status === "published"),
    previous: previous ? { proposal: previous.proposal, feedback: previous.feedback } : null };
  const plan = await model("supervisor", context);
  const authored = await model("report-delivery", { ...context, plan: changePlanSchema.parse(plan.object) });
  const proposal = changeProposalSchema.parse(authored.object);
  if(source.document.unindexed_pages.length) proposal.unresolved.push(`以下页未完整索引，需人工核对：${source.document.unindexed_pages.join("、")}`);
  const validation = validateProposedRules(proposal, source, prof.metrics, prof.keys);
  const reviewed = await model("audit", { ...context, proposal, validation });
  const audit = changeAuditSchema.parse(reviewed.object);
  const at = new Date().toISOString();
  const change: StandardChange = { id: previous?.id ?? randomUUID(), document_id: documentId,
    document_sha256: source.document.sha256, standard_name: source.document.standard_name, standard_version: source.document.standard_version,
    adapter_id: prof.p.adapter.id, adapter_digest: prof.p.snapshot.digest, configuration_hash: prof.configuration_hash,
    status: "pending", revision_round: previous ? previous.revision_round + 1 : 0, created_at: previous?.created_at ?? at, actor,
    proposal, audit, validation, source_pages:Object.fromEntries(source.chunks.map(c=>[c.id,c.page])), trace: [...(previous?.trace ?? []), ...(["supervisor","report-delivery","audit"] as const).map((role, i) => ({ role, model: [plan,authored,reviewed][i].model }))],
    feedback: previous?.feedback ?? [], decisions: [] };
  return write(projectId, version, actor, async state => {
    const current = professional(projectId);
    if (current.configuration_hash !== prof.configuration_hash || current.p.snapshot.digest !== prof.p.snapshot.digest) throw new AppError(409,"RUN_CONFLICT","工程配置已变化，请重新分析。");
    await projectStandardReviewSource(projectId, documentId);
    if (previous) state.changes[state.changes.findIndex(c => c.id === previous.id)] = change;
    else state.changes.push(change);
  });
}
export async function decideStandardChange(projectId: string, id: string, version: number, actor: string, action: "return"|"reject"|"disable"|"publish", note: string, decisions: ChangeDecision[] = [], model: ChangeModel = standardChangeModel) {
  const start = await readStandardChanges(projectId);
  if (start.version !== version) throw new AppError(409,"RUN_CONFLICT","规则变更已更新，请刷新。");
  const change = start.changes.find(c => c.id === id);
  if (!change) throw new AppError(404,"FILE_NOT_FOUND","当前工程没有此变更单。");
  if (action === "disable" ? change.status !== "published" : !["pending","returned"].includes(change.status)) throw new AppError(409,"INVALID_TRANSITION","当前状态不支持此操作。");
  if (["return","disable","reject"].includes(action) && !note.trim()) throw new AppError(400,"INVALID_REQUEST","请填写处理意见。");
  let updatedProposal = change.proposal;
  let newAudit = change.audit;
  let newValidation = change.validation;
  if (action === "publish") {
    if (!note.trim()) throw new AppError(400,"INVALID_REQUEST","请确认适用范围及关键差异，填写发布说明。");
    if (decisions.length !== change.proposal.rules.length || new Set(decisions.map(d => d.rule_id)).size !== decisions.length || decisions.some(d => !change.proposal.rules.some(r => r.id === d.rule_id))) throw new AppError(400,"INVALID_REQUEST","请逐条接受或拒绝全部候选规则。");
    const accepted: ProposedRule[] = [];
    updatedProposal = changeProposalSchema.parse({ ...change.proposal, rules: change.proposal.rules.map(rule => {
      const decision = decisions.find(d => d.rule_id === rule.id)!;
      if (decision.edited && (decision.edited.id !== rule.id || !decision.note.trim())) throw new AppError(400,"INVALID_REQUEST","修改规则需保留标识并说明理由。");
      const updated = decision.edited ?? rule;
      if (decision.action === "accept") accepted.push(updated);
      return updated;
    }) });
    if (!accepted.length) throw new AppError(400,"INVALID_REQUEST","没有接受的规则，可直接拒绝提案。");
    const prof = professional(projectId);
    if (prof.p.adapter.id !== change.adapter_id || prof.p.snapshot.digest !== change.adapter_digest || prof.configuration_hash !== change.configuration_hash) throw new AppError(409,"RUN_CONFLICT","工程配置或专业规则已变化，请退回重新分析。");
    const source = await projectStandardReviewSource(projectId, change.document_id);
    checkDocumentScope(source,prof);
    newValidation = validateProposedRules(updatedProposal, source, prof.metrics, prof.keys);
    if (accepted.some(r => newValidation[r.id].length)) throw new AppError(400,"INVALID_STANDARD","所选规则未通过程序校验，请修改或取消接受。");
    const reviewed = await model("audit", { source, execution_contract:executionContract, proposal: {...updatedProposal, rules:accepted}, engineering:prof.p.parameters,
      existing_rules:prof.rules, active_changes:start.changes.filter(c=>c.status==="published"), engineer_decisions:decisions, note });
    newAudit = changeAuditSchema.parse(reviewed.object);
    if (newAudit.issues.length) throw new AppError(400,"INVALID_STANDARD",`独立审查仍有未解决问题：${newAudit.issues.map(i=>i.message).join("；").slice(0,1200)}。请退回修改或取消相关规则。`);
    change.trace = [...change.trace, {role:"audit", model:reviewed.model}];
  }
  return write(projectId, version, actor, async state => {
    if (action === "publish") {
      const current=professional(projectId);
      if(current.configuration_hash!==change.configuration_hash || current.p.snapshot.digest!==change.adapter_digest) throw new AppError(409,"RUN_CONFLICT","工程配置已变化，请重新分析。");
      await projectStandardReviewSource(projectId,change.document_id);
      // A newer approved review of the same document replaces only that document's prior approved review.
      for(const old of state.changes) if(old.document_id===change.document_id && old.status==="published") old.status="disabled";
    }
    const target = state.changes.find(c=>c.id===id)!;
    Object.assign(target, change, { status: action === "return" ? "returned" : action === "reject" ? "rejected" : action === "disable" ? "disabled" : "published",
      proposal:updatedProposal, validation:newValidation, audit:newAudit,
      decisions:action === "publish" ? decisions : target.decisions,
      feedback:[...target.feedback,{text:note,actor,at:new Date().toISOString()}] });
  });
}
export async function effectiveProjectRules(projectId: string, selectedIds?: string[], prepared?:{engineering:ReturnType<typeof projectEngineering>;documents:ProjectStandardDocument[]}) {
  const state = await readStandardChanges(projectId);
  const prof = professional(projectId,prepared?.engineering);
  const docs = prepared?.documents ?? await listProjectStandards(projectId);
  if(docs.some(d=>d.project_id!==projectId))throw new AppError(403,"FORBIDDEN","规则来源不属于当前工程。");
  const rules: (ProposedRule & { review_id:string; source_label:string; document_id:string; document_sha256:string;source_page:number;approved_by:string;approved_at:string })[] = [];
  const gaps: string[] = [];
  for(const doc of docs.filter(d=>d.active && (!selectedIds || selectedIds.includes(d.document_id)))) {
    if(!state.changes.some(c=>c.document_id===doc.document_id && ["pending","returned","published"].includes(c.status))) gaps.push(`《${doc.standard_name}》仅参与规范检索，尚无已生效的结构化规则`);
  }
  for(const change of state.changes) {
    const doc=docs.find(d=>d.document_id===change.document_id && d.active && d.sha256===change.document_sha256);
    if(!doc || (selectedIds && !selectedIds.includes(doc.document_id))) continue;
    if(["pending","returned"].includes(change.status)) {gaps.push(`《${change.standard_name}》规则变更尚未确认，未参与自动判级`);continue;}
    if(change.status!=="published")continue;
    if(change.adapter_id!==prof.p.adapter.id || change.adapter_digest!==prof.p.snapshot.digest || change.configuration_hash!==prof.configuration_hash) {gaps.push(`《${change.standard_name}》配置已变化，原规则需重新核验，未参与自动判级`);continue;}
    for(const rule of change.proposal.rules)if(change.decisions.some(d=>d.rule_id===rule.id && d.action==="accept"))rules.push({...rule,review_id:change.id,source_label:`《${change.standard_name}》 ${change.standard_version} ${rule.clause}`,document_id:doc.document_id,document_sha256:doc.sha256,source_page:change.source_pages[rule.source_chunk_id],approved_by:change.feedback.at(-1)?.actor??"",approved_at:change.feedback.at(-1)?.at??""});
    gaps.push(...change.proposal.unresolved.map(x=>`《${change.standard_name}》待核：${x}`));
  }
  return {version:state.version,project_id:projectId,engineering_adapter:prof.p.snapshot,configuration_hash:prof.configuration_hash,rules,gaps,
    policy:"项目补充判据并行核查，不能降低原判级；缺失或不匹配条件不套用。"};
}

/** Read-only impact preview over an existing frozen run, never a published report. */
export async function previewStandardChange(access:LocalAccess,id:string,runId:string) {
  const state=await readStandardChanges(access.project_id);
  const change=state.changes.find(c=>c.id===id && ["pending","returned"].includes(c.status));
  if(!change)throw new AppError(404,"FILE_NOT_FOUND","未找到待确认的规则变更。");
  const record=await readRun(runId,access);
  const payload=record.result?.payload as {project?:{engineering_adapter?:{digest?:string};professional_parameters?:Record<string,unknown>};items?:Record<string,unknown>[];period?:{daily_items:Record<string,unknown>[]}}|undefined;
  const prof=professional(access.project_id);
  if(!payload?.items || payload.project?.engineering_adapter?.digest!==change.adapter_digest || prof.configuration_hash!==change.configuration_hash)throw new AppError(409,"RUN_CONFLICT","试算记录或工程配置与提案版本不一致，请使用当前配置生成的记录。");
  const source=await projectStandardReviewSource(access.project_id,change.document_id);
  const validation=validateProposedRules(change.proposal,source,prof.metrics,prof.keys);
  const rules=change.proposal.rules.filter(r=>!validation[r.id].length).map(r=>({...r,review_id:change.id,source_label:`《${change.standard_name}》 ${change.standard_version} ${r.clause}`,document_id:change.document_id,document_sha256:change.document_sha256}));
  const trial=await callSkillScript("review-standard-changes","apply_rules.py",{payload,context:payload.project?.professional_parameters??{},snapshot:{version:state.version,project_id:access.project_id,rules,gaps:[],preview_only:true}});
  const result=trial.result as {items:Record<string,unknown>[];period?:{daily_items:Record<string,unknown>[]}};
  const before=payload.period?.daily_items??payload.items;
  const after=result.period?.daily_items??result.items;
  const affected=after.flatMap((item,index)=>item.risk_level!==before[index]?.risk_level?[{point_id:item.point_id,metric_key:item.metric_key,timestamp:item.timestamp,before:before[index]?.risk_level,after:item.risk_level}]:[]);
  return {run_id:runId,review_id:id,rule_count:rules.length,affected_count:affected.length,samples:affected.slice(0,100),validation,
    notice:"仅在原冻结事实上的补充规则试算，未修改报告或发布规则；最多展示100条变化，最终以新运行结果为准。"};
}
