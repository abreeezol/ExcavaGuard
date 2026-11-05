import { scopeQueryConditions } from "@/server/engineering-adapters/standard-scope";
import { adapterIdFromPayload, readScenePolicy, type ScenePolicy } from "@/server/engineering-adapters/registry";
import type { StandardEvidence } from "@/contracts/standard-evidence";
import type { StandardCoverage } from "@/contracts/evidence-display";
import type { StandardEvidenceSkillResult } from "@/server/skills/retrieve-standard-evidence/runner";
import { readStandardCatalog, type CatalogStandard } from "@/server/evidence/standard-catalog";

export const STANDARD_REVIEW_STRATEGY = "catalogue-and-topic-review/v1";
export const COVERAGE_NOTICE = "已逐项检查配置目录的效力与工程适用范围，并对可用规范逐本检索候选；非逐字穷举全部条文或全网最新法规核验；无命中不代表无要求，适用性及条文差异须工程师确认，检索不改写判据。";
export type StandardSearchRequest = { query: string; filters: { effective_status: "active"; standard_versions?: string[] }; limit: number };
type Result = StandardEvidenceSkillResult;
type Query = { scope: "catalogue" | "topic"; topic: string; request: StandardSearchRequest; standard?: CatalogStandard };
export type StandardQueryReview = { scope: Query["scope"]; topic: string; standard_name?: string;
  standard_version?: string; accepted_ids: string[]; trace: Result["trace"]; status: Result["status"]; code?: string };

export function excludedStandardEvidence(item: StandardEvidence, policy: ScenePolicy): boolean {
  const normalized=item.metadata.standard_version.toUpperCase().replace(/[^A-Z0-9]/g,"");
  const rules=Object.entries(policy.excluded_clauses).find(([version])=>version.toUpperCase().replace(/[^A-Z0-9]/g,"")===normalized)?.[1]??[];
  const text=(item.metadata.clause+"；"+item.text).replace(/\s/g,"");
  return rules.includes("*") || rules.some(clause=>new RegExp("(?<![0-9.])"+clause.replace(/\./g,"\\.")+"(?![0-9.])").test(text));
}

export function relevantStandardEvidence(item: StandardEvidence, topics: string[], policy: ScenePolicy = readScenePolicy()): boolean {
  const terms = topics.flatMap((topic) => topic.includes("：") ? topic.split("：")[1].split("、") : []);
  const text = `${item.text} ${item.metadata.monitoring_item ?? ""}`;
  return !excludedStandardEvidence(item,policy) && item.metadata.effective_status === "active" && item.text.length <= 8000 && /应|宜|不得|必须/.test(item.text) && (
    terms.some((term) => term.length > 1 && text.includes(term)) ||
    /监测|复测|巡视|预警|报警|设计方/.test(text) ||
    (policy.relevance_terms.some(term => text.includes(term)) && /开挖|施工|稳定|安全|处置|验收|控制/.test(text))
  );
}

export function retainDiverseEvidence(items: StandardEvidence[], limit = 96): StandardEvidence[] {
  const byId = new Map<string, StandardEvidence>();
  const sourceFingerprint = (item: StandardEvidence) => JSON.stringify([item.text,
    Object.entries(item.metadata).sort(([a],[b])=>a.localeCompare(b))]);
  for (const item of items) {
    const old = byId.get(item.id);
    if (old && sourceFingerprint(old) !== sourceFingerprint(item)) {
      throw new Error("EVIDENCE_CONFLICT：同一证据ID对应不同原文或来源，须人工核验。");
    }
    if (!old || item.score > old.score) byId.set(item.id, item);
  }
  const groups = new Map<string, StandardEvidence[]>();
  for (const item of byId.values()) groups.set(item.metadata.standard_version, [...(groups.get(item.metadata.standard_version) ?? []), item]);
  for (const group of groups.values()) group.sort((a,b) => b.score-a.score || a.id.localeCompare(b.id));
  const result: StandardEvidence[] = [];
  for (let offset=0; result.length<limit; offset++) {
    let added = false;
    for (const [, group] of [...groups].sort(([a],[b])=>a.localeCompare(b))) if (group[offset] && result.length<limit) { result.push(group[offset]); added=true; }
    if (!added) break;
  }
  return result;
}

