import "server-only";
import { readFileSync } from "node:fs";
import { randomBytes, randomUUID } from "node:crypto";
import { resolve } from "node:path";
import { DEFAULT_PROJECT_ID } from "@/contracts/access";
import { accessDirectorySchema, type AccessDirectory } from "@/contracts/project-access";
import { AppError } from "@/server/api/errors";
import { atomicJson, withFileLock } from "@/server/storage/atomic";

export function accessDirectoryPath() {
  return resolve(/* turbopackIgnore: true */ process.env.EXCAVAGUARD_ACCESS_FILE || "var/access/directory.json");
}
export function readAccessDirectory(): AccessDirectory | null {
  try { return accessDirectorySchema.parse(JSON.parse(readFileSync(/* turbopackIgnore: true */ accessDirectoryPath(), "utf8"))); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw new AppError(503, "ACCESS_NOT_CONFIGURED", "项目成员配置不可读取或结构不合法，请检查服务端授权目录。");
  }
}
export function legacyDirectory(): AccessDirectory {
  const projectId = process.env.EXCAVAGUARD_PROJECT_ID?.trim() || DEFAULT_PROJECT_ID;
  return accessDirectorySchema.parse({ version: 1, session_secret: randomBytes(32).toString("hex"), users: [],
    projects: [{ id: projectId, name: process.env.EXCAVAGUARD_PROJECT_NAME?.trim() || "默认工程", active: true }],
    memberships: [{ user_id: "local-operator", project_id: projectId, role: "admin" }] });
}
export async function createAuthorizedProject(userId: string, name: string) {
  const file = accessDirectoryPath();
  return withFileLock(`${file}.lock`, async () => {
    const directory = readAccessDirectory() ?? legacyDirectory();
    const user = directory.users.find(u => u.id === userId && !u.disabled);
    if (directory.users.length ? !user?.is_admin : userId !== "local-operator") {
      throw new AppError(403, "FORBIDDEN", "仅系统管理员可新建工程。");
    }
    if (directory.projects.some(p => p.name === name && p.active)) throw new AppError(409, "INVALID_REQUEST", "工程名称已存在，请使用可区分的名称。");
    const project = { id: randomUUID(), name, active: true };
    directory.projects.push(project);
    directory.memberships.push({ user_id: userId, project_id: project.id, role: "admin" });
    await atomicJson(file, accessDirectorySchema.parse(directory));
    return { ...project, role: "admin" as const };
  });
}
