import type { AuditResult } from "./agent-runtime";

export function auditStages(audit: AuditResult | null | undefined, mode = "template") {
  if (audit?.stages) return audit.stages;
  const semantic = audit?.checks.find(check => check.name === "independent-llm-semantic-audit");
  return {
    deterministic: !audit ? "not_completed" as const
      : audit.checks.some(check => check !== semantic && !check.valid) ? "failed" as const
      : audit.valid || semantic ? "passed" as const : "failed" as const,
    semantic: semantic
      ? /不可用|未完成/.test(semantic.details ?? "") ? "unavailable" as const
        : semantic.valid ? "passed" as const : "failed" as const
      : mode === "ai" ? "not_completed" as const : "not_required" as const,
  };
}

export function isAuditComplete(audit: AuditResult | null | undefined, mode = "template") {
  const stages = auditStages(audit, mode);
  return audit?.valid === true && !audit.issues.some(issue => issue.blocking) &&
    audit.checks.every(check => check.valid) && stages.deterministic === "passed" &&
    (stages.semantic === "passed" || (mode !== "ai" && stages.semantic === "not_required"));
}

export const AUDIT_STAGE_LABELS = {
  passed: "通过", failed: "未通过", unavailable: "不可用，需人工排查",
  not_completed: "未完成", not_required: "模板模式未执行模型语义审查",
};
