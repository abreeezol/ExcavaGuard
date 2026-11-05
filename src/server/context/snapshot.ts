import { canonicalProjectAdapterId } from "@/server/engineering-adapters/engineering-types";
import "server-only";
import type { ContextDocument } from "@/contracts/project-context";
import { retrieveSimilarCases } from "@/server/skills/retrieve-similar-cases/runner";
import { analyzeWorkCondition } from "@/server/skills/analyze-work-condition/runner";
import { adapterIdFromPayload } from "@/server/engineering-adapters/registry";
export function buildContextSnapshot(projectId:string,payload:unknown,documents:ContextDocument[]) {
  documents=documents.filter(d=>d.active);
  const adapterId=adapterIdFromPayload(payload);
  if(documents.some(d=>d.project_id!==projectId||canonicalProjectAdapterId(d.adapter_id)!==canonicalProjectAdapterId(adapterId))) throw new Error("PROJECT_CONTEXT_SCOPE_MISMATCH");
  if(documents.length>50||documents.reduce((n,d)=>n+JSON.stringify(d).length,0)>1_000_000) throw new Error("PROJECT_CONTEXT_BUDGET_EXCEEDED");
  return { schema:"excavaguard.supporting_context/v1", project_id:projectId,adapter_id:adapterId,
    documents:documents.map(d=>({document_id:d.document_id,title:d.title,kind:d.kind,sha256:d.sha256,source_sha256:d.source_sha256,original_name:d.original_name,uploaded_by:d.uploaded_by,created_at:d.created_at,record_count:d.records.length})),
    case_retrieval:retrieveSimilarCases(payload,documents),work_analysis:analyzeWorkCondition(payload,documents),
    notice:"辅助资料仅用于线索与核验，不是规范条文，不改变冻结风险或证明因果。" };
}
