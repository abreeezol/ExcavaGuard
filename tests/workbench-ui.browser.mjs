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

function fixture(createdAt, name = "历史工程名") {
  const runId = randomUUID();
  const risk = { point_id: "P-01", metric_key: "wall_top_horizontal_displacement",
    metric_name: "围护墙顶部水平位移", timestamp: "2026-11-03T08:00:00+08:00", risk_level: "报警" };
  const payload = {
    items: [risk], alerts: [risk], review_queue: [],
    summary: { total: 1, overall_risk_level: "报警", by_risk_level: { 报警: 1 } },
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
    owner_id: actor.id, created_by: actor, project_id: projectId,
    created_at: createdAt, updated_at: createdAt, execution_status: "completed",
    lease_until: null, error: null, review: null,
    request: { project_id: projectId, monitoring_file_id: fileId, report_date: "2026-11-03",
      project: { name }, context: { safety_level: "一级", support_type: "地下连续墙", excavation_depth_m: 15 },
      project_standard_ids: [], options: { report_mode: "template", generate_report: true } },
    result: { run_id: runId, project_id: projectId, created_at: createdAt, monitoring_file_id: fileId,
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
let historyFailure = false;
let monitoringFiles = [file];
let engineeringType = "foundation_pit";
let sceneParameters = null;
let supportedReports = null;
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
  if (request.method() !== "GET" && path !== "/api/report-windows") writes.push({ path, body: request.postDataJSON() });
  if (path === "/api/session") return json({
    mode: "accounts", authenticated, user: authenticated ? actor : null,
    project_id: authenticated ? activeProject : null, can_create_project: false,
    projects: authenticated ? [
      { id: projectId, name: "当前工程名", role }, { id: otherProjectId, name: "第二工程", role },
    ] : [],
  });
  if (path === "/api/projects/select") { activeProject = request.postDataJSON().project_id; return json({ ok: true }); }
  if (path === "/api/projects") return json({ engineering_types: [{ id: "foundation_pit", name: "基坑工程" }, { id: "tunnel", name: "隧道工程" }] });
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
    windows: [{ id: "daily-window", type: "daily", start_date: "2026-11-03", end_date: "2026-11-03", label: "日报 · 2026-11-03", missing_days: [] }],
    notice: "合成数据周期建议，不代表完整覆盖。" });
  if (path === "/api/project-context") return json({ documents: [] });
  if (path === "/api/professional-review") return json({ suite: { cases: [] }, status: "pending_engineer_review" });
  if (path === "/api/project-standards/changes") return json({ state: null });
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
    const record = fixture("2026-11-06T00:00:00.000Z", "当前工程名");
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
  await hasText(resultInfo, /15 m/);
  await hasText(resultInfo, /历史工程名/);
  assert.equal(await page.getByRole("button", { name: "运行分析", exact: true }).isVisible(), false);
  checks.push("跳过失败和空结果候选，默认恢复最新成果及冻结条件");

  const reason = page.getByRole("textbox", { name: "复核总评（必填）" });
  await reason.fill("未保存的复核总评");
  await page.locator(".wb-risk-evaluation select").selectOption("follow_up_required");
  await page.locator(".wb-evaluation-comment").fill("未保存的风险评价");
  await nav("2 ·").click();
  await page.getByRole("dialog").waitFor();
  await page.keyboard.press("Escape");
  await nav("4 ·").click();
  assert.equal(await reason.inputValue(), "未保存的复核总评");
  assert.equal(await page.locator(".wb-evaluation-comment").inputValue(), "未保存的风险评价");
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
  assert.equal(await page.getByText("案例、工况与巡视资料（可选）", { exact: true }).isVisible(), true);
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
  }));
  assert.equal(mobile.pageWidth, mobile.width);
  assert.ok(mobile.sidebarHeight < 160);
  await page.mouse.wheel(0, 1200);
  await page.waitForFunction(() => scrollY > 500);
  assert.equal(await page.locator(".sidebar").evaluate(node => node.getBoundingClientRect().top), 0);
  checks.push("手机辅助区默认折叠，无横向溢出且步骤导航吸顶");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForFunction(() => document.querySelector(".wb-result-info").open);
  await page.mouse.wheel(0, 1000);
  assert.equal(await page.locator(".sidebar").evaluate(node => node.getBoundingClientRect().top), 0);
  checks.push("桌面长报告吸顶，结果与历史条件分列");

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
  assert.equal(await page.getByText("用户规范 JSON（数值阈值，可选）", { exact: true }).count(), 0);
  await page.getByLabel(/选择本工程已上传的监测数据/).selectOption(fileId);
  await page.clock.runFor(300);
  await page.getByRole("option", { name: "日报 · 2026-11-03", exact: true }).waitFor({ state: "attached" });
  await nav("4 ·").click();
  assert.equal(await page.getByRole("button", { name: "运行分析", exact: true }).isEnabled(), true);
  assert.equal(await page.locator("#wb-analysis-prerequisites").count(), 0);
  checks.push("隧道按自身必填参数启用分析，隐藏基坑支护与JSON阈值，限制不支持的周期");
  await nav("2 ·").click();
  await hasText(summary, /日报 · 2026-11-03/);
  await page.getByRole("region", { name: "监测参数确认" }).waitFor();
  await page.getByLabel(/数据含义/).selectOption("cumulative_settlement");
  await page.getByLabel("控制值依据", { exact: true }).fill("合成批准方案");
  await page.getByLabel("累计变形控制值（mm）", { exact: true }).fill("30");
  await page.getByLabel("已确认该测项的输入含义与控制要求", { exact: true }).check();
  await page.getByRole("button", { name: "确认并保存工程配置", exact: true }).click();
  await page.getByRole("status").filter({ hasText: "工程配置已确认保存" }).waitFor();
  assert.equal(writes.at(-1).path, "/api/projects/current/engineering");
  assert.equal(writes.at(-1).body.expected_revision, 0);
  await nav("4 ·").click();
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
  assert.equal(await page.getByLabel("控制值依据", { exact: true }).inputValue(), "合成批准方案");
  checks.push("新建报告复用管理员已确认工程参数与控制值");

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
