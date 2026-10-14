import "server-only";
import { createSupabaseAdmin } from "@/server/integrations/supabase";
import { readIntegrationConfig } from "@/server/config";
import { AppError } from "@/server/api/errors";

export function supabaseContext() {
  const config = readIntegrationConfig("supabase");
  return {
    client: createSupabaseAdmin(),
    bucket: config.SUPABASE_STORAGE_BUCKET,
  };
}

export async function ensureSupabaseProject(
  projectId: string,
  name = "ExcavaGuard project",
  updateName = false,
): Promise<void> {
  const { client } = supabaseContext();
  const { error } = await client
    .from("excavaguard_projects")
    .upsert(
      { id: projectId, name },
      { onConflict: "id", ignoreDuplicates: !updateName },
    );
  if (error) {
    throw new AppError(500, "STORAGE_ERROR", `Supabase 工程元数据写入失败：${error.message}`);
  }
}

export function supabaseStorageError(context: string, error: { message: string }): AppError {
  return new AppError(500, "STORAGE_ERROR", `${context}：${error.message}`);
}

export function isUniqueViolation(error: { code?: string | null; message?: string }): boolean {
  return error.code === "23505" || error.message?.includes("duplicate key") === true;
}
