import "server-only";
import { createHmac, timingSafeEqual } from "node:crypto";
import { z } from "zod";
import { DEFAULT_PROJECT_ID, type AccessStatus, type LocalAccess } from "@/contracts/access";
import { AppError } from "@/server/api/errors";

const COOKIE_NAME = "excavaguard_session";
const SESSION_SECONDS = 8 * 60 * 60;

function config() {
  const password = process.env.EXCAVAGUARD_ACCESS_PASSWORD ?? "";
  const secret = process.env.EXCAVAGUARD_SESSION_SECRET ?? "";
  const projectId = process.env.EXCAVAGUARD_PROJECT_ID?.trim() || DEFAULT_PROJECT_ID;
  if (!z.uuid().safeParse(projectId).success ||
      (password && (password.length < 12 || secret.length < 32)) ||
      (!password && process.env.NODE_ENV === "production")) {
    throw new AppError(503, "ACCESS_NOT_CONFIGURED", "访问控制未配置完整。请配置访问密码与会话签名密钥。");
  }
  // 更换密码或项目后旧会话立即失效。
  return { password, secret: signature(`${projectId}:${password}`, secret), projectId };
}

function sameText(left: string, right: string): boolean {
  // 固定长度摘要比较，避免密码长度不同导致 timingSafeEqual 抛错。
  const hash = (value: string) => createHmac("sha256", "password-comparison").update(value).digest();
  return timingSafeEqual(hash(left), hash(right));
}

function signature(value: string, secret: string): string {
  return createHmac("sha256", secret).update(value).digest("hex");
}

function validSession(request: Request, secret: string): boolean {
  const token = request.headers.get("cookie")?.split(";")
    .map((part) => part.trim()).find((part) => part.startsWith(`${COOKIE_NAME}=`))
    ?.slice(COOKIE_NAME.length + 1);
  if (!token) return false;
  const parts = token.split(".");
  if (parts.length !== 2) return false;
  const [expires, mac] = parts;
  return /^\d+$/.test(expires) && Number(expires) > Date.now() &&
    /^[a-f0-9]{64}$/.test(mac) && sameText(mac, signature(expires, secret));
}

function checkOrigin(request: Request, local: boolean): void {
  const url = new URL(request.url);
  const host = request.headers.get("host");
  if (local && (
    !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname.toLowerCase()) ||
    (host && host.toLowerCase() !== url.host.toLowerCase())
  )) {
    throw new AppError(403, "FORBIDDEN", "本地模式仅允许从本机访问。");
  }
  const origin = request.headers.get("origin");
  const site = request.headers.get("sec-fetch-site");
  if (site === "cross-site" || (origin && origin !== url.origin)) {
    throw new AppError(403, "FORBIDDEN", "请从本站页面执行此操作。");
  }
}

export function accessStatus(request: Request): AccessStatus {
  const settings = config();
  checkOrigin(request, !settings.password);
  return {
    mode: settings.password ? "password" : "local",
    authenticated: !settings.password || validSession(request, settings.secret),
    project_id: settings.projectId,
  };
}

export function requireAccess(request: Request, projectId?: string): LocalAccess {
  const status = accessStatus(request);
  if (!status.authenticated) throw new AppError(401, "UNAUTHORIZED", "请先登录工作台。");
  if (projectId && projectId !== status.project_id) {
    throw new AppError(403, "FORBIDDEN", "无权访问该项目。");
  }
  return { owner_id: "local-operator", project_id: status.project_id };
}

function cookie(request: Request, value: string, maxAge: number): string {
  return `${COOKIE_NAME}=${value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${maxAge}` +
    (new URL(request.url).protocol === "https:" ? "; Secure" : "");
}

export function loginCookie(request: Request, password: string): string {
  const settings = config();
  checkOrigin(request, !settings.password);
  if (!settings.password || !sameText(password, settings.password)) {
    throw new AppError(401, "UNAUTHORIZED", "密码不正确。");
  }
  const expires = String(Date.now() + SESSION_SECONDS * 1000);
  return cookie(request, `${expires}.${signature(expires, settings.secret)}`, SESSION_SECONDS);
}

export function logoutCookie(request: Request): string {
  accessStatus(request);
  return cookie(request, "", 0);
}
