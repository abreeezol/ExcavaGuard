import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { agentIdSchema } from "@/contracts/identifiers";
import { agentRegistry } from "@/server/agents/registry";
import { skillRegistry } from "@/server/skills/registry";

describe("角色与业务 Skill 契约", () => {
  it("所有注册能力都指向仓库中的真实契约", () => {
    for (const skill of skillRegistry) {
      const markdown = readFileSync(skill.contractPath, "utf8");
      expect(markdown).toMatch(new RegExp(`^name: ["']?${skill.id}["']?$`, "m"));
      expect(skill.status).toBe("not_implemented");
    }
  });

  it("角色工具白名单仅引用已登记能力", () => {
    const skillIds = new Set(skillRegistry.map((skill) => skill.id));
    for (const id of agentIdSchema.options) {
      expect(agentRegistry[id].status).toBe("planned");
      for (const tool of agentRegistry[id].tools) {
        expect(skillIds.has(tool)).toBe(true);
      }
    }
  });

  it("Supervisor 不直接计算，审计不修改源事实", () => {
    expect(agentRegistry.supervisor.tools).toEqual([]);
    expect(agentRegistry.audit.tools).not.toContain("normalize-monitoring-data");
    expect(agentRegistry.audit.tools).not.toContain("evaluate-thresholds");
    expect(agentRegistry.audit.tools).not.toContain("render-daily-report");
  });
});
