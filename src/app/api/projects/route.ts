import { engineeringTypes, runtimeForEngineeringType, canonicalProjectAdapterId } from "@/server/engineering-adapters/engineering-types";
import { loadEngineeringAdapter } from "@/server/engineering-adapters/registry";
import { z } from "zod";
import { requireIdentity } from "@/server/access";
import { createAuthorizedProject } from "@/server/auth/directory";
import { apiError, apiErrorFromException, apiOk } from "@/server/api/respond";
import type { EngineeringSetup } from "@/contracts/project-setup";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
let engineeringSetupCatalog: EngineeringSetup[] | null = null;
function engineeringSetups(): EngineeringSetup[] {
  if (engineeringSetupCatalog) return engineeringSetupCatalog;
  engineeringSetupCatalog = engineeringTypes.map(({ id, name }) => {
    const { adapter } = loadEngineeringAdapter(runtimeForEngineeringType(id));
    return {
      id,
      name,
      adapter_version: adapter.version,
      supported_reports: adapter.supported_reports,
      core_fields: adapter.core_fields,
    };
  });
  return engineeringSetupCatalog;
}
export function GET(request: Request) {
  try {
    const status = requireIdentity(request);
    return apiOk({
      projects: status.projects,
      project_id: status.project_id,
      can_create_project: status.can_create_project,
      engineering_types: engineeringTypes.map(({ id, name }) => ({ id, name })),
      engineering_setups: engineeringSetups(),
    });
  }
  catch (error) { return apiErrorFromException(error); }
}
export async function POST(request: Request) {
  try {
    const status = requireIdentity(request);
    if (!status.can_create_project) return apiError(403, "FORBIDDEN", "当前账号无权新建工程。");
    const parsed = z.strictObject({
      name: z.string().trim().min(1).max(100),
      engineering_type: z.enum(["foundation_pit", "tunnel"]).optional(),
      adapter_id: z.string().min(1).optional(),
      parameters: z.record(z.string(), z.unknown()).optional(),
    }).safeParse(await request.json().catch(() => null));
    if (!parsed.success) return apiError(400, "INVALID_REQUEST", "请填写工程名称（最多100字符）。");
    const runtime=parsed.data.engineering_type?runtimeForEngineeringType(parsed.data.engineering_type):canonicalProjectAdapterId(parsed.data.adapter_id);
    if(parsed.data.adapter_id&&parsed.data.engineering_type&&canonicalProjectAdapterId(parsed.data.adapter_id)!==runtime)return apiError(400,"INVALID_REQUEST","工程类型不一致，请重新选择。");
    return apiOk({
      project: await createAuthorizedProject(
        status.user!.id,
        parsed.data.name,
        runtime,
        parsed.data.parameters,
      ),
    }, 201);
  } catch (error) { return apiErrorFromException(error); }
}
