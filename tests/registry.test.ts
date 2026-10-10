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
    }
  });

  it("实现状态与脚本清单一致，且脚本真实存在", () => {
    for (const skill of skillRegistry) {
      if (skill.status === "implemented") {
        expect(skill.scripts.length).toBeGreaterThan(0);
        for (const script of skill.scripts) {
          // 文件不存在会抛错 —— 不允许"注册了但脚本没写"
          expect(() => readFileSync(script, "utf8")).not.toThrow();
          expect(script.startsWith(`skills/${skill.id}/`)).toBe(true);
        }
      } else {
        expect(skill.scripts).toEqual([]);
      }
    }
  });

  it("引擎已接通的 Skill 仅限解析与阈值判定", () => {
    const implemented = skillRegistry
      .filter((skill) => skill.status === "implemented")
      .map((skill) => skill.id)
      .sort();
    // 其余六个 Skill（数据标准化、证据检索、相似案例、工况分析、日报渲染、报告校验）
    // 仍只有 SKILL.md 契约，尚无实现
    expect(implemented).toEqual(["evaluate-thresholds", "parse-monitoring-data"]);
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
