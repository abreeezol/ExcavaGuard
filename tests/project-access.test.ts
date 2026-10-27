import { randomBytes } from "node:crypto";
import { mkdtemp, writeFile, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { beforeEach, afterEach, describe, it, expect, vi } from "vitest";
import { hashPassword } from "@/server/auth/password";
import { accessDirectorySchema, type AccessDirectory } from "@/contracts/project-access";
import { GET as sessionGET, POST as login, DELETE as logout } from "@/app/api/session/route";
import { GET as projectsGET, POST as createProject } from "@/app/api/projects/route";
import { POST as selectProject } from "@/app/api/projects/select/route";
import { GET as filesGET, POST as upload } from "@/app/api/monitoring-files/route";
import { GET as thresholdsGET } from "@/app/api/standards/route";
import { GET as normsGET, POST as normsPOST } from "@/app/api/project-standards/route";
import { GET as runsGET, POST as run } from "@/app/api/runs/route";
import { GET as runGET } from "@/app/api/runs/[runId]/route";
import { POST as review } from "@/app/api/runs/[runId]/review/route";
import { GET as download } from "@/app/api/report-artifacts/[draftId]/[fileName]/route";
import { requireAccess } from "@/server/access";

const A = "11111111-1111-4111-8111-111111111111";
const B = "22222222-2222-4222-8222-222222222222";
const IDS = { admin: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", engineer: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  reviewer: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", viewer: "dddddddd-dddd-4ddd-8ddd-dddddddddddd", outsider: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee" };
const PASSWORD = "synthetic-test-password-2026";
const HASH = hashPassword(PASSWORD);
let root: string, directoryFile: string;
const artifacts: string[] = [];
const base = "http://localhost:3000";
function request(path: string, cookie = "", body?: unknown, project?: string) {
  return new Request(base + path, { method: body === undefined ? "GET" : "POST",
    headers: { ...(cookie ? { cookie } : {}), ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(project ? { "X-Excavaguard-Project": project } : {}) },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
}
const token = (response: Response) => response.headers.get("set-cookie")!.split(";")[0];
async function user(name: keyof typeof IDS, project?: string) {
  const result = await login(request("/api/session", "", { username: name, password: PASSWORD }));
  expect(result.status).toBe(200);
  let cookie = token(result);
  if (project) { const selection = await selectProject(request("/api/projects/select", cookie, { project_id: project })); expect(selection.status).toBe(200); cookie = token(selection); }
  return cookie;
}
async function modifyDirectory(change: (directory: AccessDirectory) => void) {
  const directory = accessDirectorySchema.parse(JSON.parse(await readFile(directoryFile, "utf8")));
  change(directory); await writeFile(directoryFile, JSON.stringify(directory));
}
beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), "excavaguard-project-auth-")); directoryFile = join(root, "directory.json");
  vi.stubEnv("EXCAVAGUARD_ACCESS_FILE", directoryFile);
  vi.stubEnv("EXCAVAGUARD_STORAGE_PROVIDER", "local");
  vi.stubEnv("EXCAVAGUARD_UPLOAD_ROOT", join(root, "uploads"));
  vi.stubEnv("EXCAVAGUARD_RUN_ROOT", join(root, "runs"));
  vi.stubEnv("EXCAVAGUARD_PROJECT_STANDARDS_ROOT", join(root, "standards"));
  vi.stubEnv("EXCAVAGUARD_PROJECT_ID", A);
  vi.stubEnv("EXCAVAGUARD_ACCESS_PASSWORD", "");
  vi.stubEnv("EXCAVAGUARD_SESSION_SECRET", "test-session-secret-at-least-thirty-two-characters");
  const directory: AccessDirectory = { version: 1, session_secret: randomBytes(32).toString("hex"),
    users: Object.entries(IDS).map(([username, id]) => ({ id, username, name: username, password_hash: HASH, disabled: false, is_admin: username === "admin" })),
    projects: [{ id: A, name: "合成工程A", active: true }, { id: B, name: "合成工程B", active: true }],
    memberships: [ { user_id: IDS.admin, project_id: A, role: "admin" }, { user_id: IDS.admin, project_id: B, role: "admin" },
      { user_id: IDS.engineer, project_id: A, role: "engineer" }, { user_id: IDS.reviewer, project_id: A, role: "reviewer" },
      { user_id: IDS.viewer, project_id: A, role: "viewer" }, { user_id: IDS.outsider, project_id: B, role: "engineer" } ],
  };
  await writeFile(directoryFile, JSON.stringify(directory));
});
afterEach(async () => {
  for (const artifact of artifacts.splice(0)) await rm(artifact, { recursive: true, force: true });
  await rm(root, { recursive: true, force: true }); vi.unstubAllEnvs();
});

