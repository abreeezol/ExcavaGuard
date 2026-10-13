import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { z } from "zod";

export const STANDARD_STATUS_SCHEMA_VERSION =
  "excavaguard.standard_status/v1" as const;
export const PINECONE_IMPORT_SCHEMA_VERSION =
  "excavaguard.pinecone_standard_import/v1" as const;
export const MAX_EMBEDDING_TEXT_CHARACTERS = 420;

const chunkSchema = z.strictObject({
  id: z.string().trim().min(1).max(200),
  content: z
    .string()
    .min(1)
    .max(1_000_000)
    .refine((value) => value.trim().length > 0),
  source: z.string().trim().min(1).max(300),
  category: z.string().trim().min(1).max(100),
  clause: z.string().max(500),
});

const registryStandardSchema = z.object({
  code: z.string().trim().min(1).max(100),
  name: z.string().trim().min(1).max(500),
  file_name: z.string().trim().min(1).max(500),
  category: z.string().trim().min(1).max(100),
  relevance: z.enum(["primary", "secondary", "conditional", "reference"]),
  scope_note: z.string().trim().min(1).max(1_000),
});

const registrySchema = z.object({
  standards: z.array(registryStandardSchema).min(1),
});

const statusEntrySchema = z.strictObject({
  effective_status: z.enum(["active", "inactive", "unknown"]),
  preferred_category: z.string().trim().min(1).max(100).optional(),
  review_note: z.string().trim().max(1_000).optional(),
});

export const standardStatusManifestSchema = z.strictObject({
  schema_version: z.literal(STANDARD_STATUS_SCHEMA_VERSION),
  reviewed_at: z.string().datetime({ offset: true }).nullable(),
  reviewed_by: z.string().trim().min(1).max(200).nullable(),
  standards: z.record(z.string().trim().min(1), statusEntrySchema),
});

export type SourceChunk = z.output<typeof chunkSchema>;
export type RegistryStandard = z.output<typeof registryStandardSchema>;
export type StandardStatusManifest = z.output<typeof standardStatusManifestSchema>;

export type PineconeStandardRecord = {
  _id: string;
  chunk_text: string;
  evidence_kind: "standard";
  standard_name: string;
  standard_version: string;
  clause: string;
  source_location: string;
  applicability: string[];
  effective_status: "active" | "inactive" | "unknown";
  standard_code: string;
  source_category: string;
  source_name: string;
  registry_relevance: RegistryStandard["relevance"];
};

export type PineconeImportReport = {
  schema_version: typeof PINECONE_IMPORT_SCHEMA_VERSION;
  generated_at: string;
  ready_for_upload: boolean;
  blockers: string[];
  counts: {
    input_rows: number;
    registry_standard_codes: number;
    selected_records: number;
    excluded_project_records: number;
    excluded_non_preferred_source_records: number;
    excluded_missing_clause_records: number;
    excluded_oversized_records: number;
    duplicate_record_ids: number;
    records_by_effective_status: Record<
      PineconeStandardRecord["effective_status"],
      number
    >;
  };
  unknown_status_codes: string[];
  missing_status_codes: string[];
  unregistered_status_codes: string[];
  duplicate_standard_sources: Array<{
    standard_code: string;
    available_categories: string[];
    preferred_category: string | null;
  }>;
  oversized_record_ids: string[];
  unmatched_sources: string[];
  conflicting_record_ids: string[];
};

type BuildInput = {
  chunks: SourceChunk[];
  registry: RegistryStandard[];
  statusManifest: StandardStatusManifest;
  generatedAt?: string;
};

function sourceKey(category: string, source: string): string {
  return `${category}\u0000${source}`;
}

function withoutPdfExtension(fileName: string): string {
  return fileName.replace(/\.pdf$/i, "");
}

function sorted(values: Iterable<string>): string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function stableRecord(record: PineconeStandardRecord): string {
  return JSON.stringify(record);
}

