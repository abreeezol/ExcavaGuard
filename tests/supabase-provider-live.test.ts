import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  DEFAULT_PROJECT_ID,
  type LocalAccess,
} from "@/contracts/access";
import { riskEvaluationTargets } from "@/contracts/engineer-evaluation";

const enabled = process.env.EXCAVAGUARD_TEST_SUPABASE === "1";
const describeLive = enabled ? describe : describe.skip;
type Json = Record<string, unknown>;

describeLive("Supabase 应用 Provider 真实纵向验收", () => {
  let uploadPOST: (request: Request) => Promise<Response>;
  let standardsPOST: (request: Request) => Promise<Response>;
  let runsPOST: (request: Request) => Promise<Response>;
  let reviewPOST: (
    request: Request,
    context: { params: Promise<{ runId: string }> },
  ) => Promise<Response>;
  let artifactGET: (
    request: Request,
    context: { params: Promise<{ draftId: string; fileName: string }> },
  ) => Promise<Response>;
  let createSupabaseAdmin: typeof import("@/server/integrations/supabase").createSupabaseAdmin;
  let readIntegrationConfig: typeof import("@/server/config").readIntegrationConfig;
  let readRun: typeof import("@/server/storage/run-store").readRun;
  let saveRun: typeof import("@/server/storage/run-store").saveRun;
  let deleteRun: typeof import("@/server/storage/run-store").deleteRun;
  const cleanupObjectPaths = new Set<string>();
  const fileIds = new Set<string>();
  let runId: string | null = null;
  let originalProjectName: string | null = null;
  let projectExisted = false;

  beforeAll(async () => {
    process.env.EXCAVAGUARD_STORAGE_PROVIDER = "supabase";
    ({ createSupabaseAdmin } = await import("@/server/integrations/supabase"));
    ({ readIntegrationConfig } = await import("@/server/config"));
    ({ POST: uploadPOST } = await import("@/app/api/monitoring-files/route"));
    ({ POST: standardsPOST } = await import("@/app/api/standards/route"));
    ({ POST: runsPOST } = await import("@/app/api/runs/route"));
    ({ POST: reviewPOST } = await import("@/app/api/runs/[runId]/review/route"));
    ({ deleteRun, readRun, saveRun } = await import("@/server/storage/run-store"));
    ({ GET: artifactGET } = await import(
      "@/app/api/report-artifacts/[draftId]/[fileName]/route"
    ));
    const { data: project } = await createSupabaseAdmin()
      .from("excavaguard_projects")
      .select("name")
      .eq("id", DEFAULT_PROJECT_ID)
      .maybeSingle();
    projectExisted = Boolean(project);
    originalProjectName = project?.name ?? null;
  });

  afterAll(async () => {
    if (!enabled) return;
    const client = createSupabaseAdmin();
    const { SUPABASE_STORAGE_BUCKET } = readIntegrationConfig("supabase");
    const cleanupErrors: string[] = [];
    if (cleanupObjectPaths.size > 0) {
      const { error } = await client.storage
        .from(SUPABASE_STORAGE_BUCKET)
        .remove([...cleanupObjectPaths]);
      if (error) cleanupErrors.push(`object: ${error.message}`);
    }
    if (runId) {
      const { error: artifactError } = await client
        .from("excavaguard_report_artifacts")
        .delete()
        .eq("run_id", runId);
      if (artifactError) {
        cleanupErrors.push(`artifact: ${artifactError.message}`);
      }
      const { error: runError } = await client
        .from("excavaguard_run_revisions")
        .delete()
        .eq("run_id", runId);
      if (runError) cleanupErrors.push(`run: ${runError.message}`);
    }
    if (fileIds.size > 0) {
      const { error } = await client
        .from("excavaguard_files")
        .delete()
        .in("file_id", [...fileIds]);
      if (error) cleanupErrors.push(`file: ${error.message}`);
    }
    if (projectExisted && originalProjectName) {
      const { error } = await client
        .from("excavaguard_projects")
        .update({ name: originalProjectName })
        .eq("id", DEFAULT_PROJECT_ID);
      if (error) cleanupErrors.push(`project restore: ${error.message}`);
    } else if (!projectExisted) {
      const { error } = await client
        .from("excavaguard_projects")
        .delete()
        .eq("id", DEFAULT_PROJECT_ID);
      if (error) cleanupErrors.push(`project cleanup: ${error.message}`);
    }
    delete process.env.EXCAVAGUARD_STORAGE_PROVIDER;
    if (cleanupErrors.length > 0) {
      throw new Error(`Supabase live test cleanup failed: ${cleanupErrors.join("; ")}`);
    }
  });

  it("上传、分析、运行修订、三件套下载和复核全部走 Supabase", async () => {
    const source = readFileSync(
      resolve("确定性计算层/data_simulated/SIMULATED_基坑监测数据集_v1.csv"),
      "utf8",
    );
    const simulated = source.split(/\r?\n/).slice(0, 8).join("\n");
    const form = new FormData();
    form.set("file", new File([simulated], "SIMULATED_supabase_provider.csv", {
      type: "text/csv",
    }));

    const uploadResponse = await uploadPOST(new Request(
      "http://localhost/api/monitoring-files",
      { method: "POST", body: form },
    ));
    const upload = await uploadResponse.json() as Json;
    expect(uploadResponse.status, JSON.stringify(upload)).toBe(201);
    const file = upload.file as Json;
    const fileId = String(file.file_id);
    fileIds.add(fileId);
    expect(file).toMatchObject({
      project_id: DEFAULT_PROJECT_ID,
      kind: "monitoring",
      storage: "supabase",
      original_name: "SIMULATED_supabase_provider.csv",
    });
    expect(upload.read_report).toMatchObject({ ok: true, data_rows: 7 });

    const client = createSupabaseAdmin();
    const { data: fileRow } = await client
      .from("excavaguard_files")
      .select("storage_path,sha256")
      .eq("file_id", fileId)
      .single();
    expect(fileRow?.storage_path).toMatch(
      new RegExp(`^${DEFAULT_PROJECT_ID}/monitoring/${fileId}/monitoring\\.csv$`),
    );
    cleanupObjectPaths.add(String(fileRow?.storage_path));

    const standardResponse = await standardsPOST(new Request(
      "http://localhost/api/standards",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          payload: {
            source_id: "SIMULATED-SUPABASE-STANDARD",
            source_label: "SIMULATED Supabase Provider 验收规范",
            source_type: "user_uploaded",
            metrics: {
              wall_top_horizontal_displacement: {
                rules: [{
                  rule_id: "WTHD-L1-PILE",
                  safety_level: ["一级"],
                  support_type: ["地下连续墙"],
                  cumulative_mm: { min: 10, max: 20 },
                  rate_mm_per_day: { min: 1.5, max: 2 },
                  evidence: {
                    standard: "SIMULATED Supabase Provider 验收规范",
                    clause: "TEST-1",
                  },
                }],
              },
            },
          },
          context: {
            safety_level: "一级",
            support_type: "地下连续墙",
            excavation_depth_m: 20,
          },
        }),
      },
    ));
    const standardUpload = await standardResponse.json() as Json;
    expect(standardResponse.status, JSON.stringify(standardUpload)).toBe(201);
    const standardFileId = String((standardUpload.file as Json).file_id);
    fileIds.add(standardFileId);
    expect(standardUpload.file).toMatchObject({ storage: "supabase", kind: "standard" });
    const { data: standardRow } = await client
      .from("excavaguard_files")
      .select("storage_path")
      .eq("file_id", standardFileId)
      .single();
    cleanupObjectPaths.add(String(standardRow?.storage_path));

    const runResponse = await runsPOST(new Request("http://localhost/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: DEFAULT_PROJECT_ID,
        monitoring_file_id: fileId,
        standards_file_id: standardFileId,
        report_date: "2026-08-07",
        context: {
          safety_level: "一级",
          support_type: "地下连续墙",
          excavation_depth_m: 20,
        },
        project: { name: "SIMULATED Supabase Provider 验收" },
        options: { generate_report: true, report_mode: "template" },
      }),
    }));
    expect(runResponse.status).toBe(200);
    const run = await runResponse.json() as Json;
    runId = String(run.run_id);
    const record = run.record as Json;
    const agentRun = run.agent_run as Json;
    const state = agentRun.state as Json;
    const draft = state.report_draft as Json;
    expect(record).toMatchObject({ execution_status: "completed" });
    expect(state.run).toMatchObject({ status: "awaiting_human_review" });
    expect((run.payload as Json).summary).toMatchObject({
      by_data_origin: { simulated: 7 },
    });

    const { data: revisions } = await client
      .from("excavaguard_run_revisions")
      .select("revision")
      .eq("run_id", runId)
      .order("revision", { ascending: true });
    expect((revisions ?? []).length).toBeGreaterThanOrEqual(5);

    const { data: artifactRows } = await client
      .from("excavaguard_report_artifacts")
      .select("kind,storage_path,sha256")
      .eq("run_id", runId);
    expect(artifactRows).toHaveLength(3);
    for (const artifact of artifactRows ?? []) {
      cleanupObjectPaths.add(artifact.storage_path);
    }
    const artifacts = draft.artifacts as Json[];
    expect(existsSync(dirname(resolve(String(artifacts[0].relative_path))))).toBe(false);

    const workbook = (agentRun.downloads as Json[])
      .find((artifact) => artifact.kind === "workbook")!;
    const downloadResponse = await artifactGET(
      new Request(`http://localhost${String(workbook.url)}`),
      {
        params: Promise.resolve({
          draftId: String((draft.ref as Json).artifact_id),
          fileName: String(workbook.file_name),
        }),
      },
    );
    expect(downloadResponse.status).toBe(200);
    expect((await downloadResponse.arrayBuffer()).byteLength).toBe(workbook.size_bytes);

    const access: LocalAccess = {
      owner_id: "local-operator",
      project_id: DEFAULT_PROJECT_ID,
    };
    const current = await readRun(runId, access);
    const concurrent = await Promise.allSettled([
      saveRun({ ...current, updated_at: new Date().toISOString() }, current.revision, access),
      saveRun({ ...current, updated_at: new Date().toISOString() }, current.revision, access),
    ]);
    expect(concurrent.filter((result) => result.status === "fulfilled")).toHaveLength(1);
    expect(concurrent.find((result) => result.status === "rejected")).toMatchObject({
      reason: { code: "RUN_CONFLICT" },
    });
    const latest = await readRun(runId, access);

    const reviewResponse = await reviewPOST(new Request(
      `http://localhost/api/runs/${runId}/review`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: latest.revision,
          draft_ref: draft.ref,
          decision: "accepted",
          reason: "SIMULATED Supabase Provider 自动化验收，不代表正式工程签发。",
          evaluations: riskEvaluationTargets(latest.result?.payload).map((target) => ({
            risk_item_index: target.risk_item_index,
            disposition: "confirmed",
            comment: "SIMULATED Supabase Provider 逐项风险评价。",
          })),
        }),
      },
    ), { params: Promise.resolve({ runId }) });
    expect(reviewResponse.status).toBe(200);
    expect((await reviewResponse.json() as Json).record).toMatchObject({
      review: { decision: "accepted" },
    });

    const workbookRow = (artifactRows ?? []).find(
      (artifact) => artifact.kind === "workbook",
    )!;
    const { SUPABASE_STORAGE_BUCKET } = readIntegrationConfig("supabase");
    expect((await client.storage
      .from(SUPABASE_STORAGE_BUCKET)
      .remove([workbookRow.storage_path])).error).toBeNull();
    expect((await client.storage
      .from(SUPABASE_STORAGE_BUCKET)
      .upload(workbookRow.storage_path, new TextEncoder().encode("tampered"), {
        contentType:
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      })).error).toBeNull();
    const tamperedResponse = await artifactGET(
      new Request(`http://localhost${String(workbook.url)}`),
      {
        params: Promise.resolve({
          draftId: String((draft.ref as Json).artifact_id),
          fileName: String(workbook.file_name),
        }),
      },
    );
    expect(tamperedResponse.status).toBe(409);
    expect(await tamperedResponse.json()).toMatchObject({
      error: { code: "ARTIFACT_CHANGED" },
    });

    const reviewed = await readRun(runId, access);
    expect(await deleteRun(runId, reviewed.revision, access)).toEqual({
      deleted: true,
      cleanup_complete: true,
    });
    await expect(readRun(runId, access)).rejects.toMatchObject({ code: "RUN_NOT_FOUND" });
    expect((await client
      .from("excavaguard_report_artifacts")
      .select("artifact_id")
      .eq("run_id", runId)).data).toHaveLength(0);
  }, 90_000);
});
