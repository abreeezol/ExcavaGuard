/**
 * 引擎桥接冒烟测试（Node 侧）
 * ==========================
 *
 * 证明「Web 入口（Node/TS）→ 确定性计算引擎（Python）」这条单点链路可打通。
 *
 * **本文件是 `src/server/skills/evaluate-thresholds/runner.ts` 的原型**：
 * 逻辑一一对应，只是这里用纯 Node ESM 写、可直接运行，不需要 Next.js 工程。
 * 迁入远程仓库时，把 `spawnJudgement()` 原样搬进 TS 即可。
 *
 * 运行：
 *     node tools/bridge-smoke/run_judgement.mjs
 *     node tools/bridge-smoke/run_judgement.mjs --request my_request.json
 *
 * 退出码：0 全通过；1 有失败项。
 */

import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..");
const SCRIPT = resolve(REPO_ROOT, "skills", "evaluate-thresholds", "scripts", "run_judgement.py");

/** 候选 Python 解释器（按序尝试）。生产环境应由配置注入。 */
const PYTHON_CANDIDATES = [
  process.env.EXCAVAGUARD_PYTHON,
  process.env.PYTHON,
  "python3",
  "python",
].filter(Boolean);

const TIMEOUT_MS = Number(process.env.EXCAVAGUARD_BRIDGE_TIMEOUT_MS ?? 30000);

/**
 * 调用一次引擎。等价于未来的 `runner.ts`。
 *
 * @param {object} request 引擎请求体（见 run_judgement.py 的协议说明）
 * @param {{python?: string}} [opts]
 * @returns {Promise<object>} 引擎返回的 skill_result 信封
 */
export async function spawnJudgement(request, opts = {}) {
  const candidates = opts.python ? [opts.python] : PYTHON_CANDIDATES;
  let lastErr = null;

  for (const bin of candidates) {
    try {
      return await runOnce(bin, request);
    } catch (err) {
      if (err.code === "ENOENT") {
        lastErr = err;
        continue; // 换下一个解释器
      }
      throw err;
    }
  }
  throw new Error(
    `找不到可用的 Python 解释器（尝试过 ${candidates.join(", ")}）：${lastErr?.message ?? ""}`,
  );
}

function runOnce(bin, request) {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(bin, [SCRIPT], {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    });

    let stdout = "";
    let stderr = "";
    let settled = false;

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill("SIGKILL");
      rejectPromise(new Error(`引擎调用超时（${TIMEOUT_MS}ms）`));
    }, TIMEOUT_MS);

    child.stdout.setEncoding("utf-8");
    child.stderr.setEncoding("utf-8");
    child.stdout.on("data", (d) => (stdout += d));
    child.stderr.on("data", (d) => (stderr += d));

    child.on("error", (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      rejectPromise(err);
    });

    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);

      let parsed;
      try {
        parsed = JSON.parse(stdout);
      } catch {
        rejectPromise(
          new Error(`引擎输出不是有效 JSON（exit=${code}）\nstdout: ${stdout.slice(0, 500)}\nstderr: ${stderr.slice(0, 500)}`),
        );
        return;
      }
      if (parsed?.ok === false) {
        const e = new Error(parsed.error?.message ?? "引擎返回失败");
        e.code = parsed.error?.code;
        e.detail = parsed.error;
        rejectPromise(e);
        return;
      }
      if (stderr.trim()) {
        console.log(`  [引擎 stderr] ${stderr.trim().split("\n")[0]}`);
      }
      resolvePromise(parsed);
    });

    child.stdin.end(JSON.stringify(request), "utf-8");
  });
}

// ---------------------------------------------------------------------------
// 冒烟测试
// ---------------------------------------------------------------------------

const PASS = [];
const FAIL = [];
const check = (name, cond, detail = "") => {
  (cond ? PASS : FAIL).push(name);
  console.log(`[${cond ? "PASS" : "FAIL"}] ${name}${cond || !detail ? "" : `  -> ${detail}`}`);
};

