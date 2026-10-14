import "server-only";
import { randomUUID } from "node:crypto";
import { link, mkdir, open, rename, rm } from "node:fs/promises";
import { dirname } from "node:path";
import { setTimeout } from "node:timers/promises";
import { AppError } from "@/server/api/errors";

/** 同目录临时文件完整写入后发布，排他模式用于不可变修订。 */
export async function atomicJson(path: string, value: unknown, exclusive = false): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    const file = await open(temporary, "wx", 0o600);
    try {
      await file.writeFile(JSON.stringify(value));
      await file.sync();
    } finally {
      await file.close();
    }
    if (exclusive) await link(temporary, path);
    else await rename(temporary, path);
  } finally {
    await rm(temporary, { force: true });
  }
}

/** 单机上传索引锁；崩溃遗留锁明确报错，不冒险覆盖其他进程的写入。 */
export async function withFileLock<T>(path: string, work: () => Promise<T>): Promise<T> {
  await mkdir(dirname(path), { recursive: true });
  let acquired = false;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      await mkdir(path);
      acquired = true;
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      await setTimeout(50);
    }
  }
  if (!acquired) throw new AppError(503, "STORAGE_ERROR", "存储正在写入或存在中断遗留锁，请稍后重试并检查存储状态。");
  try {
    return await work();
  } finally {
    await rm(path, { recursive: true, force: true });
  }
}
