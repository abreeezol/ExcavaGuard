// Run with the existing TypeScript loader and an installed playwright-core module.
// All /api requests are intercepted; this suite never writes shared project data.
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { persistedRunSchema } from "@/contracts/runs";
import { createAgentRunState, recordReportDraft, recordAuditResult } from "@/server/agents/supervisor";

const modulePath = process.env.EXCAVAGUARD_PLAYWRIGHT_MODULE;
if (!modulePath) throw new Error("Set EXCAVAGUARD_PLAYWRIGHT_MODULE to the installed playwright-core module.");
const { chromium } = await import(modulePath);
const browser = await chromium.launch({
  executablePath: process.env.EXCAVAGUARD_BROWSER_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: true, chromiumSandbox: false,
});
const origin = process.env.EXCAVAGUARD_UI_ORIGIN ?? "http://localhost:3000";
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.clock.install();
const projectId = randomUUID();
const otherProjectId = randomUUID();
const fileId = randomUUID();
const actor = { id: randomUUID(), name: "合成测试工程师" };
const at = "2026-11-03T00:00:00.000Z";
const ref = schema => ({ artifact_id: randomUUID(), schema, version: 1, content_hash: "a".repeat(64) });
const file = {
  file_id: fileId, project_id: projectId, kind: "monitoring", original_name: "合成监测.csv",
  size_bytes: 80, media_type: "text/csv", sha256: "a".repeat(64), created_at: at, storage: "local",
};

