import { canonicalProjectAdapterId } from "@/server/engineering-adapters/engineering-types";
import "server-only";
import { createHash } from "node:crypto";
import { readFileSync, realpathSync, readdirSync } from "node:fs";
import { isAbsolute, relative, resolve } from "node:path";
import { z } from "zod";

const assetKeys = ["metric_mapping", "file_reader", "calculator", "rule_executor", "rule_registry",
  "rules", "catalog", "standard_status", "renderer", "artifacts", "auditor", "model_requirements"] as const;
export const engineeringAdapterSchema = z.strictObject({
  schema: z.literal("excavaguard.engineering_adapter/v1"),
  id: z.string().regex(/^[a-z][a-z0-9-]{1,63}$/), version: z.string().regex(/^\d+\.\d+\.\d+$/),
  name: z.string().min(1), engineering_type: z.string().min(1),
  status: z.enum(["development_validated_scope", "test_only"]),
  supported_reports: z.array(z.enum(["daily", "weekly", "monthly", "custom"])).min(1),
  core_fields: z.array(z.strictObject({
    key: z.string().min(1), label: z.string().min(1),
    input_type: z.enum(["text", "number", "date", "checkbox"]).optional(), required: z.boolean(), source: z.literal("engineer_confirmed"),
    choices: z.array(z.string()).optional(), choice_labels:z.record(z.string(),z.string()).optional(), missing_policy: z.string().optional(),
  })).min(1).refine(fields => new Set(fields.map(f => f.key)).size === fields.length),
  assets: z.record(z.enum(assetKeys), z.string().min(1)),
  retrieval: z.strictObject({ scope: z.string().min(1), provider: z.literal("existing_environment"), connection: z.string().regex(/^[a-z][a-z0-9-]*$/),local_index:z.string().optional(),
    project_supplements: z.literal("current_project_only"), coverage: z.literal("all_catalog_standards") }),
  additional_assets:z.array(z.string().min(1)).optional(),
  knowledge_manifest:z.string().optional(), standard_scope:z.string().optional(),
  context_schema: z.string().min(1), policy: z.string().min(1), template_version: z.string().min(1),
  handlers: z.record(z.string(), z.string().min(1)),
  boundaries: z.array(z.string().min(1)).min(1), acceptance_suites: z.array(z.string().min(1)).min(1),
});
export type EngineeringAdapter = z.infer<typeof engineeringAdapterSchema>;

/** Only registered server-owned paths are accepted. Never load a path supplied in a document or prompt. */
export function adapterAssetPath(path: string, root = process.cwd()): string {
  if (isAbsolute(path)) throw new Error("ADAPTER_ASSET_OUTSIDE_ROOT");
  const base = realpathSync(/* turbopackIgnore: true */ root);
  const target = realpathSync(/* turbopackIgnore: true */ resolve(base, path));
  const rel = relative(base, target);
  if (rel.startsWith("..") || isAbsolute(rel)) throw new Error("ADAPTER_ASSET_OUTSIDE_ROOT");
  return target;
}

