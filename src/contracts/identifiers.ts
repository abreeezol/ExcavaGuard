import { z } from "zod";

export const agentIdSchema = z.enum([
  "supervisor",
  "data-governance",
  "criteria-and-standards",
  "risk-attribution",
  "report-delivery",
  "audit",
]);

export const skillIdSchema = z.enum([
  "parse-monitoring-data",
  "normalize-monitoring-data",
  "evaluate-thresholds",
  "retrieve-standard-evidence",
  "retrieve-similar-cases",
  "analyze-work-condition",
  "render-daily-report",
  "validate-report",
]);

export type AgentId = z.infer<typeof agentIdSchema>;
export type SkillId = z.infer<typeof skillIdSchema>;
