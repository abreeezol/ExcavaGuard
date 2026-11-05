import "server-only";
import type { AgentId, SkillId } from "@/contracts/identifiers";

type AgentDefinition = {
  name: string;
  responsibility: string;
  tools: readonly SkillId[];
  status: "implemented" | "foundation" | "planned";
};

// AI 模式为三个角色分别调用模型；事实计算与最终发布仍由规则和工程师负责。
export const agentRegistry: Record<AgentId, AgentDefinition> = {
  supervisor: {
    name: "Supervisor",
    responsibility: "依据冻结事实和工程师意见规划重点，提出最多三项绑定事实的定向查证；程序保证基础目录覆盖，记录新增证据与缺口，控制有限修订和人工接管。",
    tools: ["retrieve-standard-evidence", "retrieve-similar-cases", "analyze-work-condition"],
    status: "implemented",
  },
  "report-delivery": {
    name: "报告交付",
    responsibility: "用模型组织受约束的分析和建议，调用表式渲染，保留数字与证据绑定，规范名称及条文由渲染器统一展示。",
    tools: ["render-daily-report"],
    status: "implemented",
  },
  audit: {
    name: "独立审计",
    responsibility: "执行确定性文件审计与独立模型语义审查，核验多规范引用名称、条件与来源映射，将问题退回责任角色。",
    tools: ["validate-report", "retrieve-standard-evidence", "retrieve-similar-cases"],
    status: "implemented",
  },
};
