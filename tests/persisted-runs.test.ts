import { createHash, randomUUID } from "node:crypto";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_PROJECT_ID, type LocalAccess } from "@/contracts/access";
import type { PersistedRun } from "@/contracts/runs";
import type { ReportDraft, ReportArtifact } from "@/contracts/agent-runtime";
import { readRun, saveRun, listRuns } from "@/server/storage/run-store";
import { executeAgentRun } from "@/server/agents/executor";
import { reviewRun, resumeRun } from "@/server/runs";
import { GET as artifactGET } from "@/app/api/report-artifacts/[draftId]/[fileName]/route";
import { requireAccess } from "@/server/access";
import { GET as sessionGET, POST as sessionPOST, DELETE as sessionDELETE } from "@/app/api/session/route";
import { saveFile, listFiles, localPathOf } from "@/server/storage/monitoring-file-store";

const ACCESS: LocalAccess = { owner_id: "local-operator", project_id: DEFAULT_PROJECT_ID };
let storage: string;
const artifactDirectories: string[] = [];
const hash = (bytes: Uint8Array | string) => createHash("sha256").update(bytes).digest("hex");

beforeEach(async () => {
  storage = await mkdtemp(join(tmpdir(), "excavaguard-run-tests-"));
  vi.stubEnv("EXCAVAGUARD_RUN_ROOT", join(storage, "runs"));
  vi.stubEnv("EXCAVAGUARD_UPLOAD_ROOT", join(storage, "uploads"));
  vi.stubEnv("EXCAVAGUARD_STORAGE_PROVIDER", "local");
  vi.stubEnv("EXCAVAGUARD_ACCESS_PASSWORD", "");
  vi.stubEnv("EXCAVAGUARD_PROJECT_ID", DEFAULT_PROJECT_ID);
});

afterEach(async () => {
  await rm(storage, { recursive: true, force: true });
  for (const directory of artifactDirectories.splice(0)) await rm(directory, { recursive: true, force: true });
  vi.unstubAllEnvs();
});

function emptyRun(): PersistedRun {
  const runId = randomUUID();
  const at = new Date().toISOString();
  return {
    schema: "excavaguard.persisted_run/v1", run_id: runId, revision: 1,
    owner_id: ACCESS.owner_id, project_id: ACCESS.project_id,
    created_at: at, updated_at: at, execution_status: "completed",
    lease_until: null, result: null, error: null, review: null,
    request: {
      project_id: ACCESS.project_id, monitoring_file_id: randomUUID(), report_date: "2026-10-14",
      context: { safety_level: "一级", support_type: "地下连续墙", excavation_depth_m: 20 },
    },
  };
}

/** 存储/复核测试用已审计状态；真实 Excel 审计另由 wide-upload-and-run 验证。 */
async function auditedRun(valid = true): Promise<PersistedRun> {
  const record = emptyRun();
  const artifactId = randomUUID();
  const directory = resolve("var/report-artifacts", artifactId);
  await mkdir(directory, { recursive: true });
  artifactDirectories.push(directory);
  const artifacts: ReportArtifact[] = [];
  for (const [kind, suffix] of [
    ["workbook", ".xlsx"], ["cover_markdown", "_封面.md"], ["appendices_markdown", "_附表及清单.md"],
  ] as const) {
    const fileName = `监测日报_2026-10-14_草稿${suffix}`;
    const bytes = new TextEncoder().encode(`test-only-${kind}`);
    await writeFile(join(directory, fileName), bytes);
    artifacts.push({
      kind, file_name: fileName, relative_path: `var/report-artifacts/${artifactId}/${fileName}`,
      media_type: "application/octet-stream", sha256: hash(bytes), size_bytes: bytes.byteLength, sheets: [],
    });
  }
  const payload = { schema: "excavaguard.daily_report_input/v1", items: [] };
  const execution = await executeAgentRun({ enginePayload: payload, runId: record.run_id, maxRevisionRounds: 0 }, {
    render: async (input) => ({
      draft: {
        ref: { artifact_id: artifactId, schema: "excavaguard.report_draft/v1", version: 1, content_hash: hash("fixture") },
        source_refs: { engine: input.engineSnapshot.ref, evidence: null, analysis: null },
        artifacts, fact_bindings: [], artifact_bindings: [], citations: [], review_required: true,
        payload: { status: "draft" },
      } satisfies ReportDraft,
      trace: {},
    }),
    validate: async ({ draft }) => ({
      audit: {
        ref: { artifact_id: randomUUID(), schema: "excavaguard.audit_result/v1", version: 1, content_hash: hash("audit") },
        draft_ref: draft.ref, valid, checks: [{ name: "fixture", valid }],
        issues: valid ? [] : [{
          issue_id: "unresolved", code: "REPORT_CONTENT_MISMATCH", severity: "error",
          blocking: true, responsibility: "report-delivery", path: "payload", message: "测试未通过。",
        }],
      },
      trace: {},
    }),
  });
  record.result = {
    run_id: record.run_id, project_id: record.project_id, created_at: record.created_at,
    monitoring_file_id: record.request.monitoring_file_id, standards_file_id: null,
    engine: { elapsed_ms: 1, records: 0 }, payload,
    agent_run: { state: execution.state, terminal_action: execution.terminalAction, steps: execution.steps, downloads: [] },
  };
  return saveRun(record, 0, ACCESS);
}

