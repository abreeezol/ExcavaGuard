import "server-only";
import type { AgentId, SkillId } from "@/contracts/identifiers";

type AgentDefinition = {
  name: string;
  responsibility: string;
  tools: readonly SkillId[];
  status: "foundation" | "planned";
};

// 三个角色均已有基础能力；端到端执行器、API 与持久化仍待接入。
export const agentRegistry = {
  supervisor: {
    name: "Supervisor",
    responsibility: "维护共享状态，控制报告、审计、有限退回与人工接管。",
    tools: [],
    status: "foundation",
  },
  "report-delivery": {
    name: "报告交付",
    responsibility: "使用结构化事实组织日报草稿，保留数字与证据绑定。",
    tools: ["render-daily-report"],
    status: "foundation",
  },
  audit: {
    name: "独立审计",
    responsibility: "核对数字和引用，将问题退回责任角色。",
    tools: ["validate-report", "retrieve-standard-evidence", "retrieve-similar-cases"],
    status: "foundation",
  },
} as const satisfies Record<AgentId, AgentDefinition>;
