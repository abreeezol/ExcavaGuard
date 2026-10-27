import "server-only";
import { resolve, extname } from "node:path";
import { z } from "zod";
import { projectStandardDocumentSchema, projectStandardMetadataSchema, type ProjectStandardDocument } from "@/contracts/project-standards";
import { standardEvidenceQuerySchema, standardEvidenceSchema, type StandardEvidenceQuery } from "@/contracts/standard-evidence";
import type { StandardEvidenceRetriever } from "@/server/evidence/retriever";
import { callSkillScript } from "@/server/skills/python-bridge";
import { AppError } from "@/server/api/errors";
import type { CatalogStandard } from "@/server/evidence/standard-catalog";

async function call(projectId: string, action: string, body: Record<string, unknown> = {}) {
  z.uuid().parse(projectId);
  const result = await callSkillScript("project-standard-library", "library.py", {
    ...body, action, project_id: projectId,
    root: resolve(/* turbopackIgnore: true */ process.env.EXCAVAGUARD_PROJECT_STANDARDS_ROOT || "var/project-standards"),
  }, { timeoutMs: action === "ingest" ? 120_000 : 30_000 });
  return result.result;
}

export async function listProjectStandards(projectId: string) {
  return z.array(projectStandardDocumentSchema).parse(await call(projectId, "list"));
}

export async function uploadProjectStandard(projectId: string, file: File, metadata: unknown) {
  const parsed = projectStandardMetadataSchema.safeParse(metadata);
  if (!parsed.success) throw new AppError(400, "INVALID_STANDARD", "请填写规范名称、编号、地区和适用条件，并确认文件效力及工程适用性。");
  const extension = extname(file.name).toLowerCase();
  if (![".pdf", ".txt", ".md"].includes(extension)) throw new AppError(415, "UNSUPPORTED_FILE_TYPE", "补充规范支持可搜索PDF、UTF-8 TXT或Markdown。");
  if (!file.size) throw new AppError(400, "FILE_EMPTY", "文件不能为空。");
  if (file.size > 20 * 1024 * 1024) throw new AppError(413, "FILE_TOO_LARGE", "规范文件不能超过20MB。");
  return projectStandardDocumentSchema.parse(await call(projectId, "ingest", {
    bytes: Buffer.from(await file.arrayBuffer()).toString("base64"),
    metadata: { ...parsed.data, original_name: file.name.slice(0, 200), extension },
  }));
}

export async function selectProjectStandards(projectId: string, documentIds?: string[], requireActive = true) {
  if (documentIds) z.array(z.uuid()).max(50).parse(documentIds);
  const documents = z.array(projectStandardDocumentSchema).parse(await call(projectId, "select", {
    ...(documentIds ? { document_ids: documentIds } : {}), require_active: requireActive,
  }));
  if (documents.length > 50) throw new AppError(400, "INVALID_STANDARD", "单次运行最多使用50份项目规范，请先停用不需要的文件。");
  return documents;
}

export async function setProjectStandardActive(projectId: string, documentId: string, active: boolean) {
  z.uuid().parse(documentId);
  return projectStandardDocumentSchema.parse(await call(projectId, "set_active", { document_id: documentId, active }));
}

/** Immutable document selection; disabling affects future runs only. */
export class ProjectStandardRetriever implements StandardEvidenceRetriever {
  readonly provider = "project" as const;
  constructor(readonly projectId: string, readonly documents: ProjectStandardDocument[]) {
    if (documents.some(d => d.project_id !== projectId)) throw new Error("PROJECT_STANDARD_SCOPE_MISMATCH");
  }
  async search(query: StandardEvidenceQuery) {
    const parsed = standardEvidenceQuerySchema.parse(query);
    const selected = this.documents.filter(d => !parsed.filters.standard_versions || parsed.filters.standard_versions.includes(d.standard_version));
    if (!selected.length) return [];
    const result = z.array(standardEvidenceSchema).parse(await call(this.projectId, "search", {
      document_ids: selected.map(d => d.document_id), query: parsed,
    }));
    if (result.some(e => e.metadata.project_id !== this.projectId ||
        !selected.some(d => d.document_id === e.metadata.document_id && d.sha256 === e.metadata.content_sha256))) {
      throw new Error("PROJECT_STANDARD_EVIDENCE_MISMATCH");
    }
    return result;
  }
}

export function withProjectCatalog(catalog: CatalogStandard[], documents: ProjectStandardDocument[]): CatalogStandard[] {
  const result = new Map(catalog.map(s => [s.standard_version, s]));
  for (const doc of documents) result.set(doc.standard_version, {
    standard_name: doc.standard_name, standard_version: doc.standard_version,
    effective_status: "active", scope_note: `${doc.region}；${doc.applicability}；仅当前项目补充规范`,
  });
  return [...result.values()];
}

/** Do not compare BM25 scores with vector similarity; retain hits from both libraries. */
export class CombinedStandardRetriever implements StandardEvidenceRetriever {
  readonly provider = "project" as const;
  constructor(private readonly shared: StandardEvidenceRetriever, private readonly project: ProjectStandardRetriever) {}
  async search(query: StandardEvidenceQuery) {
    const parsed = standardEvidenceQuerySchema.parse(query);
    const versions = new Set(this.project.documents.map(d => d.standard_version));
    if (parsed.filters.standard_versions?.every(v => versions.has(v))) return this.project.search(parsed);
    const [project, shared] = await Promise.all([this.project.search(parsed), this.shared.search(parsed)]);
    const candidates = shared.filter(e => !versions.has(e.metadata.standard_version));
    const result = [];
    for (let i = 0; result.length < parsed.top_k && (i < project.length || i < candidates.length); i++) {
      if (project[i]) result.push(project[i]);
      if (candidates[i] && result.length < parsed.top_k) result.push(candidates[i]);
    }
    return result;
  }
}
