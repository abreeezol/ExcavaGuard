import "server-only";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { z } from "zod";

const registrySchema = z.object({ standards: z.array(z.object({
  code: z.string().min(1), name: z.string().min(1), category: z.string().min(1), scope_note: z.string(),
})).min(1) });
const manifestSchema = z.object({ standards: z.record(z.string(), z.object({
  effective_status: z.enum(["active", "inactive", "unknown"]), preferred_category: z.string().optional(),
})) });
export type CatalogStandard = {
  standard_name: string; standard_version: string; scope_note: string;
  effective_status: "active" | "inactive" | "unknown";
};

export function readStandardCatalog(): CatalogStandard[] {
  const registry = registrySchema.parse(JSON.parse(readFileSync(resolve(process.cwd(), "确定性计算层/standards/default/规范库索引.json"), "utf8")));
  const manifest = manifestSchema.parse(JSON.parse(readFileSync(resolve(process.cwd(), "rag/standard-status.json"), "utf8")));
  const standards = new Map<string, CatalogStandard>();
  for (const entry of registry.standards) {
    const status = manifest.standards[entry.code];
    if (status?.preferred_category && entry.category !== status.preferred_category) continue;
    if (standards.has(entry.code)) throw new Error("STANDARD_CATALOG_CONFLICT：规范目录存在未消歧的重复版本来源。");
    standards.set(entry.code, { standard_name: entry.name, standard_version: entry.code,
      scope_note: entry.scope_note, effective_status: status?.effective_status ?? "unknown" });
  }
  if (!standards.size) throw new Error("STANDARD_CATALOG_EMPTY：规范目录为空，不能宣称已完成检索。");
  return [...standards.values()].sort((a, b) => a.standard_version.localeCompare(b.standard_version));
}