function fixture(createdAt, name = "历史工程名", fixtureProjectId = projectId) {
  const runId = randomUUID();
  const risk = { point_id: "P-01", metric_key: "wall_top_horizontal_displacement",
    metric_name: "围护墙顶部水平位移", timestamp: "2026-11-03T08:00:00+08:00", risk_level: "报警" };
  const unknownRisk = { ...risk, point_id: "P-02", risk_level: "未知" };
  const payload = {
    items: [risk, unknownRisk], alerts: [risk], review_queue: [unknownRisk],
    summary: { total: 2, overall_risk_level: "报警", by_risk_level: { 报警: 1, 未知: 1 } },
  };
  let state = createAgentRunState({
    runId, createdAt, deadlineAt: "2026-11-10T00:00:00.000Z", maxModelCalls: 0,
    engineSnapshot: { ref: ref("excavaguard.daily_report_input/v1"), payload },
  });
  const draftRef = ref("excavaguard.report_draft/v1");
  state = recordReportDraft(state, {
    ref: draftRef, source_refs: { engine: state.engine_snapshot.ref, evidence: null, analysis: null },
    artifacts: ["workbook", "cover_markdown", "appendices_markdown"].map((kind, index) => ({
      kind, file_name: `test-${index}.txt`, relative_path: `var/report-artifacts/${draftRef.artifact_id}/test-${index}.txt`,
      media_type: "text/plain", sha256: "b".repeat(64), size_bytes: 1, sheets: [],
    })),
    fact_bindings: [], artifact_bindings: [], citations: [], review_required: true, payload: {},
  }, createdAt);
  state = recordAuditResult(state, {
    ref: ref("excavaguard.audit_result/v1"), draft_ref: draftRef, valid: true,
    checks: [{ name: "synthetic-ui-only", valid: true }], issues: [],
  }, createdAt);
  return persistedRunSchema.parse({
    schema: "excavaguard.persisted_run/v1", run_id: runId, revision: 1,
    owner_id: actor.id, created_by: actor, project_id: fixtureProjectId,
    created_at: createdAt, updated_at: createdAt, execution_status: "completed",
    lease_until: null, error: null, review: null,
    request: { project_id: fixtureProjectId, monitoring_file_id: fileId, report_date: "2026-11-03",
      project: { name }, context: { safety_level: "一级", support_type: "地下连续墙", excavation_depth_m: 15 },
      project_standard_ids: [], options: { report_mode: "template", generate_report: true } },
    result: { run_id: runId, project_id: fixtureProjectId, created_at: createdAt, monitoring_file_id: fileId,
      standards_file_id: null, engine: { elapsed_ms: 1, records: 1 }, payload,
      agent_run: { state, steps: 3, downloads: [], terminal_action: {
        type: "handoff_to_human", agent: "supervisor", reason_code: "AUDIT_PASSED", details: "合成测试",
      } } },
  });
}
const latest = fixture(at);
const older = fixture("2026-11-01T00:00:00.000Z");
const empty = { ...fixture("2026-11-05T00:00:00.000Z"), result: null };
const failed = { ...fixture("2026-11-04T00:00:00.000Z"), execution_status: "failed", error: { code: "TEST", message: "合成失败" }, result: null };
let records = [older, failed, latest, empty];
let authenticated = true;
let role = "admin";
let activeProject = projectId;
let canCreateProject = false;
let authorizedProjects = [
  { id: projectId, name: "当前工程名" },
  { id: otherProjectId, name: "第二工程" },
];
let historyFailure = false;
let monitoringFiles = [file];
let engineeringType = "foundation_pit";
let sceneParameters = null;
let supportedReports = null;
let failNextQuickRun = false;
const manifests = {
  foundation_pit: JSON.parse(readFileSync(new URL("../engineering-adapters/foundation-pit/manifest.json", import.meta.url))),
  tunnel: JSON.parse(readFileSync(new URL("../engineering-adapters/tunnel-monitoring/manifest.json", import.meta.url))),
};
const writes = [];
const errors = [];
page.on("pageerror", error => errors.push(error.message));
await page.route("**/api/**", async route => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  const json = body => route.fulfill({ json: body });
  const view = record => ({ ...record.result, record });
  if (request.method() !== "GET" && path !== "/api/report-windows") {
    let body = null;
    try { body = request.postDataJSON(); } catch { /* multipart upload */ }
    writes.push({ path, body });
  }
  if (path === "/api/session") return json({
    mode: "accounts", authenticated, user: authenticated ? actor : null,
    project_id: authenticated ? activeProject : null, can_create_project: canCreateProject,
    projects: authenticated ? authorizedProjects.map(project => ({ ...project, role })) : [],
  });
  if (path === "/api/projects/select") { activeProject = request.postDataJSON().project_id; return json({ ok: true }); }
  if (path === "/api/projects" && request.method() === "POST") {
    const body = request.postDataJSON();
    const id = randomUUID();
    authorizedProjects.push({ id, name: body.name });
    engineeringType = body.engineering_type;
    sceneParameters = body.parameters ?? null;
    return route.fulfill({ status: 201, json: {
      project: { id, name: body.name, active: true, role: "admin", engineering: {
        adapter_id: manifests[engineeringType].id,
        adapter_version: manifests[engineeringType].version,
        parameters: sceneParameters,
        revision: sceneParameters ? 1 : undefined,
      } },
    } });
  }
  if (path === "/api/projects") return json({
    engineering_types: [{ id: "foundation_pit", name: "基坑工程" }, { id: "tunnel", name: "隧道工程" }],
    engineering_setups: [
      { id: "foundation_pit", name: "基坑工程", adapter_version: manifests.foundation_pit.version,
        supported_reports: manifests.foundation_pit.supported_reports, core_fields: manifests.foundation_pit.core_fields },
      { id: "tunnel", name: "隧道工程", adapter_version: manifests.tunnel.version,
        supported_reports: manifests.tunnel.supported_reports, core_fields: manifests.tunnel.core_fields },
    ],
  });
  if (path === "/api/projects/current/engineering") {
    if (request.method() === "PUT") {
      sceneParameters = request.postDataJSON().parameters;
      return json({ engineering: { parameters: sceneParameters, revision: 1 } });
    }
    const manifest = manifests[engineeringType];
    return json({ engineering_type: { id: engineeringType, name: engineeringType === "tunnel" ? "隧道工程" : "基坑工程" },
      adapter: { ...manifest, supported_reports: supportedReports ?? manifest.supported_reports }, parameters: sceneParameters, revision: 0,
      monitoring_metrics: [{ key: "surface_settlement", name: "地表沉降", semantics: ["cumulative_settlement"] }] });
  }
  if (path === "/api/report-windows") return json({ detected_metrics: [{ key: "surface_settlement", name: "地表沉降", supported: true }],
    available_dates: ["2026-11-03"],
    windows: [{ id: "daily-window", type: "daily", start_date: "2026-11-03", end_date: "2026-11-03", label: "日报 · 2026-11-03", missing_days: [] }],
    notice: "合成数据周期建议，不代表完整覆盖。" });
  if (path === "/api/project-context") return json({ documents: [] });
  if (path === "/api/professional-review") return json({
    suite: { cases: [{ case_id: "synthetic-review", scenario: "合成规则适用性", expected: "工程师核对规则适用范围和报告表达。" }] },
    suite_hash: "a".repeat(64), adapter_digest: "b".repeat(64), review: null, status: "pending_engineer_review",
  });
  if (path === "/api/project-standards/changes") return json({ state: null });
  if (path === "/api/monitoring-files" && request.method() === "POST") {
    const uploaded = {
      ...file,
      file_id: randomUUID(),
      project_id: activeProject,
      original_name: "快速链路监测.csv",
      created_at: new Date().toISOString(),
    };
    monitoringFiles = [uploaded, ...monitoringFiles];
    return route.fulfill({ status: 201, json: {
      file: uploaded,
      read_report: {
        ok: true,
        data_rows: 2,
        detected_metrics: [{ key: "surface_settlement", name: "地表沉降", supported: true }],
      },
    } });
  }
  if (path === "/api/monitoring-files") return json({ files: monitoringFiles });
  if (path === "/api/standards") return json({ files: [] });
  if (path === "/api/project-standards") return json({ documents: [] });
  if (path === "/api/runs" && request.method() === "GET") {
    if (historyFailure) return route.fulfill({ status: 503, json: { error: { message: "合成网络故障" } } });
    return json({ runs: records.map(record => ({
      run_id: record.run_id, revision: record.revision, created_at: record.created_at, updated_at: record.updated_at,
      execution_status: record.execution_status, error: record.error,
      report_date: record.request.report_date, project_name: record.request.project?.name ?? "未提供",
      agent_status: record.result?.agent_run?.state.run.status ?? null, decision: null, parent_run_id: null,
    })) });
  }
  if (path === "/api/runs" && request.method() === "POST") {
    if (failNextQuickRun) {
      failNextQuickRun = false;
      return route.fulfill({ status: 503, json: {
        error: { message: "合成快速运行故障" },
      } });
    }
    const record = fixture("2026-11-06T00:00:00.000Z", "当前工程名", activeProject);
    record.request = request.postDataJSON();
    records = [record, ...records];
    return json(view(record));
  }
  const record = records.find(record => path === `/api/runs/${record.run_id}`);
  if (record) return json(view(record));
  return route.fulfill({ status: 403, json: { error: { message: "无权访问合成运行" } } });
});
const nav = step => page.getByRole("navigation", { name: "工作台步骤" }).getByRole("button", { name: new RegExp(step) });
const hasText = async (locator, text) => assert.match(await locator.textContent(), text);
const resultInfo = page.getByRole("region", { name: "本次工程条件" });
const openRange = () => page.getByRole("button", { name: /^(选择范围|修改范围)$/ }).click();
const summary = page.locator(".wb-range-summary");
const checks = [];