export function buildPineconeStandardRecords({
  chunks,
  registry,
  statusManifest,
  generatedAt = new Date().toISOString(),
}: BuildInput): {
  records: PineconeStandardRecord[];
  report: PineconeImportReport;
} {
  const registryBySource = new Map<string, RegistryStandard>();
  const registryByCode = new Map<string, RegistryStandard[]>();
  for (const standard of registry) {
    const key = sourceKey(standard.category, withoutPdfExtension(standard.file_name));
    if (registryBySource.has(key)) {
      throw new Error(`规范索引存在重复来源映射：${standard.category}/${standard.file_name}`);
    }
    registryBySource.set(key, standard);
    registryByCode.set(standard.code, [
      ...(registryByCode.get(standard.code) ?? []),
      standard,
    ]);
  }

  const registryCodes = sorted(registryByCode.keys());
  const manifestCodes = sorted(Object.keys(statusManifest.standards));
  const missingStatusCodes = registryCodes.filter(
    (code) => statusManifest.standards[code] === undefined,
  );
  const unregisteredStatusCodes = manifestCodes.filter(
    (code) => !registryByCode.has(code),
  );
  const unknownStatusCodes = registryCodes.filter(
    (code) =>
      statusManifest.standards[code]?.effective_status === "unknown" ||
      statusManifest.standards[code] === undefined,
  );

  const duplicateStandardSources = [...registryByCode.entries()]
    .filter(([, standards]) => standards.length > 1)
    .map(([standardCode, standards]) => ({
      standard_code: standardCode,
      available_categories: sorted(standards.map((standard) => standard.category)),
      preferred_category:
        statusManifest.standards[standardCode]?.preferred_category ?? null,
    }))
    .sort((left, right) =>
      left.standard_code.localeCompare(right.standard_code, "zh-CN"),
    );

  const invalidPreferredCodes = duplicateStandardSources
    .filter(
      (source) =>
        source.preferred_category === null ||
        !source.available_categories.includes(source.preferred_category),
    )
    .map((source) => source.standard_code);

  const unmatchedSources = new Set<string>();
  const conflictingRecordIds = new Set<string>();
  const oversizedRecordIds = new Set<string>();
  const recordsById = new Map<string, PineconeStandardRecord>();
  let excludedProjectRecords = 0;
  let excludedNonPreferredSourceRecords = 0;
  let excludedMissingClauseRecords = 0;
  let excludedOversizedRecords = 0;
  let duplicateRecordIds = 0;

  for (const chunk of chunks) {
    if (chunk.category === "项目文件") {
      excludedProjectRecords += 1;
      continue;
    }

    const standard = registryBySource.get(sourceKey(chunk.category, chunk.source));
    if (!standard) {
      unmatchedSources.add(`${chunk.category}/${chunk.source}`);
      continue;
    }

    const sameCodeStandards = registryByCode.get(standard.code) ?? [];
    if (sameCodeStandards.length > 1) {
      const preferredCategory =
        statusManifest.standards[standard.code]?.preferred_category;
      if (!preferredCategory || standard.category !== preferredCategory) {
        excludedNonPreferredSourceRecords += 1;
        continue;
      }
    }

    const clause = chunk.clause.trim();
    if (!clause) {
      excludedMissingClauseRecords += 1;
      continue;
    }
    if (chunk.content.length > MAX_EMBEDDING_TEXT_CHARACTERS) {
      excludedOversizedRecords += 1;
      oversizedRecordIds.add(chunk.id);
      continue;
    }

    const status =
      statusManifest.standards[standard.code]?.effective_status ?? "unknown";
    const record: PineconeStandardRecord = {
      _id: chunk.id,
      chunk_text: chunk.content,
      evidence_kind: "standard",
      standard_name: standard.name,
      standard_version: standard.code,
      clause,
      source_location:
        `data/ocr_text/${chunk.category}/${chunk.source}.txt#chunk=${chunk.id}`,
      applicability: [standard.scope_note],
      effective_status: status,
      standard_code: standard.code,
      source_category: chunk.category,
      source_name: chunk.source,
      registry_relevance: standard.relevance,
    };

    const existing = recordsById.get(record._id);
    if (!existing) {
      recordsById.set(record._id, record);
      continue;
    }

    duplicateRecordIds += 1;
    if (stableRecord(existing) !== stableRecord(record)) {
      conflictingRecordIds.add(record._id);
    }
  }

  const records = [...recordsById.values()].sort((left, right) =>
    left._id.localeCompare(right._id),
  );
  const recordsByEffectiveStatus = {
    active: records.filter((record) => record.effective_status === "active").length,
    inactive: records.filter((record) => record.effective_status === "inactive").length,
    unknown: records.filter((record) => record.effective_status === "unknown").length,
  };

  const blockers: string[] = [];
  if (records.length === 0) blockers.push("没有可导入的规范条文记录。");
  if (unknownStatusCodes.length > 0) {
    blockers.push("仍有规范的生效状态为 unknown 或未登记。");
  }
  if (missingStatusCodes.length > 0) {
    blockers.push("状态清单缺少规范编号。");
  }
  if (unregisteredStatusCodes.length > 0) {
    blockers.push("状态清单包含规范索引中不存在的编号。");
  }
  if (invalidPreferredCodes.length > 0) {
    blockers.push("重复规范来源未指定有效的 preferred_category。");
  }
  if (unmatchedSources.size > 0) {
    blockers.push("存在无法与规范索引精确匹配的切片来源。");
  }
  if (conflictingRecordIds.size > 0) {
    blockers.push("存在相同 ID 但内容或元数据不同的切片。");
  }
  if (!statusManifest.reviewed_at || !statusManifest.reviewed_by) {
    blockers.push("状态清单尚未填写复核人和复核时间。");
  }

  return {
    records,
    report: {
      schema_version: PINECONE_IMPORT_SCHEMA_VERSION,
      generated_at: generatedAt,
      ready_for_upload: blockers.length === 0,
      blockers,
      counts: {
        input_rows: chunks.length,
        registry_standard_codes: registryCodes.length,
        selected_records: records.length,
        excluded_project_records: excludedProjectRecords,
        excluded_non_preferred_source_records:
          excludedNonPreferredSourceRecords,
        excluded_missing_clause_records: excludedMissingClauseRecords,
        excluded_oversized_records: excludedOversizedRecords,
        duplicate_record_ids: duplicateRecordIds,
        records_by_effective_status: recordsByEffectiveStatus,
      },
      unknown_status_codes: unknownStatusCodes,
      missing_status_codes: missingStatusCodes,
      unregistered_status_codes: unregisteredStatusCodes,
      duplicate_standard_sources: duplicateStandardSources,
      oversized_record_ids: sorted(oversizedRecordIds),
      unmatched_sources: sorted(unmatchedSources),
      conflicting_record_ids: sorted(conflictingRecordIds),
    },
  };
}

