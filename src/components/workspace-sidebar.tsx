"use client";

import Link from "next/link";
import { FileCheck2, FileUp, LayoutDashboard, Settings2, ShieldCheck } from "lucide-react";

export const WORKBENCH_STEPS = [
  { id: "start", label: "工作台启动", description: "登录账号 · 选择工程", icon: LayoutDashboard },
  { id: "conditions", label: "工程条件", description: "确认条件 · 选择范围", icon: Settings2 },
  { id: "data", label: "数据与规范", description: "监测资料 · 补充判据", icon: FileUp },
  { id: "results", label: "分析与复核", description: "查看成果 · 工程师复核", icon: FileCheck2 },
] as const;
export type WorkbenchStep = typeof WORKBENCH_STEPS[number]["id"];

export function WorkspaceSidebar({ step, ready, onStepChange }: {
  step: WorkbenchStep;
  ready: boolean;
  onStepChange: (step: WorkbenchStep) => void;
}) {
  return <aside className="sidebar">
    <Link className="brand" href="/workbench" aria-label="ExcavaGuard 工程监测日报助手">
      <span className="brand-symbol"><ShieldCheck size={24} aria-hidden="true" /></span>
      <span>ExcavaGuard<small>工程监测日报助手</small></span>
    </Link>
    <p className="nav-label">报告工作流程</p>
    <nav aria-label="工作台步骤">
      {WORKBENCH_STEPS.map((item, index) => <button key={item.id} type="button"
        disabled={!ready && item.id !== "start"} aria-current={step === item.id ? "step" : undefined}
        onClick={() => onStepChange(item.id)}>
        <item.icon size={18} aria-hidden="true" />
        <span><strong>{index + 1} · {item.label}</strong><small>{item.description}</small></span>
      </button>)}
    </nav>
    <div className="sidebar-note">
      <ShieldCheck size={21} aria-hidden="true" />
      <h2>每一份结论，都需要依据</h2>
      <p>规则主判 · 证据可溯<br />工程师保留复核与签发权</p>
    </div>
    <span className="sidebar-footer">EXCAVAGUARD / 工程监测</span>
  </aside>;
}
