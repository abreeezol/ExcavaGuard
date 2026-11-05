import "server-only";
import { readFileSync } from "node:fs";
import { loadEngineeringAdapter, adapterAssetPath } from "@/server/engineering-adapters/registry";
import { checkStandardScope,readStandardScope } from "@/server/engineering-adapters/standard-scope";
import { z } from "zod";

const registrySchema = z.object({ standards: z.array(z.object({
  code: z.string().min(1), name: z.string().min(1), category: z.string().min(1), scope_note: z.string(), conditions:z.record(z.string(),z.array(z.string())).optional(),
})).min(1) });
const manifestSchema = z.object({ standards: z.record(z.string(), z.object({
  effective_status: z.enum(["active", "inactive", "unknown"]), preferred_category: z.string().optional(),
})) });
export type CatalogStandard = {
  standard_name: string; standard_version: string; scope_note: string;
  effective_status: "active" | "inactive" | "unknown";
  applicable?:boolean; scope_reason?:string;
};

export function readStandardCatalog(adapterId = "foundation-pit", parameters?:Record<string,unknown>): CatalogStandard[] {
  const { adapter } = loadEngineeringAdapter(adapterId);
  const registry = registrySchema.parse(JSON.parse(readFileSync(adapterAssetPath(adapter.assets.catalog), "utf8")));
  const manifest = manifestSchema.parse(JSON.parse(readFileSync(adapterAssetPath(adapter.assets.standard_status), "utf8")));
  const scope=parameters?readStandardScope(adapterId):null;
  const standards = new Map<string, CatalogStandard>();
  for (const entry of registry.standards) {
    const status = manifest.standards[entry.code];
    if (status?.preferred_category && entry.category !== status.preferred_category) continue;
    if (standards.has(entry.code)) throw new Error("STANDARD_CATALOG_CONFLICT：规范目录存在未消歧的重复版本来源。");
    standards.set(entry.code, { standard_name: entry.name, standard_version: entry.code,
      scope_note: entry.scope_note, ...(parameters?checkStandardScope(adapterId,entry.conditions??{},parameters,scope):{}), effective_status: status?.effective_status ?? "unknown" });
  }
  if (!standards.size) throw new Error("STANDARD_CATALOG_EMPTY：规范目录为空，不能宣称已完成检索。");
  return [...standards.values()].sort((a, b) => a.standard_version.localeCompare(b.standard_version));
}
