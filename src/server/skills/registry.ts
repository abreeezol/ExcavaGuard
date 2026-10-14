import "server-only";
import { skillIdSchema, type SkillId } from "@/contracts/identifiers";

/**
 * 业务 Skill 注册表。
 *
 * `SKILL.md` 是能力契约；业务实现可以是 Python 桥接脚本，也可以是服务端 TypeScript
 * runner。只有契约和至少一种真实实现都存在时才标记为 `implemented`。
 */

export type SkillStatus = "not_implemented" | "implemented";

export type SkillDefinition = {
  id: SkillId;
  contractPath: string;
  status: SkillStatus;
  /** 相对仓库根的脚本路径；未实现时为空数组。 */
  scripts: readonly string[];
  /** 相对仓库根的服务端 runner 路径；没有时为 null。 */
  runner: string | null;
};

type SkillImplementation = {
  scripts?: readonly string[];
  runner?: string;
};

const IMPLEMENTED: Partial<Record<SkillId, SkillImplementation>> = {
  "parse-monitoring-data": {
    scripts: ["skills/parse-monitoring-data/scripts/inspect_file.py"],
  },
  "normalize-monitoring-data": {
    scripts: ["skills/normalize-monitoring-data/scripts/normalize_records.py"],
    runner: "src/server/skills/normalize-monitoring-data/runner.ts",
  },
  "evaluate-thresholds": {
    scripts: [
      "skills/evaluate-thresholds/scripts/run_judgement.py",
      "skills/evaluate-thresholds/scripts/check_strictness.py",
    ],
  },
  "retrieve-standard-evidence": {
    runner: "src/server/skills/retrieve-standard-evidence/runner.ts",
  },
  "render-daily-report": {
    scripts: ["skills/render-daily-report/scripts/render_daily_report.py"],
    runner: "src/server/skills/render-daily-report/runner.ts",
  },
  "validate-report": {
    scripts: ["skills/validate-report/scripts/validate_report.py"],
    runner: "src/server/skills/validate-report/runner.ts",
  },
};

// SKILL.md 是能力契约，不能当作已可调用的业务实现。
export const skillRegistry: readonly SkillDefinition[] = skillIdSchema.options.map((id) => {
  const implementation = IMPLEMENTED[id];
  const scripts = implementation?.scripts ?? [];
  const runner = implementation?.runner ?? null;
  return {
    id,
    contractPath: `skills/${id}/SKILL.md`,
    status:
      scripts.length > 0 || runner !== null
        ? "implemented"
        : "not_implemented",
    scripts,
    runner,
  };
});