export async function reviewAllStandards(input: {
  topics: string[]; enginePayload: unknown;
  search: (request: StandardSearchRequest) => Promise<Result>;
  catalog?: CatalogStandard[];
  onQuery?: (query: StandardQueryReview, result: Result) => Promise<void>;
}) {
  const adapterId = adapterIdFromPayload(input.enginePayload);
  const policy = readScenePolicy(adapterId);
  const parameters=(input.enginePayload as {project?:{professional_parameters?:Record<string,unknown>}})?.project?.professional_parameters??{};
  const catalog = input.catalog ?? readStandardCatalog(adapterId,parameters);
  if (!catalog.length || new Set(catalog.map(s=>s.standard_version)).size !== catalog.length) throw new Error("STANDARD_CATALOG_INVALID：规范目录为空或编号重复。");
  const topics = [...new Set(input.topics)];
  const activeVersions = new Set(catalog.filter(s=>s.effective_status==='active'&&s.applicable!==false).map(s=>s.standard_version));
  const engine = input.enginePayload as { project?: Record<string, unknown>; summary?: Record<string, unknown> };
  const conditions = [...scopeQueryConditions(adapterId,parameters),...policy.query_context_fields.map(field => (engine.project?.professional_parameters as Record<string, unknown> | undefined)?.[field] ?? engine.project?.[field]), engine.summary?.overall_risk_level].filter(Boolean).join(" ");
  const allTopics = topics.join("；");
  const entries: StandardCoverage["standards"] = catalog.map(s=>({standard_name:s.standard_name,
    standard_version:s.standard_version,effective_status:s.effective_status,
    status:s.applicable===false?'skipped_scope':s.effective_status==='active'?'pending':'skipped_status',candidate_ids:[],retained_ids:[],
    reason:s.applicable===false?s.scope_reason??'不属于本工程适用范围':s.effective_status==='active'?'尚未查询':`效力未确认或非现行，不能作为确定依据；${s.scope_note}`}));
  const queries: Query[] = [
    ...catalog.filter(s=>s.effective_status==='active'&&s.applicable!==false).map(standard=>({scope:'catalogue' as const,topic:allTopics,standard,
      request:{query:`${policy.query_prefix} ${conditions} ${allTopics} 监测要求 允许变形 预警 复测 风险处置`.slice(0,1000),
        filters:{effective_status:'active' as const,standard_versions:[standard.standard_version]},limit:4}})),
    ...topics.map(topic=>({scope:'topic' as const,topic,request:{query:`${policy.topic_prefix} ${topic} ${conditions} 监测方法 精度 布点 预警 复核 处置要求`.slice(0,1000),
      filters:{effective_status:'active' as const},limit:8}})),
  ];
  const evidence: StandardEvidence[] = [], queryReviews: StandardQueryReview[] = [], gaps: string[] = [];
  // Rolling network workers; progress/checkpoint mutations remain strictly serialized.
  let cursor=0, stopped=false, unavailable=false;
  let callbackError: unknown = null;
  let progress: Promise<void> = Promise.resolve();
  const processResult = async (query: Query, result: Result) => {
    const accepted=result.status==='success' ? result.evidence.filter(item=>activeVersions.has(item.metadata.standard_version) && relevantStandardEvidence(item,topics,policy) &&
      (!query.standard || item.metadata.standard_version===query.standard.standard_version)) : [];
    if(result.evidence.some(item=>excludedStandardEvidence(item,policy)))gaps.push(`${query.topic}：已按已知效力配置排除废止条文候选，不能据无命中认定无要求。`);
    evidence.push(...accepted);
    const entry=entries.find(s=>s.standard_version===query.standard?.standard_version);
    if(entry) {
      entry.candidate_ids=accepted.map(e=>e.id);
      entry.status=result.status==='abstained' && result.code==='EVIDENCE_UNAVAILABLE' ? 'unavailable' : accepted.length?'matched':'no_relevant_hit';
      entry.reason=accepted.length?'取得相关候选，需人工确认适用性':'未获得适用候选，不能认定无要求';
    }
    const record:StandardQueryReview={scope:query.scope,topic:query.topic,
      ...(query.standard?{standard_name:query.standard.standard_name,standard_version:query.standard.standard_version}:{}),
      accepted_ids:accepted.map(e=>e.id),trace:result.trace,status:result.status,
      ...(result.status==='abstained'?{code:result.code}:{})};
    queryReviews.push(record);
    if(result.status==='abstained' && result.code==='EVIDENCE_UNAVAILABLE') unavailable=true;
    if(result.status==='abstained' && result.code==='EVIDENCE_CONFLICT') gaps.push(`${query.standard?.standard_name ?? query.topic}：规范效力或来源冲突，须人工复核。`);
    await input.onQuery?.(record,result);
  };
  const worker = async () => {
    while (!stopped && cursor < queries.length) {
      const query=queries[cursor++];
      let result: Result;
      try { result=await input.search(query.request); }
      catch { result={status:"abstained",code:"EVIDENCE_UNAVAILABLE",message:"规范查询执行失败，不能宣称已完成核查。",evidence:[],notice:COVERAGE_NOTICE,
        trace:{provider:"unavailable",query:query.request.query,filters:query.request.filters,limit:query.request.limit,hit_count:0,evidence_ids:[]}}; }
      if (result.status === "abstained" && result.code === "EVIDENCE_UNAVAILABLE") { stopped=true;unavailable=true; }
      const completed=result;
      progress=progress.then(async()=>{if(!callbackError) await processResult(query,completed);})
        .catch(error=>{callbackError=error instanceof Error ? error : new Error("QUERY_PROGRESS_FAILED：检索进度保存失败。");stopped=true;});
      await progress;
    }
  };
  await Promise.all(Array.from({length:Math.min(8,queries.length)},worker));
  await progress;
  if(callbackError) throw callbackError;
  if(unavailable) throw new Error("EVIDENCE_UNAVAILABLE：规范目录检索未完成，保留已执行查询轨迹，不输出全覆盖声明。");
  const retained=retainDiverseEvidence(evidence);
  const unique=new Map(evidence.map(e=>[e.id,e]));
  for(const entry of entries) {
    entry.retained_ids=retained.filter(e=>e.metadata.standard_version===entry.standard_version).map(e=>e.id);
    if(entry.status==='no_relevant_hit' && entry.retained_ids.length) { entry.status='matched';entry.reason='跨规范主题检索补充命中，须人工确认'; }
    if(entry.status!=='matched') gaps.push(`《${entry.standard_name}》${entry.standard_version}：${entry.reason}。`);
  }
  const coverage:StandardCoverage={strategy:STANDARD_REVIEW_STRATEGY,catalogue_count:catalog.length,
    queried_count:entries.filter(s=>!['pending','skipped_status','skipped_scope'].includes(s.status)).length,
    completed:entries.every(s=>s.status!=='pending'&&s.status!=='unavailable'),candidate_count:unique.size,
    retained_count:retained.length,omitted_count:unique.size-retained.length,notice:COVERAGE_NOTICE,standards:entries};
  const comparisons = topics.map(topic => {
    const terms = topic.includes("：") ? topic.split("：")[1].split("、") : [];
    const matched = retained.filter(item => terms.length ? terms.some(term =>
      `${item.text} ${item.metadata.monitoring_item ?? ""}`.includes(term)) : /监测|预警|报警|设计方|复核/.test(item.text));
    return { topic, evidence_ids: matched.map(item=>item.id),
      standard_versions: [...new Set(matched.map(item=>item.metadata.standard_version))],
      status: matched.length ? "candidates_for_comparison" : "no_relevant_hit",
      notice: "同主题候选不等于条件相同；须对照原文和适用条件，差异由工程师核查，不自动改变冻结判据。" };
  });
  return {evidence:retained,queries:queryReviews,gaps,coverage,comparisons};
}