export function readChunksJsonl(filePath: string): SourceChunk[] {
  const rows: SourceChunk[] = [];
  const lines = readFileSync(filePath, "utf8").split(/\r?\n/);
  for (const [index, line] of lines.entries()) {
    if (!line.trim()) continue;
    let raw: unknown;
    try {
      raw = JSON.parse(line);
    } catch {
      throw new Error(`切片文件第 ${index + 1} 行不是合法 JSON。`);
    }
    const parsed = chunkSchema.safeParse(raw);
    if (!parsed.success) {
      throw new Error(`切片文件第 ${index + 1} 行字段不完整。`);
    }
    rows.push(parsed.data);
  }
  return rows;
}

export function readRegistry(filePath: string): RegistryStandard[] {
  const parsed = registrySchema.safeParse(
    JSON.parse(readFileSync(filePath, "utf8")) as unknown,
  );
  if (!parsed.success) {
    throw new Error("默认规范库索引字段不完整。");
  }
  return parsed.data.standards;
}

export function readStatusManifest(filePath: string): StandardStatusManifest {
  const parsed = standardStatusManifestSchema.safeParse(
    JSON.parse(readFileSync(filePath, "utf8")) as unknown,
  );
  if (!parsed.success) {
    throw new Error("规范生效状态清单字段不完整。");
  }
  return parsed.data;
}

export function preparePineconeImport(options: {
  rootDir?: string;
  generatedAt?: string;
} = {}): {
  records: PineconeStandardRecord[];
  report: PineconeImportReport;
  recordsPath: string;
  reportPath: string;
} {
  const rootDir = resolve(options.rootDir ?? process.cwd());
  const chunks = readChunksJsonl(resolve(rootDir, "data/chunks.jsonl"));
  const registry = readRegistry(
    resolve(rootDir, "确定性计算层/standards/default/规范库索引.json"),
  );
  const statusManifest = readStatusManifest(
    resolve(rootDir, "rag/standard-status.json"),
  );
  const prepared = buildPineconeStandardRecords({
    chunks,
    registry,
    statusManifest,
    generatedAt: options.generatedAt,
  });
  const recordsPath = resolve(rootDir, "var/rag/pinecone-records.jsonl");
  const reportPath = resolve(rootDir, "var/rag/pinecone-import-report.json");

  mkdirSync(dirname(recordsPath), { recursive: true });
  writeFileSync(
    recordsPath,
    `${prepared.records.map((record) => JSON.stringify(record)).join("\n")}\n`,
    "utf8",
  );
  writeFileSync(reportPath, `${JSON.stringify(prepared.report, null, 2)}\n`, "utf8");

  return { ...prepared, recordsPath, reportPath };
}