function reviewInput(record: PersistedRun, decision: "accepted" | "needs_changes" | "rejected" = "accepted") {
  return {
    expected_revision: record.revision, draft_ref: record.result!.agent_run!.state.report_draft!.ref,
    decision, reason: "测试草稿复核记录。",
  };
}

async function download(record: PersistedRun) {
  const draft = record.result!.agent_run!.state.report_draft!;
  return artifactGET(new Request("http://localhost/api/report-artifacts/test"), {
    params: Promise.resolve({ draftId: draft.ref.artifact_id, fileName: draft.artifacts[0].file_name }),
  });
}

describe("运行持久化与复核", () => {
  it("从磁盘恢复并保留旧修订；同修订的并发提交只有一个成功", async () => {
    const original = await saveRun(emptyRun(), 0, ACCESS);
    const outcomes = await Promise.allSettled([
      saveRun({ ...original, error: { code: "A", message: "A" } }, 1, ACCESS),
      saveRun({ ...original, error: { code: "B", message: "B" } }, 1, ACCESS),
    ]);
    expect(outcomes.filter((outcome) => outcome.status === "fulfilled")).toHaveLength(1);
    expect(outcomes.find((outcome) => outcome.status === "rejected")).toMatchObject({ reason: { code: "RUN_CONFLICT" } });
    expect((await readRun(original.run_id, ACCESS)).revision).toBe(2);
    expect(JSON.parse(await readFile(join(storage, "runs", original.run_id, "1.json"), "utf8"))).toEqual(original);
    expect(await listRuns(ACCESS)).toHaveLength(1);
  });

  it("最新记录损坏时明确失败，不回退到旧成功状态", async () => {
    const record = await saveRun(emptyRun(), 0, ACCESS);
    await writeFile(join(storage, "runs", record.run_id, "1.json"), "{");
    await expect(readRun(record.run_id, ACCESS)).rejects.toMatchObject({ code: "STORAGE_ERROR" });
    await expect(listRuns(ACCESS)).rejects.toMatchObject({ code: "STORAGE_ERROR" });
  });

  it("拒绝跨项目读取且非法 UUID 不能越界", async () => {
    const record = await saveRun(emptyRun(), 0, ACCESS);
    await expect(readRun(record.run_id, { ...ACCESS, project_id: randomUUID() })).rejects.toMatchObject({ code: "RUN_NOT_FOUND" });
    await expect(readRun("../other", ACCESS)).rejects.toMatchObject({ code: "INVALID_REQUEST" });
  });

  it("接受绑定当前草稿，保存理由与轨迹，源事实和文件指纹不变", async () => {
    const record = await auditedRun();
    const reviewed = await reviewRun(record.run_id, reviewInput(record), ACCESS);
    expect(reviewed.review).toMatchObject({ decision: "accepted", owner_id: "local-operator" });
    expect(reviewed.result?.payload).toEqual(record.result?.payload);
    expect(reviewed.result?.agent_run?.state.report_draft).toEqual(record.result?.agent_run?.state.report_draft);
    expect(reviewed.result?.agent_run?.state.audit_result).toEqual(record.result?.agent_run?.state.audit_result);
    expect(reviewed.result?.agent_run?.state.trace.at(-1)).toMatchObject({ capability: "human-review", output_versions: { decision: "accepted" } });
    expect((await download(reviewed)).status).toBe(200);
    await expect(reviewRun(record.run_id, reviewInput(record), ACCESS)).rejects.toMatchObject({ code: "RUN_CONFLICT" });
    await expect(reviewRun(record.run_id, reviewInput(reviewed), ACCESS)).rejects.toMatchObject({ code: "INVALID_TRANSITION" });
  });

  it.each(["needs_changes", "rejected"] as const)("决定 %s 停止自动流程，保留文件并关闭下载", async (decision) => {
    const record = await auditedRun();
    expect((await download(record)).status).toBe(200);
    const reviewed = await reviewRun(record.run_id, reviewInput(record, decision), ACCESS);
    expect(reviewed.result?.agent_run?.state.run.status).toBe("stopped");
    expect(reviewed.result?.agent_run?.downloads).toEqual([]);
    expect((await download(reviewed)).status).toBe(404);
    expect(await readFile(resolve(reviewed.result!.agent_run!.state.report_draft!.artifacts[0].relative_path))).toBeTruthy();
    await expect(resumeRun(reviewed.run_id, reviewed.revision, ACCESS)).rejects.toMatchObject({ code: "INVALID_TRANSITION" });
  });

  it("拒绝旧草稿哈希和未通过审计的复核", async () => {
    const record = await auditedRun();
    const input = reviewInput(record);
    await expect(reviewRun(record.run_id, { ...input, draft_ref: { ...input.draft_ref, content_hash: hash("stale") } }, ACCESS)).rejects.toMatchObject({ code: "RUN_CONFLICT" });
    const failed = await auditedRun(false);
    await expect(reviewRun(failed.run_id, reviewInput(failed), ACCESS)).rejects.toMatchObject({ code: "INVALID_TRANSITION" });
    expect((await download(failed)).status).toBe(404);
  });

  it("文件在审计后被替换时拒绝下载和接受，仍可记录退回", async () => {
    const record = await auditedRun();
    await writeFile(resolve(record.result!.agent_run!.state.report_draft!.artifacts[0].relative_path), "tampered");
    expect((await download(record)).status).toBe(409);
    await expect(reviewRun(record.run_id, reviewInput(record), ACCESS)).rejects.toMatchObject({ code: "ARTIFACT_CHANGED" });
    expect((await reviewRun(record.run_id, reviewInput(record, "needs_changes"), ACCESS)).review?.decision).toBe("needs_changes");
  });

  it("并发上传不会丢索引，绑定项目且修改文件会阻止分析读取", async () => {
    const files = await Promise.all([1, 2, 3].map((value) => saveFile({
      kind: "monitoring", originalName: `test-${value}.csv`, bytes: new TextEncoder().encode(String(value)),
    })));
    expect(await listFiles("monitoring", ACCESS.project_id)).toHaveLength(3);
    expect(await listFiles("monitoring", randomUUID())).toHaveLength(0);
    const path = await localPathOf(files[0].file_id);
    await writeFile(path!, "changed");
    await expect(localPathOf(files[0].file_id)).rejects.toMatchObject({ code: "STORAGE_ERROR" });
  });
});

