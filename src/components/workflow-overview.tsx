import { CircleDashed, GitBranch } from "lucide-react";
import { agentIdSchema } from "@/contracts/identifiers";
import { agentRegistry } from "@/server/agents/registry";

export function WorkflowOverview() {
  return (
    <section className="panel workflow-panel" id="workflow" aria-labelledby="workflow-title">
      <div className="section-heading">
        <div>
          <span className="eyebrow">协作流程</span>
          <h2 id="workflow-title">从监测数据，到可复核的草稿</h2>
        </div>
        <GitBranch size={22} aria-hidden="true" />
      </div>
      <p className="section-description">以下为已规划的角色分工，执行链路尚未接入。</p>
      <ol className="workflow-list">
        {agentIdSchema.options.map((id, index) => {
          const agent = agentRegistry[id];
          return (
            <li key={id}>
              <span className="step-number">{String(index + 1).padStart(2, "0")}</span>
              <div><h3>{agent.name}</h3><p>{agent.responsibility}</p></div>
              <span className="step-status"><CircleDashed size={14} aria-hidden="true" />待接入</span>
            </li>
          );
        })}
      </ol>
      <p className="workflow-footnote">数据缺失时暂停，证据不足时弃权，审计问题退回责任角色。</p>
    </section>
  );
}
