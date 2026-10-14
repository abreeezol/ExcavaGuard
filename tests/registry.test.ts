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
        expect(skill.scripts.length > 0 || skill.runner !== null).toBe(true);
        for (const script of skill.scripts) {
          // 文件不存在会抛错 —— 不允许"注册了但脚本没写"
          expect(() => readFileSync(script, "utf8")).not.toThrow();
          expect(script.startsWith(`skills/${skill.id}/`)).toBe(true);
        }
        if (skill.runner) {
          expect(() => readFileSync(skill.runner!, "utf8")).not.toThrow();
          expect(skill.runner.startsWith("src/server/skills/")).toBe(true);
        }
      } else {
        expect(skill.scripts).toEqual([]);
        expect(skill.runner).toBeNull();
      }
    }
  });

  it("已接通的 Skill 包含解析、标准化、判定、规范证据、报告和审计", () => {
    const implemented = skillRegistry
      .filter((skill) => skill.status === "implemented")
      .map((skill) => skill.id)
      .sort();
    expect(implemented).toEqual([
      "evaluate-thresholds",
      "normalize-monitoring-data",
      "parse-monitoring-data",
      "render-daily-report",
      "retrieve-standard-evidence",
      "validate-report",
    ]);
  });

  it("角色工具白名单仅引用已登记能力", () => {
    const skillIds = new Set(skillRegistry.map((skill) => skill.id));
    for (const id of agentIdSchema.options) {
      for (const tool of agentRegistry[id].tools) {
        expect(skillIds.has(tool)).toBe(true);
      }
    }
    expect(agentIdSchema.options).toEqual(["supervisor", "report-delivery", "audit"]);
    expect(agentRegistry.supervisor.status).toBe("implemented");
    expect(agentRegistry["report-delivery"].status).toBe("implemented");
    expect(agentRegistry.audit.status).toBe("implemented");
  });

  it("Supervisor 不直接计算，审计不修改源事实", () => {
    expect(agentRegistry.supervisor.tools).toEqual([]);
    expect(agentRegistry.audit.tools).not.toContain("normalize-monitoring-data");
    expect(agentRegistry.audit.tools).not.toContain("evaluate-thresholds");
    expect(agentRegistry.audit.tools).not.toContain("render-daily-report");
  });
});
