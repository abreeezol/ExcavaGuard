import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdtemp, readFile, writeFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import { it, expect } from "vitest";
import { verifyPassword } from "@/server/auth/password";
import { accessDirectorySchema } from "@/contracts/project-access";

const exec = promisify(execFile);
it("账号管理工具保留既有工程授权、哈希密码、生成私有凭据并支持授权撤销", async () => {
  const root = await mkdtemp(join(tmpdir(), "excavaguard-account-cli-"));
  const file = join(root, "directory.json");
  const a = "11111111-1111-4111-8111-111111111111", b = "22222222-2222-4222-8222-222222222222";
  const password = "synthetic-cli-password-2026";
  const env = { ...process.env, EXCAVAGUARD_ACCESS_FILE: file, EXCAVAGUARD_PROJECT_ID: a, EXCAVAGUARD_NEW_PASSWORD: password };
  const command = async (args: string[], configuredPassword = true) => {
    const environment: NodeJS.ProcessEnv = { ...env };
    if (!configuredPassword) delete environment.EXCAVAGUARD_NEW_PASSWORD;
    const result = await exec(process.execPath, ["tools/access/manage.mjs", ...args], { env: environment });
    expect(result.stdout).not.toContain(password); return result.stdout;
  };
  try {
    await writeFile(file, JSON.stringify({ version: 1, session_secret: randomBytes(32).toString("hex"), users: [],
      projects: [{ id: a, name: "已有工程A", active: true }, { id: b, name: "已有工程B", active: true }],
      memberships: [{ user_id: "local-operator", project_id: a, role: "admin" }, { user_id: "local-operator", project_id: b, role: "admin" }] }));
    await command(["init", "--username", "admin", "--name", "验收管理员"]);
    let directory = accessDirectorySchema.parse(JSON.parse(await readFile(file, "utf8")));
    expect(directory.memberships).toHaveLength(2);
    expect(directory.memberships.every(m => m.user_id === directory.users[0].id)).toBe(true);
    expect(verifyPassword(password, directory.users[0].password_hash)).toBe(true);
    expect((await stat(file)).mode & 0o077).toBe(0);
    await command(["add-user", "--username", "engineer"], false);
    const credentials = await readFile(join(root, "credentials/engineer.txt"), "utf8");
    const generatedPassword = credentials.split("初始密码：")[1].trim();
    directory = accessDirectorySchema.parse(JSON.parse(await readFile(file, "utf8")));
    expect(verifyPassword(generatedPassword, directory.users.find(u => u.username === "engineer")!.password_hash)).toBe(true);
    expect((await stat(join(root, "credentials/engineer.txt"))).mode & 0o077).toBe(0);
    await command(["grant", "--username", "engineer", "--project", a, "--role", "engineer"]);
    const summary = await command(["list"]);
    expect(summary).not.toMatch(/password_hash|session_secret|scrypt:/);
    expect(summary).not.toContain(generatedPassword);
    await command(["revoke", "--username", "engineer", "--project", a]);
    await command(["set-password", "--username", "engineer"]);
    await command(["disable-user", "--username", "engineer"]);
    directory = accessDirectorySchema.parse(JSON.parse(await readFile(file, "utf8")));
    const engineer = directory.users.find(u => u.username === "engineer")!;
    expect(engineer.disabled).toBe(true); expect(verifyPassword(password, engineer.password_hash)).toBe(true);
    expect(directory.memberships.some(m => m.user_id === engineer.id)).toBe(false);
  } finally { await rm(root, { recursive: true, force: true }); }
});
