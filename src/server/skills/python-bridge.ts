import "server-only";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

/**
 * 引擎桥接（Node/TS → Python 子进程）
 * ===================================
 *
 * 确定性计算引擎是 `确定性计算层/pipeline/` 下的纯标准库 Python 代码
 * （阶段一 数据准备 / 阶段二 确定性计算 / 阶段三 规范比对，203 项回归测试）。
 *
 * 为什么不重写成 TypeScript：引擎的判定逻辑已被 203 项测试覆盖，
 * 二次实现等于给"确定性"计算引入偏差风险。桥接只做**协议转换**，
 * 不含任何判定逻辑。
 *
 * 协议：stdin 传 JSON 请求体，stdout 回 JSON 信封
 * （`excavaguard.skill_result/v1`），详见各脚本头部说明。
 */

export type SkillEnvelope = {
  schema: string;
  skill: string;
  ok: boolean;
  result?: unknown;
  summary?: unknown;
  trace?: Record<string, unknown>;
  error?: { code: string; message: string };
  [key: string]: unknown;
};

/** 引擎返回的结构化错误；`engineCode` 为引擎自己的错误码。 */
export class EngineError extends Error {
  readonly engineCode: string;

  constructor(engineCode: string, message: string) {
    super(message);
    this.name = "EngineError";
    this.engineCode = engineCode;
  }
}

/** 引擎不可用（找不到解释器 / 脚本 / 超时），与"引擎跑完但报错"区分开。 */
export class EngineUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EngineUnavailableError";
  }
}

const PYTHON_CANDIDATES = [
  process.env.EXCAVAGUARD_PYTHON,
  process.env.PYTHON,
  "python3",
  "python",
].filter((value): value is string => Boolean(value && value.trim()));

const TIMEOUT_MS = Number(process.env.EXCAVAGUARD_BRIDGE_TIMEOUT_MS ?? 30_000);

/** 引擎脚本位置：`<repo>/skills/<skill>/scripts/<file>`（远程 README 规定的位置）。 */
export function skillScriptPath(skill: string, file: string): string {
  return resolve(process.cwd(), "skills", skill, "scripts", file);
}

function spawnOnce(bin: string, script: string, request: unknown): Promise<SkillEnvelope> {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(bin, [script], {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      windowsHide: true,
    });

    let stdout = "";
    let stderr = "";
    let settled = false;

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill("SIGKILL");
      rejectPromise(new EngineUnavailableError(`引擎调用超时（${TIMEOUT_MS} ms）。`));
    }, TIMEOUT_MS);

    child.stdout.setEncoding("utf-8");
    child.stderr.setEncoding("utf-8");
    child.stdout.on("data", (chunk: string) => (stdout += chunk));
    child.stderr.on("data", (chunk: string) => (stderr += chunk));

    child.on("error", (error: NodeJS.ErrnoException) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      rejectPromise(error);
    });

    child.on("close", (exitCode) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);

      let parsed: SkillEnvelope;
      try {
        parsed = JSON.parse(stdout) as SkillEnvelope;
      } catch {
        // 带上 stderr 尾部：脚本崩在 stdout 输出之前时，这是唯一线索
        const tail = stderr.trim().split("\n").slice(-3).join(" / ");
        rejectPromise(
          new EngineUnavailableError(
            `引擎输出不是有效 JSON（exit=${exitCode ?? "?"}）。` +
              `stdout 前 200 字符：${stdout.slice(0, 200) || "（空）"}` +
              (tail ? `；stderr 末尾：${tail}` : ""),
          ),
        );
        return;
      }
      if (parsed.ok === false) {
        rejectPromise(
          new EngineError(parsed.error?.code ?? "ENGINE_ERROR", parsed.error?.message ?? "引擎返回失败。"),
        );
        return;
      }
      resolvePromise(parsed);
    });

    child.stdin.end(JSON.stringify(request), "utf-8");
  });
}

/**
 * 调用一个 Skill 脚本。按候选解释器依次尝试，只在"找不到可执行文件"时换下一个。
 */
export async function callSkillScript(
  skill: string,
  file: string,
  request: unknown,
): Promise<SkillEnvelope> {
  const script = skillScriptPath(skill, file);
  if (!existsSync(script)) {
    throw new EngineUnavailableError(`引擎脚本不存在：${script}`);
  }
  if (PYTHON_CANDIDATES.length === 0) {
    throw new EngineUnavailableError("未配置 Python 解释器（EXCAVAGUARD_PYTHON / PYTHON）。");
  }

  let lastError: unknown = null;
  for (const bin of PYTHON_CANDIDATES) {
    try {
      return await spawnOnce(bin, script, request);
    } catch (error) {
      if ((error as NodeJS.ErrnoException)?.code === "ENOENT") {
        lastError = error;
        continue;
      }
      throw error;
    }
  }
  throw new EngineUnavailableError(
    `找不到可用的 Python 解释器（尝试过 ${PYTHON_CANDIDATES.join("、")}）：` +
      `${lastError instanceof Error ? lastError.message : String(lastError)}`,
  );
}