describe("账号登录与获授权项目选择", () => {
  it("未登录不披露项目；账号登录后必须先选择工程", async () => {
    const before = await sessionGET(request("/api/session")).json();
    expect(before.authenticated).toBe(false); expect(before.projects).toEqual([]);
    expect(projectsGET(request("/api/projects")).status).toBe(401);
    const cookie = await user("engineer");
    const status = await sessionGET(request("/api/session", cookie)).json();
    expect(status.project_id).toBeNull(); expect(status.projects.map((p: { id: string }) => p.id)).toEqual([A]);
    expect(status.user.id).toBe(IDS.engineer);
    expect(JSON.stringify(status)).not.toMatch(/password_hash|session_secret|scrypt:/);
    expect((await filesGET(request("/api/monitoring-files", cookie))).status).toBe(403);
  });
  it("密码错误、篡改签名、改密旧会话和跨站请求均拒绝", async () => {
    expect((await login(request("/api/session", "", { username: "engineer", password: "wrong" }))).status).toBe(401);
    const cookie = await user("engineer", A);
    const tampered = cookie.replace(/v2\./, "v3.");
    expect(() => requireAccess(request("/api/runs", tampered))).toThrow();
    const cross = new Request(base + "/api/session", { headers: { origin: "https://untrusted.example", cookie } });
    expect(sessionGET(cross).status).toBe(403);
    expect(logout(new Request(base + "/api/session", { method: "DELETE", headers: { cookie } })).headers.get("set-cookie")).toContain("Max-Age=0");
    await modifyDirectory(directory => { directory.users.find(u => u.username === "engineer")!.password_hash = hashPassword("replacement-test-password-2026"); });
    expect((await runsGET(request("/api/runs", cookie))).status).toBe(401);
  });
  it("禁止选择非成员工程，修改请求project_id不能隐式切换", async () => {
    const cookie = await user("engineer", A);
    expect((await selectProject(request("/api/projects/select", cookie, { project_id: B }))).status).toBe(403);
    expect((await runsGET(request("/api/runs", cookie, undefined, B))).status).toBe(403);
    expect(requireAccess(request("/api/runs", cookie)).project_id).toBe(A);
  });
  it("同一账号可在授权工程间切换，并拒绝旧标签页的项目预期", async () => {
    const a = await user("admin", A);
    const selection = await selectProject(request("/api/projects/select", a, { project_id: B }));
    const b = token(selection);
    expect(requireAccess(request("/api/runs", b)).project_id).toBe(B);
    expect((await runsGET(request("/api/runs", b, undefined, A))).status).toBe(403);
    expect((await runsGET(request("/api/runs", b, undefined, B))).status).toBe(200);
  });
  it("撤销成员关系和停用账号立即影响现有会话", async () => {
    const cookie = await user("engineer", A);
    await modifyDirectory(directory => { directory.memberships = directory.memberships.filter(m => m.user_id !== IDS.engineer); });
    expect((await runsGET(request("/api/runs", cookie))).status).toBe(403);
    await modifyDirectory(directory => { directory.users.find(u => u.id === IDS.engineer)!.disabled = true; });
    expect((await runsGET(request("/api/runs", cookie))).status).toBe(401);
  });
  it("管理员创建工程只授权创建者，普通成员不可创建", async () => {
    const engineer = await user("engineer", A);
    expect((await createProject(request("/api/projects", engineer, { name: "新工程" }))).status).toBe(403);
    const admin = await user("admin", A);
    const created = await createProject(request("/api/projects", admin, { name: "新工程" }));
    expect(created.status).toBe(201);
    const project = (await created.json()).project;
    expect((await selectProject(request("/api/projects/select", admin, { project_id: project.id }))).status).toBe(200);
    expect((await selectProject(request("/api/projects/select", engineer, { project_id: project.id }))).status).toBe(403);
    expect((await createProject(request("/api/projects", admin, { name: "新工程" }))).status).toBe(409);
  });
  it("只读成员可加载文件和规范，但不能上传、运行、修改规范或复核", async () => {
    const cookie = await user("viewer", A);
    expect((await filesGET(request("/api/monitoring-files", cookie))).status).toBe(200);
    expect((await normsGET(request("/api/project-standards", cookie))).status).toBe(200);
    expect((await thresholdsGET(request("/api/standards", cookie))).status).toBe(200);
    expect((await upload(request("/api/monitoring-files", cookie, {}))).status).toBe(403);
    expect((await run(request("/api/runs", cookie, {}))).status).toBe(403);
    expect((await normsPOST(request("/api/project-standards", cookie, {}))).status).toBe(403);
    const engineer = await user("engineer", A);
    expect((await review(request("/api/runs/test/review", engineer, {}), { params: Promise.resolve({ runId: A }) })).status).toBe(403);
  });
  it("旧密码登录创建工程后仍保持登录，项目选择持久化且不改变默认工程ID", async () => {
    await rm(directoryFile);
    vi.stubEnv("EXCAVAGUARD_ACCESS_PASSWORD", PASSWORD);
    const response = await login(request("/api/session", "", { password: PASSWORD }));
    const cookie = token(response);
    const created = await createProject(request("/api/projects", cookie, { name: "兼容模式新工程" }));
    expect(created.status).toBe(201); const project = (await created.json()).project;
    const selected = await selectProject(request("/api/projects/select", cookie, { project_id: project.id }));
    expect(selected.status).toBe(200);
    expect(requireAccess(request("/api/runs", token(selected))).project_id).toBe(project.id);
    expect(process.env.EXCAVAGUARD_PROJECT_ID).toBe(A);
    expect((await sessionGET(request("/api/session", cookie)).json()).authenticated).toBe(true);
  });
  it("并发新建不覆盖成员目录，停用工程立即阻断读取", async () => {
    const cookie = await user("admin", A);
    const results = await Promise.all([createProject(request("/api/projects", cookie, { name: "并发工程一" })), createProject(request("/api/projects", cookie, { name: "并发工程二" }))]);
    expect(results.map(r => r.status)).toEqual([201, 201]);
    expect((await sessionGET(request("/api/session", cookie)).json()).projects).toHaveLength(4);
    await modifyDirectory(directory => { directory.projects.find(p => p.id === A)!.active = false; });
    expect((await runsGET(request("/api/runs", cookie))).status).toBe(403);
  });
  it("真实上传→项目规范→报告→同项目复核共享；其他项目不可读或下载", async () => {
    const engineer = await user("engineer", A), reviewer = await user("reviewer", A), outsider = await user("outsider", B);
    const form = new FormData();
    form.set("file", new File(["point_id,timestamp,metric_key,value,unit,data_origin\nSIMULATED-P,2026-10-01,wall_top_horizontal_displacement,0,mm,simulated\nSIMULATED-P,2026-10-02,wall_top_horizontal_displacement,12,mm,simulated\n"], "synthetic.csv"));
    const uploaded = await upload(new Request(base + "/api/monitoring-files", { method: "POST", headers: { cookie: engineer, "X-Excavaguard-Project": A }, body: form }));
    expect(uploaded.status).toBe(201); const file = (await uploaded.json()).file;
    expect(file.project_id).toBe(A);
    expect((await (await filesGET(request("/api/monitoring-files", reviewer))).json()).files).toHaveLength(1);
    expect((await (await filesGET(request("/api/monitoring-files", outsider))).json()).files).toHaveLength(0);
    const norm = new FormData();
    for (const [key, value] of Object.entries({ standard_name: "合成要求（非真实规范）", standard_version: "TEST/T999-2026", region: "测试地区", applicability: "仅软件合成测试", confirmed: "true" })) norm.set(key, value);
    norm.set("file", new File(["5.1.1 基坑监测应核对水平位移，报警时应复测并记录监测日报。"], "test.txt"));
    expect((await normsPOST(new Request(base + "/api/project-standards", { method: "POST", headers: { cookie: engineer }, body: norm }))).status).toBe(201);
    expect((await (await normsGET(request("/api/project-standards", outsider))).json()).documents).toHaveLength(0);
    const input = { project_id: A, monitoring_file_id: file.file_id, report_date: "2026-10-02", context: { safety_level: "一级", support_type: "地下连续墙", excavation_depth_m: 20 }, options: { generate_report: true, report_mode: "template" } };
    expect((await run(request("/api/runs", outsider, { ...input, project_id: B }))).status).toBe(404);
    const response = await run(request("/api/runs", engineer, input));
    const body = await response.json(); expect(response.status).toBe(200);
    expect(body.record.owner_id).toBe(IDS.engineer); expect(body.record.request.project.name).toBe("合成工程A");
    expect(body.agent_run.state.audit_result.valid).toBe(true);
    const draft = body.agent_run.state.report_draft;
    artifacts.push(dirname(resolve(draft.artifacts[0].relative_path)));
    expect((await runsGET(request("/api/runs", reviewer))).status).toBe(200);
    expect((await (await runsGET(request("/api/runs", reviewer))).json()).runs).toHaveLength(1);
    const context = { params: Promise.resolve({ runId: body.run_id }) };
    expect((await runGET(request("/api/runs/" + body.run_id, reviewer), context)).status).toBe(200);
    expect((await runGET(request("/api/runs/" + body.run_id, outsider), context)).status).toBe(404);
    const params = { params: Promise.resolve({ draftId: draft.ref.artifact_id, fileName: draft.artifacts[0].file_name }) };
    expect((await download(request("/api/report-artifacts/test", reviewer), params)).status).toBe(200);
    expect((await download(request("/api/report-artifacts/test", outsider), params)).status).toBe(404);
    const accepted = await review(request("/api/runs/test/review", reviewer, { expected_revision: body.record.revision, draft_ref: draft.ref, decision: "accepted", reason: "合成测试复核，不是正式签发。" }), context);
    expect(accepted.status).toBe(200);
    const reviewed = (await accepted.json()).record;
    expect(reviewed.review.owner_id).toBe(IDS.reviewer);
    expect(reviewed.owner_id).toBe(IDS.engineer);
  });
});
