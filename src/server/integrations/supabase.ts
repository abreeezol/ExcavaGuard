import "server-only";
import { createClient } from "@supabase/supabase-js";
import { readIntegrationConfig } from "@/server/config";

// 管理客户端会绕过 RLS。业务接入前必须另行验证用户身份与项目所有权。
export function createSupabaseAdmin() {
  const config = readIntegrationConfig("supabase");
  return createClient(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false,
    },
  });
}