function minimalRequest() {
  return {
    records: [0, 5, 12, 22, 35, 52, 60].map((v, i) => ({
      point_id: "WTHD-01",
      timestamp: `2026-08-${String(i + 1).padStart(2, "0")}`,
      metric: "wall_top_horizontal_displacement",
      value: v,
      unit: "mm",
    })),
    context: {
      safety_level: "一级",
      support_type: "地下连续墙",
      excavation_depth_m: 20.0,
    },
    options: { report_date: "2026-08-07", project: { name: "桥接冒烟工程" } },
  };
}

async function main() {
  const argFile = process.argv.indexOf("--request");
  const request =
    argFile >= 0 && process.argv[argFile + 1]
      ? JSON.parse(readFileSync(process.argv[argFile + 1], "utf-8"))
      : minimalRequest();

  console.log("=".repeat(72));
  console.log("引擎桥接冒烟测试（Node → Python）");
  console.log("=".repeat(72));
  console.log(`脚本      : ${SCRIPT}`);
  console.log(`记录数    : ${request.records.length}`);
  console.log();

  // --- 1. 正常路径 ---
  const t0 = Date.now();
  const res = await spawnJudgement(request);
  const elapsed = Date.now() - t0;

  check("引擎返回成功", res.ok === true);
  check("信封 schema 正确", res.schema === "excavaguard.skill_result/v1", res.schema);
  check("skill 标识正确", res.skill === "evaluate-thresholds", res.skill);
  check("返回日报载荷", !!res.result, String(Object.keys(res.result ?? {}).length));
  check("载荷 schema 正确",
    res.result?.schema === "excavaguard.daily_report_input/v1",
    res.result?.schema);
  check("载荷含逐条明细", Array.isArray(res.result?.items) && res.result.items.length === 7,
    String(res.result?.items?.length));
  check("载荷含报警清单", Array.isArray(res.result?.alerts) && res.result.alerts.length === 6,
    String(res.result?.alerts?.length));
  check("载荷含规范条文依据",
    res.result?.items?.[0]?.evidence?.standard === "GB 50497-2019",
    JSON.stringify(res.result?.items?.[0]?.evidence));
  check("原始观测表被正确识别（非全量弃权）",
    Object.keys(res.result?.summary?.by_risk_level ?? {}).includes("危险报警"),
    JSON.stringify(res.result?.summary?.by_risk_level));
  check("trace 含耗时", typeof res.trace?.elapsed_ms === "number", String(res.trace?.elapsed_ms));
  check("往返耗时 < 10s", elapsed < 10000, `${elapsed}ms`);

  console.log();
  console.log(`  风险分布 : ${JSON.stringify(res.result?.summary?.by_risk_level)}`);
  console.log(`  末条等级 : ${res.result?.items?.at(-1)?.risk_level}`);
  console.log(`  限值依据 : ${res.result?.items?.at(-1)?.checks?.[0]?.limit_basis}`);

  // --- 2. 错误路径：空 stdin ---
  let emptyFailed = false;
  try {
    await spawnJudgement({ records: [], context: {} });
  } catch (e) {
    emptyFailed = e.code === "INVALID_INPUT";
  }
  check("空 records 被拒绝且错误码正确", emptyFailed);

  // --- 3. 错误路径：缺 context ---
  let ctxFailed = false;
  try {
    await spawnJudgement({ records: [{ point_id: "P", timestamp: "2026-08-01", metric: "m", value: 1, unit: "mm" }] });
  } catch (e) {
    ctxFailed = e.code === "INVALID_INPUT";
  }
  check("缺 context 被拒绝", ctxFailed);

  console.log();
  console.log("=".repeat(72));
  console.log(`PASS: ${PASS.length}    FAIL: ${FAIL.length}`);
  if (FAIL.length) {
    console.log("失败项：");
    for (const f of FAIL) console.log("  -", f);
    process.exitCode = 1;
  } else {
    console.log("全部通过 —— 引擎与入口可打通");
  }
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  main().catch((e) => {
    console.error("桥接失败：", e);
    process.exitCode = 1;
  });
}
