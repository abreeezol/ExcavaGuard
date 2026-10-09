import "server-only";
import type { AgentId, SkillId } from "@/contracts/identifiers";

type AgentDefinition = {
  name: string;
  responsibility: string;
  tools: readonly SkillId[];
  status: "planned";
};

// 角色与工具白名单仅作注册信息；运行时、提示词、路由和终止控制尚未实现。
export const agentRegistry = {
  supervisor: {
    name: "Supervisor",
    responsibility: "规划任务、调度角色，管理冲突与人工接管。",
    tools: [],
    status: "planned",
  },
  "data-governance": {
    name: "数据治理",
    responsibility: "核验字段、单位与方向，拦截不满足分析条件的数据。",
    tools: ["parse-monitoring-data", "normalize-monitoring-data"],
    status: "planned",
  },
  "criteria-and-standards": {
    name: "判据与规范",
    responsibility: "将确定性计算事实与适用规范、规则来源绑定。",
    tools: ["evaluate-thresholds", "retrieve-standard-evidence"],
    status: "planned",
  },
  "risk-attribution": {
    name: "风险归因",
    responsibility: "比对案例与施工工况，呈现候选原因和证据局限。",
    tools: ["retrieve-similar-cases", "analyze-work-condition"],
    status: "planned",
  },
  "report-delivery": {
    name: "报告交付",
    responsibility: "使用结构化事实组织日报草稿，保留数字与证据绑定。",
    tools: ["render-daily-report"],
    status: "planned",
  },
  audit: {
    name: "独立审计",
    responsibility: "核对数字和引用，将问题退回责任角色。",
    tools: ["validate-report", "retrieve-standard-evidence", "retrieve-similar-cases"],
    status: "planned",
  },
} as const satisfies Record<AgentId, AgentDefinition>;
