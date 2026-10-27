import type { ReportNarrative } from "@/contracts/ai-report";
import type { StandardEvidence } from "@/contracts/standard-evidence";

/** Relevant project hits must affect authored conclusions, not just an attachment index. */
export function validateProjectStandardReferences(narrative: ReportNarrative, evidence: StandardEvidence[]) {
  const project = evidence.filter(e => e.provider === "project");
  if (!project.length) return;
  const paragraphs = [...narrative.analysis, ...narrative.recommendations,
    ...narrative.appendix_analysis.flatMap(a => [a.analysis, a.recommendation])];
  const cited = new Set(paragraphs.flatMap(p => p.evidence_ids));
  const documents = new Set(project.map(e => e.metadata.document_id));
  if ([...documents].some(documentId => !project.some(e => e.metadata.document_id === documentId && cited.has(e.id)))) {
    throw new Error("PROJECT_STANDARD_REFERENCE_REQUIRED：本次命中项目补充要求，请在分析或建议中引用相关条文并说明适用条件，不得仅使用默认规范。");
  }
}
