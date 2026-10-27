import "server-only";
import { createHmac, timingSafeEqual } from "node:crypto";
import { z } from "zod";
import { DEFAULT_PROJECT_ID, type AccessStatus, type LocalAccess, type ProjectRole } from "@/contracts/access";
import { readAccessDirectory } from "@/server/auth/directory";
import { verifyPassword } from "@/server/auth/password";
import { AppError } from "@/server/api/errors";

const COOKIE_NAME = "excavaguard_session";
const SESSION_SECONDS = 8 * 60 * 60;
const sessionSchema = z.strictObject({ uid: z.string().min(1).max(100), project_id: z.uuid().nullable(), expires: z.number().int().positive() });
type Session = z.infer<typeof sessionSchema>;
function signature(value: string, secret: string) { return createHmac("sha256", secret).update(value).digest("hex"); }
function sameText(left: string, right: string) {
  return timingSafeEqual(Buffer.from(signature(left, "comparison"), "hex"), Buffer.from(signature(right, "comparison"), "hex"));
}
function config() {
  const directory = readAccessDirectory();
  const password = process.env.EXCAVAGUARD_ACCESS_PASSWORD ?? "";
  const secret = process.env.EXCAVAGUARD_SESSION_SECRET ?? "";
  const projectId = process.env.EXCAVAGUARD_PROJECT_ID?.trim() || DEFAULT_PROJECT_ID;
  const accounts = Boolean(directory?.users.length);
  if (!z.uuid().safeParse(projectId).success || (!accounts && (
    (password && (password.length < 12 || secret.length < 32)) || (!password && process.env.NODE_ENV === "production")
  )) || (accounts && secret && secret.length < 32)) {
    throw new AppError(503, "ACCESS_NOT_CONFIGURED", "访问控制未配置完整，请检查账号目录、密码及会话密钥。");
  }
  return { directory, password, projectId, accounts,
    mode: accounts ? "accounts" as const : password ? "password" as const : "local" as const,
    secret: accounts ? signature(directory!.session_secret, secret || directory!.session_secret) : signature(`${projectId}:${password}`, secret) };
}
function checkOrigin(request: Request, local: boolean) {
  const url = new URL(request.url); const host = request.headers.get("host");
  if (local && (!["localhost", "127.0.0.1", "[::1]"].includes(url.hostname.toLowerCase()) ||
    (host && host.toLowerCase() !== url.host.toLowerCase()))) throw new AppError(403, "FORBIDDEN", "本地模式仅允许从本机访问。");
  const origin = request.headers.get("origin");
  if (request.headers.get("sec-fetch-site") === "cross-site" || (origin && origin !== url.origin)) throw new AppError(403, "FORBIDDEN", "请从本站页面执行此操作。");
}
function tokenFrom(request: Request) {
  return request.headers.get("cookie")?.split(";").map(p => p.trim()).find(p => p.startsWith(`${COOKIE_NAME}=`))?.slice(COOKIE_NAME.length + 1) ?? "";
}
function userKey(settings: ReturnType<typeof config>, uid: string) {
  if (!settings.accounts) return uid === "local-operator" ? settings.secret : null;
  const user = settings.directory!.users.find(u => u.id === uid && !u.disabled);
  return user ? signature(user.password_hash, settings.secret) : null;
}
function readSession(request: Request, settings: ReturnType<typeof config>): Session | null {
  const token = tokenFrom(request);
  if (token.length > 4096) return null;
  const [version, encoded, mac, extra] = token.split(".");
  if (version !== "v2" || !encoded || !/^[a-f0-9]{64}$/.test(mac ?? "") || extra) return null;
  try {
    const parsed = sessionSchema.parse(JSON.parse(Buffer.from(encoded, "base64url").toString("utf8")));
    const key = userKey(settings, parsed.uid);
    return key && parsed.expires > Date.now() && sameText(mac, signature(encoded, key)) ? parsed : null;
  } catch { return null; }
}
function identity(request: Request) {
  const settings = config(); checkOrigin(request, settings.mode === "local");
  const session = readSession(request, settings);
  const uid = settings.mode === "local" ? "local-operator" : session?.uid ?? null;
  const user = settings.directory?.users.find(u => u.id === uid && !u.disabled);
  return { settings, session, uid, user };
}
export function accessStatus(request: Request): AccessStatus {
  const { settings, session, uid, user } = identity(request);
  const projects = uid ? (settings.directory ? settings.directory.projects.filter(p => p.active).flatMap(project => {
    const membership = settings.directory!.memberships.find(m => m.user_id === uid && m.project_id === project.id);
    return membership ? [{ id: project.id, name: project.name, role: membership.role }] : [];
  }) : [{ id: settings.projectId, name: process.env.EXCAVAGUARD_PROJECT_NAME?.trim() || "默认工程", role: "admin" as const }]) : [];
  const selected = session?.project_id ?? (settings.accounts ? null : settings.projectId);
  return { mode: settings.mode, authenticated: Boolean(uid),
    project_id: projects.some(p => p.id === selected) ? selected : null,
    user: uid ? { id: uid, name: user?.name ?? "本地工程师" } : null,
    projects, can_create_project: Boolean(uid && (settings.accounts ? user?.is_admin : true)) };
}
export function requireIdentity(request: Request) {
  const status = accessStatus(request);
  if (!status.authenticated || !status.user) throw new AppError(401, "UNAUTHORIZED", "请先登录工作台。");
  return status;
}
export function requireAccess(request: Request, projectId?: string): LocalAccess {
  const status = requireIdentity(request);
  if (!status.project_id) throw new AppError(403, "FORBIDDEN", "请先选择获授权的工程。");
  const expected = request.headers.get("x-excavaguard-project");
  if ((expected && expected !== status.project_id) || (projectId && projectId !== status.project_id)) throw new AppError(403, "FORBIDDEN", "当前工程已变化或无权访问该工程，请重新选择工程。");
  const access: LocalAccess = { owner_id: status.user!.id, project_id: status.project_id };
  // Keep old single-operator callers compatible; membership mode shares project history.
  if (readAccessDirectory()) access.role = status.projects!.find(p => p.id === status.project_id)!.role;
  return access;
}
export function requireProjectAction(request: Request, action: "write" | "review" | "standards", projectId?: string): LocalAccess {
  const access = requireAccess(request, projectId);
  const roles: Record<typeof action, ProjectRole[]> = {
    write: ["admin", "reviewer", "engineer"], review: ["admin", "reviewer"], standards: ["admin", "reviewer", "engineer"],
  };
  if (access.role && !roles[action].includes(access.role)) throw new AppError(403, "FORBIDDEN", "当前工程角色无权执行此操作。");
  return access;
}
function cookie(request: Request, value: string, seconds = SESSION_SECONDS) {
  return `${COOKIE_NAME}=${value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${seconds}` + (new URL(request.url).protocol === "https:" ? "; Secure" : "");
}
function issueCookie(request: Request, uid: string, projectId: string | null, expires = Date.now() + SESSION_SECONDS * 1000) {
  const settings = config(); const key = userKey(settings, uid);
  if (!key) throw new AppError(401, "UNAUTHORIZED", "账号已失效，请重新登录。");
  const encoded = Buffer.from(JSON.stringify({ uid, project_id: projectId, expires })).toString("base64url");
  return cookie(request, `v2.${encoded}.${signature(encoded, key)}`, Math.max(0, Math.ceil((expires - Date.now()) / 1000)));
}
export function loginCookie(request: Request, password: string, username?: string) {
  const settings = config(); checkOrigin(request, settings.mode === "local");
  if (settings.accounts) {
    const user = settings.directory!.users.find(u => u.username === username?.trim().toLowerCase() && !u.disabled);
    if (!user || !verifyPassword(password, user.password_hash)) throw new AppError(401, "UNAUTHORIZED", "账号或密码不正确。");
    return issueCookie(request, user.id, null);
  }
  if (!settings.password || !sameText(password, settings.password)) throw new AppError(401, "UNAUTHORIZED", "密码不正确。");
  return issueCookie(request, "local-operator", settings.projectId);
}
export function selectProjectCookie(request: Request, projectId: string) {
  const status = requireIdentity(request);
  if (!status.projects?.some(p => p.id === projectId)) throw new AppError(403, "FORBIDDEN", "无权访问该工程。");
  const { session } = identity(request);
  return issueCookie(request, status.user!.id, projectId, session?.expires);
}
export function logoutCookie(request: Request) {
  accessStatus(request); return cookie(request, "", 0);
}
