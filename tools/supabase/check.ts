import { randomUUID } from "node:crypto";
import { createClient } from "@supabase/supabase-js";

const TABLES = [
  "excavaguard_projects",
  "excavaguard_project_members",
  "excavaguard_files",
  "excavaguard_run_revisions",
  "excavaguard_report_artifacts",
] as const;

const url = process.env.NEXT_PUBLIC_SUPABASE_URL?.trim() || process.env.SUPABASE_URL?.trim();
const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY?.trim();
const secretKey = process.env.SUPABASE_SECRET_KEY?.trim();
const unsupportedProjectSecret = process.env.SUPABASE_PROJECT_SECRET?.trim();
const bucket = process.env.SUPABASE_STORAGE_BUCKET?.trim() || "excavaguard-private";
const writeProbe = process.argv.includes("--write-probe");
const requireReady = process.argv.includes("--require-ready");

function fail(message: string): never {
  console.error(JSON.stringify({ status: "configuration_error", message }));
  process.exit(1);
}

function safeMessage(value: unknown): string {
  let message = value instanceof Error ? value.message : String(value);
  for (const secret of [url, publishableKey, secretKey]) {
    if (secret) message = message.replaceAll(secret, "<redacted>");
  }
  return message.slice(0, 500);
}

if (!url || !/^https:\/\/[a-z0-9-]+\.supabase\.co$/i.test(url)) {
  fail("缺少合法的 NEXT_PUBLIC_SUPABASE_URL。");
}
if (!publishableKey?.startsWith("sb_publishable_")) {
  fail("缺少合法的 NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY。");
}
if (unsupportedProjectSecret) {
  fail(
    "检测到不受支持的 SUPABASE_PROJECT_SECRET。若其值是数据库密码，请从 .env.local " +
      "删除并立即轮换；应用需要的是 sb_secret_ 开头的 SUPABASE_SECRET_KEY。",
  );
}
if (secretKey && !secretKey.startsWith("sb_secret_")) {
  fail("SUPABASE_SECRET_KEY 必须使用 sb_secret_ 开头的新式服务端密钥。");
}

const publicClient = createClient(url, publishableKey, {
  auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
});

const authResponse = await fetch(`${url}/auth/v1/settings`, {
  headers: { apikey: publishableKey },
});
if (!authResponse.ok) {
  fail(`公共连接失败（Auth HTTP ${authResponse.status}）。`);
}

if (!secretKey) {
  const result = {
    status: "public_connected",
    public_connection: true,
    secret_configured: false,
    schema_ready: false,
    private_bucket_ready: false,
    infrastructure_verified: false,
    missing: [
      "SUPABASE_SECRET_KEY",
      "SUPABASE_STORAGE_BUCKET（未配置时检查工具使用 excavaguard-private）",
      "执行 supabase/migrations/202610140001_excavaguard_storage.sql",
    ],
  };
  console.log(JSON.stringify(result, null, 2));
  if (requireReady) process.exit(2);
  process.exit(0);
}

const admin = createClient(url, secretKey, {
  auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
});

const tableChecks: Record<string, boolean> = {};
const errors: string[] = [];
for (const table of TABLES) {
  // PostgREST 对缺表的 HEAD 响应可能被客户端视为成功；真实 GET 才能验证 schema cache。
  const { error } = await admin.from(table).select("*").limit(1);
  tableChecks[table] = !error;
  if (error) errors.push(`${table}: ${safeMessage(error.message)}`);
}

const { data: bucketInfo, error: bucketError } = await admin.storage.getBucket(bucket);
const privateBucketReady = !bucketError && bucketInfo?.public === false;
if (bucketError) errors.push(`bucket: ${safeMessage(bucketError.message)}`);
if (bucketInfo?.public === true) errors.push("bucket: bucket 必须为 private。");

const schemaReady = Object.values(tableChecks).every(Boolean);
let infrastructureVerified = false;

if (writeProbe && schemaReady && privateBucketReady) {
  const projectId = randomUUID();
  const objectPath = `${projectId}/_connection-probe/${randomUUID()}.txt`;
  const contents = new TextEncoder().encode("ExcavaGuard Supabase connection probe");
  let projectCreated = false;
  let objectCreated = false;
  try {
    const { error: projectError } = await admin
      .from("excavaguard_projects")
      .insert({ id: projectId, name: "ExcavaGuard connection probe" });
    if (projectError) throw new Error(`project insert: ${projectError.message}`);
    projectCreated = true;

    const { error: uploadError } = await admin.storage
      .from(bucket)
      .upload(objectPath, contents, { contentType: "text/plain", upsert: false });
    if (uploadError) throw new Error(`object upload: ${uploadError.message}`);
    objectCreated = true;

    const { data: downloaded, error: downloadError } = await admin.storage
      .from(bucket)
      .download(objectPath);
    if (downloadError || !downloaded) {
      throw new Error(`object download: ${downloadError?.message ?? "empty response"}`);
    }
    if (new TextDecoder().decode(await downloaded.arrayBuffer()) !== new TextDecoder().decode(contents)) {
      throw new Error("object download: content mismatch");
    }

    const { data: publicDownload } = await publicClient.storage.from(bucket).download(objectPath);
    if (publicDownload) throw new Error("bucket policy: publishable key unexpectedly downloaded private object");
    infrastructureVerified = true;
  } catch (error) {
    errors.push(safeMessage(error));
  } finally {
    if (objectCreated) {
      const { error } = await admin.storage.from(bucket).remove([objectPath]);
      if (error) {
        infrastructureVerified = false;
        errors.push(`probe cleanup object: ${safeMessage(error.message)}`);
      }
    }
    if (projectCreated) {
      const { error } = await admin.from("excavaguard_projects").delete().eq("id", projectId);
      if (error) {
        infrastructureVerified = false;
        errors.push(`probe cleanup project: ${safeMessage(error.message)}`);
      }
    }
  }
}

const status = infrastructureVerified
  ? "infrastructure_verified"
  : schemaReady && privateBucketReady
    ? "schema_ready"
    : "public_connected";

console.log(JSON.stringify({
  status,
  public_connection: true,
  secret_configured: true,
  schema_ready: schemaReady,
  table_checks: tableChecks,
  private_bucket_ready: privateBucketReady,
  bucket,
  write_probe_requested: writeProbe,
  infrastructure_verified: infrastructureVerified,
  missing: [
    ...(!schemaReady
      ? ["执行 supabase/migrations/202610140001_excavaguard_storage.sql"]
      : []),
    ...(!privateBucketReady ? [`创建 private bucket: ${bucket}`] : []),
  ],
  errors,
}, null, 2));

if ((requireReady && status !== "schema_ready" && status !== "infrastructure_verified") ||
    (writeProbe && !infrastructureVerified)) {
  process.exit(2);
}
