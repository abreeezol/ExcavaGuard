import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { WorkspaceSidebar } from "@/components/workspace-sidebar";
import { WorkbenchClient } from "./workbench-client";

export const metadata: Metadata = {
  title: "可视化测试工作台 · ExcavaGuard",
  description:
    "上传监测数据与用户规范，运行确定性计算与风险识别，查看逐测点判定、生效规范来源与待复核项。",
};

export default function WorkbenchPage() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#workbench">跳到主要内容</a>
      <WorkspaceSidebar />
      <main className="workspace" id="workbench">
        <header className="topbar">
          <span>工作空间 <span className="breadcrumb-divider">/</span> 可视化测试工作台</span>
          <span className="status-pill"><span className="status-dot" />确定性计算层已接通</span>
        </header>

        <div className="workspace-content">
          <section className="intro">
            <div>
              <p className="eyebrow">EXCAVAGUARD · 端到端验证</p>
              <h1>上传数据，看它算出什么。</h1>
              <p>
                走的是真实链路：上传 → 阶段一 数据准备 → 阶段二 确定性计算 → 阶段三 规范比对。
                页面本身不做任何判定，只展示引擎返回的结构化载荷。
              </p>
            </div>
            <Link className="outline-link" href="/">
              <ArrowLeft size={16} aria-hidden="true" />返回工作台首页
            </Link>
          </section>

          <WorkbenchClient />

          <footer className="workspace-footer">
            <span>规则主判 · 证据可溯 · 弃权不放过</span>
            <span>ExcavaGuard · 可视化测试工作台</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