describe("单操作者访问控制", () => {
  it("本地模式拒绝非 loopback、跨站 Origin 和伪装 Host", () => {
    expect(requireAccess(new Request("http://localhost/api/runs"))).toEqual(ACCESS);
    for (const request of [
      new Request("http://other.example/api/runs"),
      new Request("http://localhost/api/runs", { headers: { Origin: "http://other.example" } }),
      new Request("http://localhost/api/runs", { headers: { Host: "other.example" } }),
    ]) expect(() => requireAccess(request)).toThrow();
    expect(() => requireAccess(new Request("http://localhost/api/runs"), randomUUID())).toThrow();
  });

  it("生产未配置拒绝业务访问，不泄露配置", async () => {
    vi.stubEnv("NODE_ENV", "production");
    const response = sessionGET(new Request("https://demo.example/api/session"));
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ error: { code: "ACCESS_NOT_CONFIGURED" } });
  });

  it("密码登录签发 HttpOnly 会话，篡改/过期失效，退出清空", async () => {
    vi.stubEnv("EXCAVAGUARD_ACCESS_PASSWORD", "test-password-1234");
    vi.stubEnv("EXCAVAGUARD_SESSION_SECRET", "test-only-session-key-12345678901234567890");
    const url = "https://demo.example/api/session";
    expect((await sessionGET(new Request(url)).json()).authenticated).toBe(false);
    const response = await sessionPOST(new Request(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: "test-password-1234" }),
    }));
    expect(response.status).toBe(200);
    const cookie = response.headers.get("set-cookie")!;
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("SameSite=Strict");
    expect(cookie).toContain("Secure");
    expect(requireAccess(new Request(url, { headers: { cookie } }))).toEqual(ACCESS);
    expect(() => requireAccess(new Request(url, { headers: { cookie: cookie.replace(/\d/, "0") } }))).toThrow();
    expect(sessionDELETE(new Request(url, { method: "DELETE", headers: { cookie } })).headers.get("set-cookie")).toContain("Max-Age=0");
    const wrong = await sessionPOST(new Request(url, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: "wrong" }),
    }));
    expect(wrong.status).toBe(401);
  });
});
