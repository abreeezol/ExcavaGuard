import "server-only";
import { skillIdSchema, type SkillId } from "@/contracts/identifiers";

/**
 * 业务 Skill 注册表。
 *
 * `SKILL.md` 是能力契约；`scripts/` 下是**已可调用的实现**（Python 桥接脚本，
 * 由 `src/server/skills/python-bridge.ts` 以子进程方式调用）。
 * 只有两者都存在时才标记为 `implemented`。
 */

export type SkillStatus = "not_implemented" | "implemented";

export type SkillDefinition = {
  id: SkillId;
  contractPath: string;
  status: SkillStatus;
  /** 相对仓库根的脚本路径；未实现时为空数组。 */
  scripts: readonly string[];
};

/** 已实现（或部分实现）的 Skill 及其脚本。 */
const IMPLEMENTED: Partial<Record<SkillId, readonly string[]>> = {
  "parse-monitoring-data": ["skills/parse-monitoring-data/scripts/inspect_file.py"],
  "evaluate-thresholds": [
    "skills/evaluate-thresholds/scripts/run_judgement.py",
    "skills/evaluate-thresholds/scripts/check_strictness.py",
  ],
};

// SKILL.md 是能力契约，不能当作已可调用的业务实现。
export const skillRegistry: readonly SkillDefinition[] = skillIdSchema.options.map((id) => {
  const scripts = IMPLEMENTED[id] ?? [];
  return {
    id,
    contractPath: `skills/${id}/SKILL.md`,
    status: scripts.length > 0 ? "implemented" : "not_implemented",
    scripts,
  };
});
