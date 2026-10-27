"use client";
import { useEffect, useState } from "react";
import type { AccessStatus } from "@/contracts/access";
import { ProjectWorkbench } from "./workbench-client";

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
  const [newProject, setNewProject] = useState("");
  const [pending, setPending] = useState(false);
  const [projectBusy, setProjectBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    void fetch("/api/session").then(responseBody).then(status => { if (!cancelled) setSession(status); })
      .catch(caught => { if (!cancelled) setError(caught.message); });
    return () => { cancelled = true; };
  }, []);
  async function perform(work: () => Promise<void>) {
    if (pending || projectBusy) return;
    setPending(true); setError("");
    try { await work(); setSession(await responseBody(await fetch("/api/session"))); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "操作失败。"); }
    finally { setPending(false); setProjectBusy(false); }
  }
  async function selectProject(id: string) {
    await responseBody(await fetch("/api/projects/select", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: id }) }));
  }
  const selected = session?.projects?.find(p => p.id === session.project_id);
  return <>
    <section className="wb-card" aria-label="登录与项目选择">
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
            const id = event.target.value; if (id) void perform(() => selectProject(id));
          }}>
            <option value="" disabled>请选择工程</option>
            {session.projects?.map(project => <option key={project.id} value={project.id}>{project.name} · {ROLE_LABELS[project.role]}</option>)}
          </select>
        </label>
        {selected && <p className="wb-hint">{selected.name} · {ROLE_LABELS[selected.role]} · 工程ID：{selected.id}</p>}
        {!session.projects?.length && <p className="wb-hint">暂无获授权工程，请联系管理员分配成员权限。</p>}
        {!session.project_id && <p className="wb-hint">选择获授权工程后才可查看、上传或生成报告。</p>}
        <div className="wb-actions">
          <button className="wb-btn wb-btn-sm" disabled={pending || projectBusy} onClick={() => void perform(async () => {})}>刷新授权</button>
          {session.mode !== "local" && <button className="wb-btn wb-btn-sm" disabled={pending || projectBusy} onClick={() => void perform(async () => {
            await responseBody(await fetch("/api/session", { method: "DELETE" }));
          })}>退出登录</button>}
        </div>
        {session.can_create_project && <form onSubmit={event => {
          event.preventDefault(); void perform(async () => {
            const body = await responseBody(await fetch("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: newProject }) }));
            await selectProject(body.project.id); setNewProject("");
          });
        }}>
          <label className="wb-field">新建工程<input required maxLength={100} value={newProject} disabled={pending || projectBusy} onChange={event => setNewProject(event.target.value)} placeholder="例如：杭州一期基坑工程" /></label>
          <button className="wb-btn wb-btn-sm" disabled={pending || projectBusy || !newProject.trim()}>创建并切换</button>
        </form>}
      </>}
      {pending && <p role="status">正在更新工程会话…</p>}
    </section>
    {session?.authenticated && session.project_id && !pending && <ProjectWorkbench
      key={`${session.user?.id}:${session.project_id}:${selected?.role}`}
      session={{ ...session, project_id: session.project_id }} onBusyChange={setProjectBusy} />}
  </>;
}