try {
  authenticated = false;
  await page.goto(`${origin}/workbench`);
  await page.getByLabel("账号", { exact: true }).waitFor();
  assert.equal(await nav("2 ·").isDisabled(), true);
  checks.push("未登录显示登录表单并禁止后续步骤");
  authenticated = true;
  await page.goto(`${origin}/workbench`);
  await resultInfo.waitFor();
  assert.match(page.url(), new RegExp(latest.run_id));
  const reportDelivery = page.getByRole("region", { name: "报告交付与运行轨迹" });
  const reviewSamples = page.locator('[aria-label="复核样例校验"]');
  await reportDelivery.waitFor();
  const engineerReview = page.getByRole("region", { name: "工程师复核" });
  await engineerReview.waitFor();
  assert.equal(await engineerReview.evaluate(node => node.closest(".wb-result-context") !== null), true);
  assert.ok(await page.locator(".wb-result-context").evaluate(node => node.getBoundingClientRect().width) >= 340);
  assert.equal(await reviewSamples.evaluate(node => node.hasAttribute("open")), false);
  assert.equal(await page.evaluate(() => {
    const report = document.querySelector('[aria-label="报告交付与运行轨迹"]');
    const samples = document.querySelector('[aria-label="复核样例校验"]');
    return Boolean(report && samples && (report.compareDocumentPosition(samples) & Node.DOCUMENT_POSITION_FOLLOWING));
  }), true);
  await reviewSamples.locator("summary").click();
  await page.getByRole("link", { name: "输入与预期样例", exact: true }).waitFor();
  assert.equal(await reviewSamples.getByText(/signal is aborted/i).count(), 0);
  checks.push("当前报告工程师复核优先展示，项目级复核样例默认折叠且按需展开");
  await hasText(resultInfo, /15 m/);
  await hasText(resultInfo, /历史工程名/);
  assert.equal(await page.getByRole("button", { name: "运行分析", exact: true }).isVisible(), false);
  checks.push("跳过失败和空结果候选，默认恢复最新成果及冻结条件");

  const reason = page.getByRole("textbox", { name: "复核总评（必填）" });
  await reason.fill("未保存的复核总评");
  const finalRiskLevel = page.getByLabel("工程师最终等级", { exact: true });
  await finalRiskLevel.selectOption("正常");
  await page.getByLabel("评价结论", { exact: true }).selectOption("follow_up_required");
  await page.locator(".wb-evaluation-comment").fill("未保存的风险评价");
  const riskNavigator = page.locator(".wb-risk-navigator select");
  await riskNavigator.selectOption("1");
  await hasText(page.locator(".wb-risk-evaluation"), /系统原判：未知/);
  await hasText(finalRiskLevel.locator("option").first(), /保持待确定/);
  await finalRiskLevel.selectOption("危险报警");
  await page.getByLabel("评价结论", { exact: true }).selectOption("confirmed");
  await page.locator(".wb-evaluation-comment").fill("现场资料补齐后判定为危险报警");
  await riskNavigator.selectOption("0");
  await nav("2 ·").click();
  await page.getByRole("dialog").waitFor();
  await page.keyboard.press("Escape");
  await nav("4 ·").click();
  assert.equal(await reason.inputValue(), "未保存的复核总评");
  assert.equal(await page.locator(".wb-evaluation-comment").inputValue(), "未保存的风险评价");
  assert.equal(await finalRiskLevel.inputValue(), "正常");
  assert.equal(await finalRiskLevel.inputValue(), "正常");
  records = records.map(record => record.run_id === latest.run_id ? { ...record, revision: 2 } : record);
  await page.clock.fastForward(15_001);
  await page.getByRole("button", { name: "加载最新协作版本", exact: true }).waitFor();
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByRole("button", { name: "加载最新协作版本", exact: true }).click();
  assert.equal(await reason.inputValue(), "未保存的复核总评");
  checks.push("协作轮询只提示新修订；取消加载保留未保存风险评价和总评");
  page.once("dialog", dialog => dialog.dismiss());
  await page.locator(".wb-history-item").filter({ hasText: older.run_id.slice(0, 8) }).click();
  assert.match(page.url(), new RegExp(latest.run_id));
  assert.equal(await reason.inputValue(), "未保存的复核总评");
  await nav("1 ·").click();
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByLabel("选择获授权工程", { exact: true }).selectOption(otherProjectId);
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  assert.equal(writes.length, 0);
  await nav("2 ·").click();
  checks.push("步骤往返保留总评；取消历史和工程切换保留原运行");

  await openRange();
  await page.getByRole("button", { name: "周报 连续 7 天", exact: true }).click();
  await page.getByLabel("周报结束日（含当日及之前6日）", { exact: true }).fill("2027-01-03");
  await hasText(page.locator(".wb-range-preview"), /2026-12-28 至 2027-01-03/);
  await page.getByRole("button", { name: "确认范围", exact: true }).click();
  await hasText(summary, /周报/);
  await openRange();
  await page.getByRole("button", { name: "月报 完整自然月", exact: true }).click();
  await page.getByLabel("报告月份", { exact: true }).fill("2028-02");
  await hasText(page.locator(".wb-range-preview"), /2028-02-01 至 2028-02-29/);
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await hasText(summary, /周报/);
  assert.equal(await page.getByRole("button", { name: "修改范围", exact: true }).evaluate(node => node === document.activeElement), true);
  await page.getByLabel(/安全等级/).selectOption("二级");
  await page.getByLabel(/设计开挖深度/).fill("19");
  assert.equal(await page.getByLabel(/实际支护信息/).isVisible(), true);
  await hasText(page.locator(".wb-accordion summary").filter({ hasText: "判据适用条件" }), /必填/);
  checks.push("第二步未确认支护时自动展开必填项，工程名称与支护类型明确区分");
  await page.getByLabel(/实际支护信息/).selectOption("灌注桩");
  await nav("3 ·").click();
  await page.getByLabel(/选择本工程已上传的监测数据/).selectOption(fileId);
  await page.clock.runFor(300);
  await page.getByRole("option", { name: "日报 · 2026-11-03", exact: true }).waitFor({ state: "attached" });
  await nav("2 ·").click();
  await hasText(summary, /周报 · 2026-12-28 至 2027-01-03/);
  checks.push("数据推荐周期不覆盖已手动确认的报告范围");
  await nav("3 ·").click();
  const optionalTool = page.getByLabel(/选择要配置的可选资料/);
  assert.equal(await page.getByRole("region", { name: "案例、工况与巡视资料" }).count(), 0);
  await optionalTool.selectOption("context");
  const contextPanel = page.getByRole("region", { name: "案例、工况与巡视资料" });
  await contextPanel.waitFor();
  assert.equal(await contextPanel.getByText(/signal is aborted/i).count(), 0);
  await page.getByLabel("辅助资料标题", { exact: true }).fill("未上传的合成案例标题");
  await page.setViewportSize({ width: 390, height: 844 });
  const optionalLayout = await page.evaluate(() => {
    const panel = document.querySelector('[aria-label="案例、工况与巡视资料"]');
    const bounds = panel?.getBoundingClientRect();
    return {
      width: innerWidth,
      pageWidth: document.documentElement.scrollWidth,
      controlsFit: [...(panel?.querySelectorAll("input, select") ?? [])].every(control => {
        const rect = control.getBoundingClientRect();
        return Boolean(bounds && rect.left >= bounds.left && rect.right <= bounds.right);
      }),
    };
  });
  assert.equal(optionalLayout.pageWidth, optionalLayout.width);
  assert.equal(optionalLayout.controlsFit, true);
  await page.setViewportSize({ width: 1440, height: 900 });
  await optionalTool.selectOption("project-standard");
  await page.getByRole("region", { name: "项目补充规范" }).waitFor();
  assert.equal(await contextPanel.isVisible(), false);
  await optionalTool.selectOption("context");
  assert.equal(await page.getByLabel("辅助资料标题", { exact: true }).inputValue(), "未上传的合成案例标题");
  await optionalTool.selectOption("thresholds");
  await page.getByRole("heading", { name: "用户规范 JSON（数值阈值，可选）", exact: true }).waitFor();
  checks.push("三个可选资料工具由单一下拉菜单按需展开，窄屏无溢出且切换后保留未提交输入");
  await nav("4 ·").click();
  await nav("2 ·").click();
  await page.getByLabel(/实际支护信息/).selectOption("");
  await page.getByText("判据适用条件（必填） · 待确认支护信息", { exact: true }).click();
  await nav("4 ·").click();
  assert.equal(await page.getByRole("button", { name: "运行分析", exact: true }).isDisabled(), true);
  const missingSupport = page.locator("#wb-analysis-prerequisites li").filter({ hasText: "确认实际支护信息" });
  await missingSupport.getByRole("button", { name: "返回第二步补充", exact: true }).click();
  assert.equal(await page.getByLabel(/实际支护信息/).isVisible(), true);
  assert.equal(await page.getByLabel(/安全等级/).inputValue(), "二级");
  await page.getByLabel(/实际支护信息/).selectOption("灌注桩");
  await nav("4 ·").click();
  assert.equal(await page.getByRole("button", { name: "运行分析", exact: true }).isEnabled(), true);
  assert.equal(await page.locator("#wb-analysis-prerequisites").count(), 0);
  checks.push("缺少支护信息明确说明禁用原因，一键补充后启用分析且保留已有输入");
  assert.equal(await reason.inputValue(), "未保存的复核总评");
  await hasText(resultInfo, /15 m/);
  assert.equal(writes.length, 0);
  checks.push("周/月范围准确、取消不改旧范围且恢复焦点；新输入不改变旧快照");

  await page.getByRole("button", { name: "基于此报告重新分析", exact: true }).click();
  await summary.waitFor();
  await hasText(summary, /日报 · 2026-11-03/);
  await nav("4 ·").click();
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "运行分析", exact: true }).click();
  await page.getByRole("button", { name: "运行分析", exact: true }).waitFor({ state: "visible" });
  await page.waitForFunction(id => !location.search.includes(id), latest.run_id);
  assert.equal(writes.length, 1);
  assert.equal(writes[0].body.parent_run_id, latest.run_id);
  assert.deepEqual(writes[0].body.project_standard_ids, []);
  assert.equal(writes[0].body.context.excavation_depth_m, 15);
  checks.push("关联重跑发送原条件及冻结规范引用，显式确认后替换复核内容");

  await nav("2 ·").click();
  await openRange();
  await page.getByRole("button", { name: "月报 完整自然月", exact: true }).click();
  await page.getByLabel("报告月份", { exact: true }).fill("2028-02");
  await page.getByRole("button", { name: "确认范围", exact: true }).click();
  await nav("4 ·").click();
  await page.getByRole("button", { name: "运行分析", exact: true }).click();
  await page.waitForFunction(() => !document.querySelector(".wb-spin"));
  assert.equal(writes.length, 2);
  assert.equal(writes[1].body.report_date, "2028-02-29");
  assert.deepEqual(writes[1].body.report_period, { type: "monthly", start_date: "2028-02-01", end_date: "2028-02-29" });
  checks.push("弹窗确认的月报范围完整传入运行请求");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => !document.querySelector(".wb-result-info").open);
  const mobile = await page.evaluate(() => ({
    width: innerWidth, pageWidth: document.documentElement.scrollWidth,
    sidebarHeight: document.querySelector(".sidebar").getBoundingClientRect().height,
    reviewPosition: getComputedStyle(document.querySelector(".wb-result-context-sticky")).position,
  }));
  assert.equal(mobile.pageWidth, mobile.width);
  assert.ok(mobile.sidebarHeight < 160);
  assert.equal(mobile.reviewPosition, "static");
  await page.mouse.wheel(0, 1200);
  await page.waitForFunction(() => scrollY > 500);
  assert.equal(await page.locator(".sidebar").evaluate(node => node.getBoundingClientRect().top), 0);
  checks.push("手机辅助区默认折叠，无横向溢出且步骤导航吸顶");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForFunction(() => document.querySelector(".wb-result-info").open);
  await page.mouse.wheel(0, 1000);
  assert.equal(await page.locator(".sidebar").evaluate(node => node.getBoundingClientRect().top), 0);
  const reviewWorkspace = await page.locator(".wb-result-context-sticky").evaluate(node => ({
    top: node.getBoundingClientRect().top,
    height: node.getBoundingClientRect().height,
    maxHeight: getComputedStyle(node).maxHeight,
    overflowY: getComputedStyle(node).overflowY,
  }));
  assert.equal(reviewWorkspace.top, 16);
  assert.ok(reviewWorkspace.height <= 868);
  assert.equal(reviewWorkspace.overflowY, "auto");
  checks.push("桌面长报告中右侧复核工作区吸顶并独立滚动，报告与辅助信息分列");

  await page.goto(`${origin}/workbench?step=results&run=${randomUUID()}`);
  await page.getByRole("alert").filter({ hasText: "无权访问合成运行" }).waitFor();
  assert.equal(await resultInfo.isVisible(), false);
  checks.push("明确无权运行链接不回退加载其他成果");
  records = [failed];
  await page.goto(`${origin}/workbench`);
  await page.getByRole("dialog").waitFor();
  await page.keyboard.press("Escape");
  await hasText(summary, /尚未选择/);
  assert.equal(await page.getByLabel(/安全等级/).inputValue(), "");
  assert.equal(await page.getByLabel(/设计开挖深度/).inputValue(), "");
  checks.push("仅失败历史进入新任务，取消首次范围不填入演示条件");
  historyFailure = true;
  await page.goto(`${origin}/workbench?step=results`);
  await page.getByRole("alert").filter({ hasText: "合成网络故障" }).waitFor();
  historyFailure = false;
  records = [latest];
  await page.getByRole("button", { name: "重试加载", exact: true }).click();
  await resultInfo.waitFor();
  checks.push("历史网络失败明确提示，并可重试恢复");
  monitoringFiles = [];
  await page.getByRole("button", { name: "基于此报告重新分析", exact: true }).click();
  await page.getByRole("status").filter({ hasText: "原监测文件或部分汇总文件已不可用" }).waitFor();
  await hasText(summary, /日报 · 2026-11-03/);
  await nav("3 ·").click();
  assert.equal(await page.getByLabel(/选择本工程已上传的监测数据/).inputValue(), "");
  await nav("4 ·").click();
  assert.equal(await page.getByRole("button", { name: "运行分析", exact: true }).isVisible(), false);
  assert.equal(writes.length, 2);
  checks.push("历史文件失效仍恢复原条件与关联关系，重新选择文件后才能分析");
  monitoringFiles = [file];
  role = "viewer";
  await page.goto(`${origin}/workbench`);
  await resultInfo.waitFor();
  assert.equal(await page.getByRole("button", { name: "新建报告", exact: true }).count(), 0);
  assert.equal(await page.getByRole("button", { name: "基于此报告重新分析", exact: true }).count(), 0);
  assert.equal(await reason.count(), 0);
  role = "admin";
  engineeringType = "tunnel";
  supportedReports = ["daily"];
  records = [];
  await page.goto(`${origin}/workbench`);
  await page.getByRole("dialog").waitFor();
  await page.getByLabel(/工程类别/).waitFor({ state: "attached" });
  assert.equal(await page.getByRole("button", { name: "月报 完整自然月", exact: true }).isDisabled(), true);
  await page.keyboard.press("Escape");
  await page.getByLabel(/工程类别/).selectOption("rail");
  await page.getByLabel(/施工工法/).selectOption("mining");
  await page.getByLabel(/工程阶段/).selectOption("construction");
  await page.getByLabel(/特殊地质条件/).selectOption("none");
  assert.equal(await page.getByText(/判据适用条件（必填）/).count(), 0);
  await nav("3 ·").click();
  assert.equal(await page.getByLabel(/选择要配置的可选资料/).getByRole("option", { name: "用户规范 JSON（数值阈值，可选）" }).count(), 0);
  await page.getByLabel(/选择本工程已上传的监测数据/).selectOption(fileId);
  await page.clock.runFor(300);
  await page.getByRole("option", { name: "日报 · 2026-11-03", exact: true }).waitFor({ state: "attached" });
  await page.getByRole("region", { name: "监测参数确认" }).waitFor();
  await page.getByLabel(/数据含义/).selectOption("cumulative_settlement");
  await page.getByLabel("控制值依据", { exact: true }).fill("合成批准方案");
  await page.getByLabel("累计变形控制值（mm）", { exact: true }).fill("30");
  await page.getByLabel("已确认该测项的输入含义与控制要求", { exact: true }).check();
  await page.getByRole("button", { name: "确认并保存监测参数", exact: true }).click();
  await page.getByRole("status").filter({ hasText: "监测参数已确认保存" }).waitFor();
  assert.equal(writes.at(-1).path, "/api/projects/current/engineering");
  assert.equal(writes.at(-1).body.expected_revision, 0);
  await nav("4 ·").click();
  assert.equal(await page.getByRole("button", { name: "运行分析", exact: true }).isEnabled(), true);
  assert.equal(await page.locator("#wb-analysis-prerequisites").count(), 0);
  checks.push("隧道上传后在第三步原地填写并保存监测参数，隐藏基坑支护与JSON阈值");
  await page.getByRole("button", { name: "运行分析", exact: true }).click();
  await resultInfo.waitFor();
  assert.equal(writes.at(-1).body.context.construction_method, "mining");
  assert.equal(writes.at(-1).body.context.metric_controls.surface_settlement.confirmed, true);
  assert.equal(writes.at(-1).body.report_date, "2026-11-03");
  await hasText(resultInfo, /矿山法／钻爆法/);
  assert.doesNotMatch(await resultInfo.textContent(), /安全等级|设计开挖深度/);
  checks.push("推荐日期、隧道测项控制值与保存配置完整传入请求，历史快照按工程字段展示");
  await page.getByRole("button", { name: "新建报告", exact: true }).click();
  await page.getByRole("dialog").waitFor();
  await page.keyboard.press("Escape");
  assert.equal(await page.getByLabel(/施工工法/).inputValue(), "mining");
  await nav("3 ·").click();
  await page.getByLabel(/选择本工程已上传的监测数据/).selectOption(fileId);
  await page.clock.runFor(300);
  assert.equal(await page.getByLabel("控制值依据", { exact: true }).inputValue(), "合成批准方案");
  checks.push("新建报告复用管理员已确认工程参数与控制值");

  canCreateProject = true;
  role = "admin";
  activeProject = projectId;
  engineeringType = "foundation_pit";
  supportedReports = null;
  sceneParameters = null;
  records = [];
  const writesBeforeProject = writes.length;
  await page.goto(`${origin}/workbench?step=start`);
  await page.getByText("保留原有快速创建", { exact: true }).waitFor();
  await page.getByLabel("选择获授权工程", { exact: true }).selectOption("__new_project__");
  await page.getByRole("dialog", { name: "基本信息" }).waitFor();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  assert.equal(writes.filter(write => write.path === "/api/projects").length, 0);
  await page.getByRole("button", { name: "新建工程", exact: true }).click();
  const projectDialog = page.getByRole("dialog");
  await projectDialog.waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  const projectDialogMobile = await page.evaluate(() => ({
    width: innerWidth,
    pageWidth: document.documentElement.scrollWidth,
    dialogWidth: document.querySelector("dialog")?.getBoundingClientRect().width,
    dialogHeight: document.querySelector("dialog")?.getBoundingClientRect().height,
  }));
  assert.equal(projectDialogMobile.pageWidth, projectDialogMobile.width);
  assert.ok(projectDialogMobile.dialogWidth <= 390);
  assert.ok(projectDialogMobile.dialogHeight <= 844);
  await page.setViewportSize({ width: 1440, height: 900 });
  await projectDialog.getByLabel(/工程类型/).selectOption("foundation_pit");
  await projectDialog.getByLabel(/工程名称/).fill("合成引导工程");
  await page.getByRole("button", { name: "下一步", exact: true }).click();
  await projectDialog.getByLabel(/安全等级/).selectOption("二级");
  await projectDialog.getByLabel(/支护形式/).selectOption("灌注桩");
  await page.getByRole("button", { name: "下一步", exact: true }).click();
  await page.getByRole("button", { name: "周报 连续 7 天", exact: true }).click();
  await page.getByLabel("周报结束日（含当日及之前6日）", { exact: true }).fill("2027-01-03");
  await hasText(page.locator(".wb-range-preview"), /2026-12-28 至 2027-01-03/);
  await page.getByRole("button", { name: "创建后进入详细流程", exact: true }).click();
  await page.getByRole("heading", { name: "数据与规范", exact: true }).waitFor();
  assert.match(page.url(), /step=data/);
  const projectWrites = writes.slice(writesBeforeProject);
  assert.deepEqual(projectWrites.filter(write => write.path === "/api/projects").at(-1).body, {
    name: "合成引导工程",
    engineering_type: "foundation_pit",
    parameters: { safety_level: "二级", support_type: "灌注桩", excavation_depth_m: null },
  });
  assert.equal(projectWrites.filter(write => write.path === "/api/projects/select").length, 1);
  await nav("2 ·").click();
  await hasText(summary, /周报 · 2026-12-28 至 2027-01-03/);
  assert.equal(await page.getByLabel(/安全等级/).inputValue(), "二级");
  assert.equal(await page.getByLabel(/实际支护信息/).inputValue(), "灌注桩");
  checks.push("新建工程向导保留创建后进入详细流程，原子保存条件并直达数据页");

  const quickWritesStart = writes.length;
  await nav("1 ·").click();
  await page.getByRole("button", { name: "新建工程", exact: true }).click();
  const quickDialog = page.getByRole("dialog");
  await quickDialog.getByLabel(/工程类型/).selectOption("tunnel");
  await quickDialog.getByLabel(/工程名称/).fill("合成隧道快速工程");
  await quickDialog.getByRole("button", { name: "下一步", exact: true }).click();
  await quickDialog.getByLabel(/工程类别/).selectOption("rail");
  await quickDialog.getByLabel(/施工工法/).selectOption("mining");
  await quickDialog.getByLabel(/工程阶段/).selectOption("construction");
  await quickDialog.getByLabel(/特殊地质条件/).selectOption("none");
  await quickDialog.getByRole("button", { name: "下一步", exact: true }).click();
  await quickDialog.getByLabel("报告日期", { exact: true }).fill("2026-11-03");
  await quickDialog.getByRole("button", { name: "下一步", exact: true }).click();
  await quickDialog.getByLabel("快速链路监测数据文件", { exact: true }).setInputFiles({
    name: "SIMULATED_隧道监测.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      "point_id,timestamp,metric_key,value,unit,data_origin\n" +
      "SIM-01,2026-11-03 08:00:00,surface_settlement,1,mm,simulated\n" +
      "SIM-01,2026-11-03 11:00:00,surface_settlement,2,mm,simulated\n",
    ),
  });
  await quickDialog.getByRole("button", { name: "创建工程并识别文件", exact: true }).click();
  await quickDialog.getByRole("heading", { name: "确认运行", exact: true }).waitFor();
  await quickDialog.getByText(/无法可靠判定的风险将标为“未知”并进入人工复核/).waitFor();
  await hasText(quickDialog.locator(".wb-project-summary"), /运行方式仅确定性计算/);
  assert.equal(
    await quickDialog.getByRole("button", { name: "运行分析并查看结果", exact: true }).isEnabled(),
    true,
  );
  failNextQuickRun = true;
  await quickDialog.getByRole("button", { name: "运行分析并查看结果", exact: true }).click();
  await quickDialog.getByRole("alert").filter({ hasText: "合成快速运行故障" }).waitFor();
  await quickDialog.getByRole("button", { name: "运行分析并查看结果", exact: true }).click();
  await quickDialog.waitFor({ state: "detached" });
  await resultInfo.waitFor();
  assert.match(page.url(), /step=results&run=/);
  const quickWrites = writes.slice(quickWritesStart);
  assert.equal(quickWrites.filter(write => write.path === "/api/projects").length, 1);
  assert.equal(quickWrites.filter(write => write.path === "/api/monitoring-files").length, 1);
  const quickConfiguration = quickWrites.find(write =>
    write.path === "/api/projects/current/engineering"
  );
  assert.equal(quickWrites.filter(write =>
    write.path === "/api/projects/current/engineering"
  ).length, 1);
  assert.equal(quickWrites.filter(write => write.path === "/api/runs").length, 2);
  assert.equal(quickConfiguration.body.parameters.metric_controls, undefined);
  const quickRun = quickWrites.find(write => write.path === "/api/runs");
  assert.equal(quickRun.body.context.construction_method, "mining");
  assert.equal(quickRun.body.context.metric_controls, undefined);
  assert.equal(quickRun.body.options.generate_report, false);
  await hasText(resultInfo, /合成隧道快速工程/);
  checks.push("新建隧道快速链路允许控制值留空，按未知待核提示运行；失败重试不重复保存配置并直达第四步");

  const legacyAudit = structuredClone(latest);
  legacyAudit.result.agent_run.state.report_mode = "ai";
  legacyAudit.result.agent_run.downloads = [{ kind: "workbook", file_name: "合成.xlsx", url: "/api/report-artifacts/test", sha256: "b".repeat(64), size_bytes: 1 }];
  records = [legacyAudit];
  await page.goto(`${origin}/workbench`);
  await resultInfo.waitFor();
  await page.getByText(/完整审查尚未通过/).waitFor();
  assert.equal(await page.getByRole("button", { name: /下载 Excel/ }).count(), 0);
  assert.equal(await reason.count(), 0);
  checks.push("旧AI报告仅文件校验通过时仍阻挡下载与人工接受，保留未完成审查提示");
  assert.deepEqual(errors, []);
  checks.push("只读成员可读成果，无新建或复核入口；无页面运行时错误");
  console.log(JSON.stringify({ status: "passed", checks, interceptedWrites: writes.length }, null, 2));
} finally {
  await browser.close();
}
