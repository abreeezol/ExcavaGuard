import "server-only";
import type { AgentId, SkillId } from "@/contracts/identifiers";

type AgentDefinition = {
  name: string;
  responsibility: string;
  tools: readonly SkillId[];
  status: "implemented" | "foundation" | "planned";
};

// 三个角色已接入同步执行器；运行持久化与独立模型语义审计仍待实现。
export const agentRegistry: Record<AgentId, AgentDefinition> = {
  supervisor: {
    name: "Supervisor",
    responsibility: "维护共享状态，控制报告、审计、有限退回与人工接管。",
    tools: [],
    status: "implemented",
  },
  "report-delivery": {
    name: "报告交付",
    responsibility: "使用结构化事实组织日报草稿，保留数字与证据绑定。",
    tools: ["render-daily-report"],
    status: "implemented",
  },
  audit: {
    name: "独立审计",
    responsibility: "核对数字和引用，将问题退回责任角色。",
    tools: ["validate-report", "retrieve-standard-evidence", "retrieve-similar-cases"],
    status: "implemented",
  },
};
