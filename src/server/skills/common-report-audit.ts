import "server-only";
import { createHash } from "node:crypto";
import { readFile, realpath } from "node:fs/promises";
import { relative, resolve, isAbsolute } from "node:path";
import type { ReportDraft } from "@/contracts/agent-runtime";

/** Mandatory transport checks; professional handlers cannot opt out. */
export async function commonReportIssues(draft: ReportDraft, evidenceIds: string[]) {
  const issues: Array<{ code: string; severity: "error"; blocking: true; responsibility: "report-delivery"; path: string; message: string }> = [];
  const issue = (code: string, path: string, message: string) => issues.push({ code, path, message, severity: "error", blocking: true, responsibility: "report-delivery" });
  const base = resolve(process.cwd(), "var/report-artifacts");
  const root = await realpath(base).catch(() => base);
  for (const artifact of draft.artifacts) {
    try {
      const file = await realpath(/* turbopackIgnore: true */ resolve(/* turbopackIgnore: true */ process.cwd(), artifact.relative_path));
      const rel = relative(root, file);
      if (rel.startsWith("..") || isAbsolute(rel)) throw new Error("outside root");
      const bytes = await readFile(file);
      if (bytes.length !== artifact.size_bytes || createHash("sha256").update(bytes).digest("hex") !== artifact.sha256) {
        issue("COMMON_ARTIFACT_HASH_MISMATCH", artifact.relative_path, "文件内容与登记指纹不一致。");
      }
    } catch { issue("COMMON_ARTIFACT_UNAVAILABLE", artifact.relative_path, "报告文件不存在或路径越界。"); }
  }
  for (const citation of draft.citations) if (!evidenceIds.includes(citation.evidence_id)) {
    issue("COMMON_CITATION_OUT_OF_SCOPE", citation.report_path, "引用不属于本次冻结证据。");
  }
  return issues;
}
