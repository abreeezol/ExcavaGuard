"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Plus } from "lucide-react";
import type { AccessStatus } from "@/contracts/access";
import { ProjectWorkbench } from "./workbench-client";
import { WorkspaceSidebar, WORKBENCH_STEPS, type WorkbenchStep } from "@/components/workspace-sidebar";
import {
  NewProjectDialog,
  type GuidedProjectInput,
  type GuidedProjectPreparation,
  type GuidedRunInput,
} from "./new-project-dialog";
import { resolveReportRange, type ReportRange } from "./report-range";
import { engineeringSetupsSchema, type EngineeringSetup } from "@/contracts/project-setup";
import { uploadMonitoringFileResponseSchema } from "@/contracts/monitoring-files";
import { persistedRunSchema } from "@/contracts/runs";

const ROLE_LABELS = { admin: "项目管理员", reviewer: "复核工程师", engineer: "工程师", viewer: "只读成员" };
async function responseBody(response: Response) {
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message || "操作失败。");
  return body;
}

export function WorkbenchClient() {
  const [session, setSession] = useState<AccessStatus | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [engineeringTypes, setEngineeringTypes] = useState<Array<{ id: string; name: string }>>([]);
  const [engineeringSetups, setEngineeringSetups] = useState<EngineeringSetup[]>([]);
  const [engineeringType, setEngineeringType] = useState("foundation_pit");
  const [newProject, setNewProject] = useState("");
  const [newProjectDialogOpen, setNewProjectDialogOpen] = useState(false);
  const [projectOnboarding, setProjectOnboarding] = useState<{
    projectId: string;
    range: ReportRange;
  } | null>(null);
  const [guidedProvision, setGuidedProvision] = useState<{
    projectId: string;
    engineeringRevision?: number;
    configuredParameters?: string;
  } | null>(null);
  const [workbenchEpoch, setWorkbenchEpoch] = useState(0);
  const [pending, setPending] = useState(false);
  const [projectBusy, setProjectBusy] = useState(false);
  const [error, setError] = useState("");
  const [step, setStep] = useState<WorkbenchStep>("start");
  const [initialRunId, setInitialRunId] = useState<string | null>(null);
  const dirty = useRef(false);
  const navigationTouched = useRef(false);
  const setDirty = useCallback((value: boolean) => { dirty.current = value; }, []);
  const consumeProjectOnboarding = useCallback(() => setProjectOnboarding(null), []);
  const changeStep = useCallback((next: WorkbenchStep, runId?: string | null) => {
    navigationTouched.current = true;
    setStep(next);
    const url = new URL(window.location.href);
    url.searchParams.set("step", next);
    if (runId) url.searchParams.set("run", runId);
    else if (runId === null) url.searchParams.delete("run");
    window.history.replaceState(null, "", url);
    window.scrollTo({ top: 0, behavior: "instant" });
  }, []);
  const defaultStep = useCallback((next: WorkbenchStep, runId?: string) => {
    if (!navigationTouched.current) changeStep(next, runId);
  }, [changeStep]);
  useEffect(() => {
    let cancelled = false;
    const url = new URL(window.location.href);
    const requestedStep = WORKBENCH_STEPS.find(item => item.id === url.searchParams.get("step"))?.id;
    void fetch("/api/session").then(responseBody).then(status => {
      if (cancelled) return;
      if (requestedStep) {
        setStep(requestedStep);
        navigationTouched.current = requestedStep !== "results";
      }
      setInitialRunId(url.searchParams.get("run"));
      setSession(status);
    })
      .catch(caught => { if (!cancelled) setError(caught.message); });
    return () => { cancelled = true; };
  }, []);
  async function perform(work: () => Promise<void>) {
    if (pending || projectBusy) return;
    if (dirty.current && !window.confirm("当前报告有未保存的复核内容，更新工程会话可能清空这些内容。确认继续？")) return;
    setPending(true); setError("");
    try { await work(); setSession(await responseBody(await fetch("/api/session"))); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "操作失败。"); }
    finally { setPending(false); setProjectBusy(false); }
  }
  async function selectProject(id: string, onboardingRange: ReportRange | null = null) {
    await responseBody(await fetch("/api/projects/select", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: id }) }));
    dirty.current = false;
    navigationTouched.current = false;
    setInitialRunId(null);
    setProjectOnboarding(onboardingRange ? { projectId: id, range: onboardingRange } : null);
    const url = new URL(window.location.href);
    url.searchParams.delete("run");
    url.searchParams.delete("step");
    window.history.replaceState(null, "", url);
  }
  useEffect(() => {
    if (!session?.authenticated) return;
    let cancelled = false;
    void fetch("/api/projects").then(responseBody).then(body => {
      if (cancelled) return;
      setEngineeringTypes(body.engineering_types ?? []);
      setEngineeringSetups(engineeringSetupsSchema.parse(body.engineering_setups));
    }).catch(caught => { if (!cancelled) setError(caught.message); });
    return () => { cancelled = true; };
  }, [session?.authenticated]);
  function openNewProjectDialog() {
    setError("");
    setGuidedProvision(null);
    setNewProjectDialogOpen(true);
  }
  function createGuidedProject(input: GuidedProjectInput) {
    void perform(async () => {
      const body = await responseBody(await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: input.name,
          engineering_type: input.engineering_type,
          parameters: input.parameters,
        }),
      }));
      await selectProject(body.project.id, input.range);
      setGuidedProvision(null);
      setNewProjectDialogOpen(false);
      changeStep("data");
    });
  }

  function projectHeaders(projectId: string, init?: HeadersInit) {
    const headers = new Headers(init);
    headers.set("X-Excavaguard-Project", projectId);
    return headers;
  }

  async function prepareGuidedProject(
    input: GuidedProjectInput,
    file: File,
  ): Promise<GuidedProjectPreparation> {
    if (pending) throw new Error("快速创建正在处理中，请稍候。");
    setPending(true);
    setError("");
    let provision = guidedProvision;
    try {
      if (!provision) {
        const body = await responseBody(await fetch("/api/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: input.name,
            engineering_type: input.engineering_type,
            parameters: input.parameters,
          }),
        }));
        provision = { projectId: body.project.id };
        setGuidedProvision(provision);
        await selectProject(provision.projectId, input.range);
      }

      const form = new FormData();
      form.set("file", file);
      const uploaded = uploadMonitoringFileResponseSchema.parse(
        await responseBody(await fetch("/api/monitoring-files", {
          method: "POST",
          headers: projectHeaders(provision.projectId),
          body: form,
        })),
      );
      const [scene, windows] = await Promise.all([
        responseBody(await fetch("/api/projects/current/engineering", {
          headers: projectHeaders(provision.projectId),
          cache: "no-store",
        })),
        responseBody(await fetch("/api/report-windows", {
          method: "POST",
          headers: projectHeaders(provision.projectId, { "Content-Type": "application/json" }),
          body: JSON.stringify({ file_ids: [uploaded.file.file_id] }),
        })),
      ]);
      setSession(await responseBody(await fetch("/api/session")));
      return {
        project_id: provision.projectId,
        file: uploaded.file,
        read_report: uploaded.read_report,
        detected_metrics: windows.detected_metrics ?? [],
        monitoring_definitions: scene.monitoring_metrics ?? [],
        available_dates: windows.available_dates ?? [],
        adapter_version: scene.adapter.version,
        engineering_revision: scene.revision,
      };
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "快速链路准备失败。";
      setError(message);
      if (provision) {
        try { setSession(await responseBody(await fetch("/api/session"))); } catch { /* 保留主错误。 */ }
      }
      throw new Error(message);
    } finally {
      setPending(false);
      setProjectBusy(false);
    }
  }

  async function runGuidedProject(input: GuidedRunInput) {
    if (pending) throw new Error("快速运行正在处理中，请稍候。");
    setPending(true);
    setError("");
    try {
      const parametersKey = JSON.stringify(input.parameters);
      let configuredParameters = input.parameters;
      if (guidedProvision?.configuredParameters !== parametersKey) {
        const configured = await responseBody(await fetch("/api/projects/current/engineering", {
          method: "PUT",
          headers: projectHeaders(input.preparation.project_id, { "Content-Type": "application/json" }),
          body: JSON.stringify({
            expected_revision: guidedProvision?.engineeringRevision ??
              input.preparation.engineering_revision,
            adapter_version: input.preparation.adapter_version,
            parameters: input.parameters,
          }),
        }));
        configuredParameters = configured.engineering.parameters;
        setGuidedProvision({
          projectId: input.preparation.project_id,
          engineeringRevision: configured.engineering.revision,
          configuredParameters: parametersKey,
        });
      }
      const resolvedRange = resolveReportRange(input.project.range);
      const run = await responseBody(await fetch("/api/runs", {
        method: "POST",
        headers: projectHeaders(input.preparation.project_id, { "Content-Type": "application/json" }),
        body: JSON.stringify({
          project_id: input.preparation.project_id,
          monitoring_file_id: input.preparation.file.file_id,
          report_date: resolvedRange.report_date,
          report_period: resolvedRange.report_period,
          context: configuredParameters,
          project: { name: input.project.name },
          options: {
            generate_report: input.generate_report,
            report_mode: input.report_mode,
          },
        }),
      }));
      const record = persistedRunSchema.parse(run.record);
      setInitialRunId(record.run_id);
      setProjectOnboarding(null);
      setGuidedProvision(null);
      setNewProjectDialogOpen(false);
      setWorkbenchEpoch(value => value + 1);
      changeStep("results", record.run_id);
      setSession(await responseBody(await fetch("/api/session")));
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "快速运行失败。";
      setError(message);
      throw new Error(message);
    } finally {
      setPending(false);
      setProjectBusy(false);
    }
  }
  const selected = session?.projects?.find(p => p.id === session.project_id);
  const ready = Boolean(session?.authenticated && selected);
  const activeStep = ready ? step : "start";
  const stepInfo = WORKBENCH_STEPS.find(item => item.id === activeStep)!;
  return <div className="app-shell">
    <a className="skip-link" href="#workbench">跳到主要内容</a>
    <WorkspaceSidebar step={activeStep} ready={ready} onStepChange={next => changeStep(next)} />
    <main className="workspace" id="workbench">
      <header className="topbar">
        <span>工作空间 <span className="breadcrumb-divider">/</span> {stepInfo.label}</span>
        <span className="status-pill"><span className="status-dot" />{selected?.name ?? "工程监测日报助手"}</span>
      </header>
      <div className="workspace-content">
        <section className="intro">
          <div><p className="eyebrow">EXCAVAGUARD · 工程监测</p>
            <h1>{stepInfo.label}</h1>
            <p>{activeStep === "results" ? "接续已有成果，核对工程条件与规范依据，完成工程师复核。" : stepInfo.description}</p>
          </div>
          {ready && activeStep !== "start" && <button className="wb-btn" disabled={pending || projectBusy}
            onClick={() => changeStep("start")}>工程与账号</button>}
        </section>
    <section className="wb-card wb-session-card" hidden={activeStep !== "start"} aria-label="登录与项目选择">
      <div className="wb-card-head"><h2>{session?.authenticated ? "当前工程" : "登录工作台"}</h2></div>
      {error && <div role="alert" className="wb-alert wb-alert-error">{error}</div>}
      {!session && !error && <p>正在加载访问状态…</p>}
      {session && !session.authenticated && <form onSubmit={event => {
        event.preventDefault(); void perform(async () => {
          await responseBody(await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password, ...(session.mode === "accounts" ? { username } : {}) }) }));
          setPassword("");
        });
      }}>
        {session.mode === "accounts" && <label className="wb-field">账号<input autoComplete="username" required value={username} onChange={event => setUsername(event.target.value)} /></label>}
        <label className="wb-field">密码<input type="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} /></label>
        <button className="wb-btn" disabled={pending}>登录</button>
      </form>}
      {session?.authenticated && <>
        <p className="wb-hint">已登录：{session.user?.name}。切换工程会清空当前输入和结果，并加载所选工程的数据、规范和历史报告。</p>
        <label className="wb-field">选择获授权工程
          <select aria-label="选择获授权工程" value={session.project_id ?? ""} disabled={pending || projectBusy} onChange={event => {
            const id = event.target.value;
            if (id === "__new_project__") openNewProjectDialog();
            else if (id) void perform(() => selectProject(id));
          }}>
            <option value="" disabled>请选择工程</option>
            {session.projects?.map(project => <option key={project.id} value={project.id}>{project.name} · {ROLE_LABELS[project.role]}</option>)}
            {session.can_create_project && engineeringSetups.length > 0 && <option value="__new_project__">＋ 新建工程…</option>}
          </select>
        </label>
        {selected && <p className="wb-hint">{selected.name} · {ROLE_LABELS[selected.role]} · 工程ID：{selected.id}</p>}
        {selected && <div className="wb-actions">
          <button className="wb-btn wb-btn-primary" disabled={pending || projectBusy} onClick={() => changeStep("results")}>进入工程工作台</button>
          <button className="wb-btn" disabled={pending || projectBusy} onClick={() => changeStep("conditions")}>填写新报告条件</button>
        </div>}
        {!session.projects?.length && <p className="wb-hint">暂无获授权工程，请联系管理员分配成员权限。</p>}
        {!session.project_id && <p className="wb-hint">选择获授权工程后才可查看、上传或生成报告。</p>}
        <div className="wb-actions">
          <button className="wb-btn wb-btn-sm" disabled={pending || projectBusy} onClick={() => void perform(async () => {})}>刷新授权</button>
          {session.can_create_project && <button
            className="wb-btn wb-btn-sm"
            disabled={pending || projectBusy || engineeringSetups.length === 0}
            onClick={openNewProjectDialog}
          >
            <Plus size={15} aria-hidden="true" />
            新建工程
          </button>}
          {session.mode !== "local" && <button className="wb-btn wb-btn-sm" disabled={pending || projectBusy} onClick={() => void perform(async () => {
            await responseBody(await fetch("/api/session", { method: "DELETE" }));
          })}>退出登录</button>}
        </div>
        {session.can_create_project && <details className="wb-accordion wb-project-create-legacy">
          <summary>保留原有快速创建</summary>
          <form className="wb-project-create" onSubmit={event => {
            event.preventDefault(); void perform(async () => {
              const body = await responseBody(await fetch("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: newProject, engineering_type: engineeringType }) }));
              await selectProject(body.project.id); setNewProject("");
            });
          }}>
            <label className="wb-field">工程类型<select value={engineeringType} onChange={event => setEngineeringType(event.target.value)}>{engineeringTypes.map(type => <option key={type.id} value={type.id}>{type.name}</option>)}</select></label>
            <label className="wb-field">新建工程<input required maxLength={100} value={newProject} disabled={pending || projectBusy} onChange={event => setNewProject(event.target.value)} placeholder="例如：杭州一期基坑工程" /></label>
            <button className="wb-btn wb-btn-sm" disabled={pending || projectBusy || !newProject.trim()}>创建并切换</button>
          </form>
        </details>}
      </>}
      {pending && <p role="status">正在更新工程会话…</p>}
    </section>
    {session?.authenticated && session.project_id && selected && <ProjectWorkbench
      key={`${session.user?.id}:${session.project_id}:${selected?.role}:${workbenchEpoch}`}
      session={{ ...session, project_id: session.project_id }} onBusyChange={setProjectBusy}
      step={activeStep} onStepChange={changeStep} onDefaultStep={defaultStep}
      initialRunId={initialRunId}
      initialReportRange={projectOnboarding?.projectId === session.project_id ? projectOnboarding.range : null}
      onInitialReportRangeConsumed={consumeProjectOnboarding}
      onDirtyChange={setDirty} sessionPending={pending} />}
    {newProjectDialogOpen && <NewProjectDialog
      setups={engineeringSetups}
      busy={pending || projectBusy}
      error={error}
      onClose={() => {
        if (!pending && !projectBusy) {
          setNewProjectDialogOpen(false);
          if (guidedProvision) changeStep("data");
        }
      }}
      onCreateDetailed={createGuidedProject}
      onPrepare={prepareGuidedProject}
      onRun={runGuidedProject}
    />}
        <footer className="workspace-footer"><span>规则主判 · 证据可溯 · 工程师复核与签发</span><span>ExcavaGuard · 工程监测日报助手</span></footer>
      </div>
    </main>
  </div>;
}
