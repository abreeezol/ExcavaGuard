import { projectBinding } from "@/server/engineering-adapters/engineering-types";
import "server-only";
import { AppError } from "@/server/api/errors";
import { readAccessDirectory } from "@/server/auth/directory";
import { loadEngineeringAdapter, validateSceneParameters } from "@/server/engineering-adapters/registry";

export function projectEngineering(projectId: string) {
  const directory = readAccessDirectory();
  const project = directory?.projects.find(p => p.id === projectId && p.active);
  if (directory && !project) throw new Error("PROJECT_NOT_FOUND");
  // Existing projects predate engineering bindings: explicitly treated as legacy pit.
  const binding = project?.engineering;
  const resolved=projectBinding(binding);
  const loaded = loadEngineeringAdapter(resolved.id);
  if (binding && binding.adapter_id===resolved.id && binding.adapter_version !== loaded.adapter.version) throw new Error("ADAPTER_VERSION_MISMATCH：工程绑定版本需由管理员确认升级。");
  return { ...loaded, parameters: resolved.parameters };
}
export function projectParameters(projectId: string, requestParameters: unknown) {
  const current = projectEngineering(projectId);
  try { return { ...current, context: validateSceneParameters(current.adapter.id, current.parameters ?? requestParameters) }; }
  catch { throw new AppError(400, "INVALID_REQUEST", "工程参数不符合当前场景要求，请检查或更新工程配置。"); }
}
