import { projectBinding,publicEngineeringType } from "@/server/engineering-adapters/engineering-types";
import { readFileSync } from "node:fs";
import { z } from "zod";
import { requireAccess, requireProjectAction } from "@/server/access";
import { accessDirectoryPath, readAccessDirectory, legacyDirectory } from "@/server/auth/directory";
import { atomicJson, withFileLock } from "@/server/storage/atomic";
import { accessDirectorySchema } from "@/contracts/project-access";
import { loadEngineeringAdapter, adapterAssetPath, validateSceneParameters } from "@/server/engineering-adapters/registry";
import { apiOk, apiErrorFromException } from "@/server/api/respond";
import { AppError } from "@/server/api/errors";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export function GET(request: Request) {
  try {
    const access = requireAccess(request);
    const project = readAccessDirectory()?.projects.find(p => p.id === access.project_id);
    const resolved=projectBinding(project?.engineering);
    const { adapter } = loadEngineeringAdapter(resolved.id);
    const rules=JSON.parse(readFileSync(adapterAssetPath(adapter.assets.rules),"utf8"));
    return apiOk({ engineering_type:publicEngineeringType(adapter.id), monitoring_metrics:Object.entries(rules.metrics).map(([key,value])=>{const v=value as {display_name?:string;semantics?:string[]};return {key,name:v.display_name??key,semantics:v.semantics??[]};}), adapter: { id: adapter.id, name: publicEngineeringType(adapter.id).name, version: adapter.version,
      core_fields: adapter.core_fields, supported_reports: adapter.supported_reports },
      parameter_schema: JSON.parse(readFileSync(adapterAssetPath(adapter.context_schema), "utf8")),
      parameters: resolved.parameters ?? null,
      revision: project?.engineering?.revision ?? 0,
      requires_upgrade: Boolean(project?.engineering && project.engineering.adapter_version !== adapter.version) });
  } catch (error) { return apiErrorFromException(error); }
}
export async function PUT(request: Request) {
  try {
    const access = requireProjectAction(request, "write");
    if (access.role && access.role !== "admin") throw new AppError(403, "FORBIDDEN", "仅项目管理员可确认或更新工程配置。");
    const parsed = z.strictObject({ expected_revision: z.number().int().nonnegative(), adapter_version: z.string(), parameters: z.record(z.string(), z.unknown()) }).safeParse(await request.json());
    if (!parsed.success) throw new AppError(400, "INVALID_REQUEST", "请检查工程配置及版本。");
    return await withFileLock(`${accessDirectoryPath()}.lock`, async () => {
      const directory = readAccessDirectory() ?? legacyDirectory();
      const project = directory.projects.find(p => p.id === access.project_id && p.active);
      if (!project) throw new AppError(404, "FILE_NOT_FOUND", "工程不存在。");
      const { adapter } = loadEngineeringAdapter(projectBinding(project.engineering).id);
      if ((project.engineering?.revision ?? 0) !== parsed.data.expected_revision || parsed.data.adapter_version !== adapter.version) throw new AppError(409, "INVALID_REQUEST", "配置已变化，请刷新后重新确认。");
      let parameters: Record<string, unknown>;
      try { parameters = validateSceneParameters(adapter.id, parsed.data.parameters); }
      catch { throw new AppError(400, "INVALID_REQUEST", "参数不符合当前工程场景要求。"); }
      project.engineering = { adapter_id: adapter.id, adapter_version: adapter.version,
        parameters, revision: parsed.data.expected_revision + 1, confirmed_by: access.actor?.id ?? access.owner_id, confirmed_at: new Date().toISOString() };
      await atomicJson(accessDirectoryPath(), accessDirectorySchema.parse(directory));
      return apiOk({ engineering: project.engineering });
    });
  } catch (error) { return apiErrorFromException(error); }
}