export function validateEngineeringAdapter(value: unknown, root = process.cwd(), verifyAcceptanceFiles = false) {
  const adapter = engineeringAdapterSchema.parse(value);
  const hashes: Record<string, string> = {};
  const requiredHandlers = ["parse-monitoring-data/inspect_file.py", "normalize-monitoring-data/normalize_records.py",
    "evaluate-thresholds/run_judgement.py", "evaluate-thresholds/check_strictness.py",
    "render-daily-report/render_daily_report.py", "validate-report/validate_report.py"];
  if (adapter.status !== "test_only" && requiredHandlers.some(key => !adapter.handlers[key])) throw new Error("ADAPTER_CAPABILITIES_INCOMPLETE");
  const policy = policySchema.parse(JSON.parse(readFileSync(adapterAssetPath(adapter.policy, root), "utf8")));
  if (new Set(policy.form_rules.map(([key]) => key)).size !== policy.form_rules.length) throw new Error("ADAPTER_FORM_CONFLICT");
  const contextSchema = JSON.parse(readFileSync(adapterAssetPath(adapter.context_schema, root), "utf8"));
  z.fromJSONSchema(contextSchema);
  if (adapter.core_fields.some(field => !contextSchema.properties?.[field.key])) throw new Error("ADAPTER_CORE_FIELD_UNKNOWN");
  for (const [key, path] of Object.entries(adapter.assets)) {
    hashes[key] = createHash("sha256").update(readFileSync(adapterAssetPath(path, root))).digest("hex");
  }
  if (verifyAcceptanceFiles) {
    for (const path of adapter.acceptance_suites) adapterAssetPath(path, root);
  }
  const rules = JSON.parse(readFileSync(adapterAssetPath(adapter.assets.rules, root), "utf8"));
  if (!rules.source_id || !rules.metrics || !Object.keys(rules.metrics).length) throw new Error("ADAPTER_RULES_EMPTY");
  hashes.context_schema = createHash("sha256").update(readFileSync(adapterAssetPath(adapter.context_schema, root))).digest("hex");
  hashes.policy = createHash("sha256").update(readFileSync(adapterAssetPath(adapter.policy, root))).digest("hex");
  for (const [key, path] of Object.entries(adapter.handlers)) {
    hashes[`handler:${key}`] = createHash("sha256").update(readFileSync(adapterAssetPath(path, root))).digest("hex");
  }
  if(adapter.standard_scope)hashes.standard_scope=createHash("sha256").update(readFileSync(adapterAssetPath(adapter.standard_scope,root))).digest("hex");
  if(adapter.knowledge_manifest)hashes.knowledge_manifest=createHash("sha256").update(readFileSync(adapterAssetPath(adapter.knowledge_manifest,root))).digest("hex");
  for(const path of adapter.additional_assets??[])hashes[`dependency:${path}`]=createHash("sha256").update(readFileSync(adapterAssetPath(path,root))).digest("hex");
  const externalKnowledge = adapter.knowledge_manifest ? null : {
    status: "external_content_not_pinned", declared_version: process.env.EXCAVAGUARD_KNOWLEDGE_VERSION || "unversioned",
    connection_fingerprint: createHash("sha256").update(JSON.stringify([adapter.retrieval.connection,process.env.RAG_PROVIDER??"",process.env.PINECONE_INDEX??"",process.env.PINECONE_NAMESPACE??"",process.env.LOCAL_RAG_BASE_URL??"",process.env.EXCAVAGUARD_RAG_CONNECTIONS??""])).digest("hex"),
    evidence_policy: "本次实际引用原文已随证据快照冻结；不等于远端全库已归档",
  };
  if(externalKnowledge)hashes.external_knowledge_config=createHash("sha256").update(JSON.stringify(externalKnowledge)).digest("hex");
  const digest = createHash("sha256").update(JSON.stringify({ adapter, hashes })).digest("hex");
  return { adapter, snapshot: {
    schema: "excavaguard.engineering_adapter_snapshot/v1" as const,
    id: adapter.id, version: adapter.version, name: adapter.name,
    engineering_type: adapter.engineering_type, digest, asset_hashes: hashes,
    supported_reports: adapter.supported_reports, retrieval_scope: adapter.retrieval.scope,
    boundaries: adapter.boundaries, knowledge_manifest: adapter.knowledge_manifest ? JSON.parse(readFileSync(adapterAssetPath(adapter.knowledge_manifest,root),"utf8")) : externalKnowledge,
  } };
}

export const LEGACY_ADAPTER_ID = "foundation-pit";
export function loadEngineeringAdapter(id = LEGACY_ADAPTER_ID) {
  if (!/^[a-z][a-z0-9-]{1,63}$/.test(id)) throw new Error("ENGINEERING_ADAPTER_UNSUPPORTED");
  let value: unknown;
  try { value = JSON.parse(readFileSync(adapterAssetPath(`engineering-adapters/${id}/manifest.json`), "utf8")); }
  catch { throw new Error("ENGINEERING_ADAPTER_UNSUPPORTED：尚未适配该工程场景。"); }
  const result = validateEngineeringAdapter(value);
  if (result.adapter.id !== id || (result.adapter.status === "test_only" && process.env.NODE_ENV !== "test")) {
    throw new Error("ENGINEERING_ADAPTER_UNSUPPORTED");
  }
  return result;
}

export function adapterIdFromPayload(payload: unknown): string {
  const snapshot = (payload as { project?: { engineering_adapter?: { id?: unknown } } } | null)?.project?.engineering_adapter;
  if (!snapshot) return LEGACY_ADAPTER_ID; // Explicit compatibility for pre-adapter pit records only.
  if (typeof snapshot.id !== "string") throw new Error("ADAPTER_SNAPSHOT_INVALID");
  loadEngineeringAdapter(snapshot.id);
  return snapshot.id;
}

