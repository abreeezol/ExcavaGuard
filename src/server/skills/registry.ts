import "server-only";
import { skillIdSchema, type SkillId } from "@/contracts/identifiers";

export type SkillDefinition = {
  id: SkillId;
  contractPath: string;
  status: "not_implemented";
};

// SKILL.md 是能力契约，不能当作已可调用的业务实现。
export const skillRegistry: readonly SkillDefinition[] = skillIdSchema.options.map(
  (id) => ({
    id,
    contractPath: `skills/${id}/SKILL.md`,
    status: "not_implemented",
  }),
);
