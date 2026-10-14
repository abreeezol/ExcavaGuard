import "server-only";
import { callSkillScript, type SkillEnvelope } from "@/server/skills/python-bridge";

export type NormalizeMonitoringRequest = {
  filePath?: string;
  records?: unknown[];
  reportDate?: string | null;
  dailyAggregate?: boolean;
  expectedIntervalDays?: number | null;
  includeRecords?: boolean;
};

/**
 * Exposes the Python stage-one normalizer for diagnostics and orchestration.
 * Numeric normalization and provenance handling remain in the deterministic
 * engine; this runner only translates the request protocol.
 */
export async function normalizeMonitoringData(
  request: NormalizeMonitoringRequest,
): Promise<SkillEnvelope> {
  return callSkillScript("normalize-monitoring-data", "normalize_records.py", {
    ...(request.filePath ? { file_path: request.filePath } : {}),
    ...(request.records ? { records: request.records } : {}),
    ...(request.reportDate ? { report_date: request.reportDate } : {}),
    daily_aggregate: request.dailyAggregate ?? false,
    ...(request.expectedIntervalDays != null
      ? { expected_interval_days: request.expectedIntervalDays }
      : {}),
    include_records: request.includeRecords ?? false,
  });
}