export type ScenePolicy = {
  excluded_clauses:Record<string,string[]>;
  supporting_context: { max_case_hits: number; max_links: number; section_fields: string[]; time_policy: "same_day" | "interval_overlap"; timezone: string; utc_offset:string; time_window_hours:number; case_defaults:Record<string,string> };
  form_rules: [string, string[]][]; context_checks: [string, string][];
  query_prefix: string; topic_prefix: string; relevance_terms: string[]; query_context_fields: string[];
  recurring_groups: [string, string[]][]; recurring_fallback: string;
  model_instructions: Record<"supervisor" | "report-delivery" | "audit", string>;
};
const policySchema = z.object({
  excluded_clauses:z.record(z.string(),z.array(z.string())).default({}),
  supporting_context: z.object({ max_case_hits: z.number().int().min(1).max(10), max_links: z.number().int().min(1).max(100), section_fields: z.array(z.string().min(1)).min(1), time_policy: z.enum(["same_day","interval_overlap"]), timezone:z.string().default("Asia/Shanghai"),utc_offset:z.string().regex(/^[+-]\d{2}:\d{2}$/).default("+08:00"),time_window_hours:z.number().positive().max(168).default(24),case_defaults:z.record(z.string(),z.string()).default({}) }),
  form_rules: z.array(z.tuple([z.string().min(1), z.array(z.string().min(1))])),
  context_checks: z.array(z.tuple([z.string(), z.string()])),
  query_prefix: z.string().min(1), topic_prefix: z.string().min(1), relevance_terms: z.array(z.string().min(1)),
  query_context_fields: z.array(z.string()), recurring_groups: z.array(z.tuple([z.string(), z.array(z.string())])),
  recurring_fallback: z.string().min(1),
  model_instructions: z.object({ supervisor: z.string(), "report-delivery": z.string(), audit: z.string() }),
});
export function readScenePolicy(id = LEGACY_ADAPTER_ID): ScenePolicy {
  const { adapter } = loadEngineeringAdapter(id);
  return policySchema.parse(JSON.parse(readFileSync(adapterAssetPath(adapter.policy), "utf8")));
}
export function listEngineeringAdapters() {
  return readdirSync(resolve(process.cwd(), "engineering-adapters"), { withFileTypes: true })
    .filter(entry => entry.isDirectory()).flatMap(entry => {
      try { const { adapter } = loadEngineeringAdapter(entry.name); if(canonicalProjectAdapterId(adapter.id)!==adapter.id)return []; return [{ id: adapter.id, name: adapter.name, version: adapter.version, core_fields: adapter.core_fields }]; }
      catch { return []; }
    });
}

export function validateSceneParameters(id: string, parameters: unknown): Record<string, unknown> {
  const { adapter } = loadEngineeringAdapter(id);
  const schema = JSON.parse(readFileSync(adapterAssetPath(adapter.context_schema), "utf8"));
  const supplied = parameters && typeof parameters === "object" && !Array.isArray(parameters) ? { ...parameters } as Record<string, unknown> : parameters;
  if (supplied && typeof supplied === "object") for (const field of adapter.core_fields) {
    const definition = schema.properties?.[field.key];
    if (!field.required && !(field.key in supplied) && definition?.anyOf?.some((item: { type?: string }) => item.type === "null")) {
      (supplied as Record<string, unknown>)[field.key] = null; // Explicit absence, never a guessed engineering value.
    }
  }
  const parsed=z.fromJSONSchema(schema).parse(supplied) as Record<string,unknown>;
  const defaults={...readScenePolicy(id).supporting_context.case_defaults};
  if(adapter.standard_scope){const scope=JSON.parse(readFileSync(adapterAssetPath(adapter.standard_scope),'utf8'));const method=scope.case_method;const value=method?.labels?.[String(parsed[method.parameter])];if(value)defaults.method=value;}
  if(Object.keys(defaults).length){
    const actual=(parsed.case_context??{}) as Record<string,string>;
    if(Object.entries(defaults).some(([k,v])=>actual[k]&&actual[k]!==v))throw new Error("SCENE_CASE_CONTEXT_CONFLICT：案例工法与所选工程场景冲突。");
    parsed.case_context={...actual,...defaults};
  }
  return parsed;
}
export function assertAdapterSnapshot(payload: unknown) {
  const snapshot = (payload as { project?: { engineering_adapter?: { id?: string; version?: string; digest?: string } } } | null)?.project?.engineering_adapter;
  if (!snapshot) return; // Legacy pit payload has no adapter snapshot.
  const current = loadEngineeringAdapter(adapterIdFromPayload(payload)).snapshot;
  if (snapshot.version !== current.version || snapshot.digest !== current.digest) throw new Error("ADAPTER_VERSION_MISMATCH：专业能力已变更，请新建运行重新计算，不能混用旧事实与新实现。");
}
