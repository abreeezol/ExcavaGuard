import "server-only";
import type { ReadReport } from "@/contracts/monitoring-files";
import { callSkillScript } from "@/server/skills/python-bridge";

/**
 * parse-monitoring-data · 文件解析检查
 *
 * 上传后立即调用，把「文件是什么编码、哪些列被识别、是否缺必填列」告诉用户。
 * 只读取与映射，不做任何计算或推断。
 */
export async function inspectMonitoringFile(filePath: string): Promise<{
  report: ReadReport;
  records: number;
  elapsedMs: number;
}> {
  const envelope = await callSkillScript("parse-monitoring-data", "inspect_file.py", {
    file_path: filePath,
    include_records: true,
  });
  const trace = (envelope.trace ?? {}) as Record<string, unknown>;
  return {
    report: (envelope.result ?? {}) as ReadReport,
    records: Number(trace.records ?? 0),
    elapsedMs: Number(trace.elapsed_ms ?? 0),
  };
}
