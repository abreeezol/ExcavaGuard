import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

export function hashPassword(password: string): string {
  if (password.length < 12 || password.length > 1024) throw new Error("密码需为12至1024字符。");
  const salt = randomBytes(16).toString("hex");
  return `scrypt:${salt}:${scryptSync(password, salt, 64).toString("hex")}`;
}
export function verifyPassword(password: string, stored: string): boolean {
  if (!/^scrypt:[a-f0-9]{32}:[a-f0-9]{128}$/.test(stored)) return false;
  const [, salt, hash] = stored.split(":");
  return timingSafeEqual(scryptSync(password, salt, 64), Buffer.from(hash, "hex"));
}
