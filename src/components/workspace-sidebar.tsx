import { ArrowUpRight, FileText, GitBranch, LayoutDashboard, ShieldCheck } from "lucide-react";

export function WorkspaceSidebar() {
  return (
    <aside className="sidebar">
      <a className="brand" href="#workspace" aria-label="ExcavaGuard 工作台">
        <span className="brand-symbol"><ShieldCheck size={24} aria-hidden="true" /></span>
        <span>ExcavaGuard<small>基坑监测日报助手</small></span>
      </a>
      <p className="nav-label">工作空间</p>
      <nav aria-label="工作台导航">
        <a href="#workspace"><LayoutDashboard size={18} aria-hidden="true" />日报工作台</a>
        <a href="#workflow"><GitBranch size={18} aria-hidden="true" />协作流程</a>
        <a href="#report"><FileText size={18} aria-hidden="true" />日报草稿</a>
      </nav>
      <div className="sidebar-note">
        <ShieldCheck size={21} aria-hidden="true" />
        <h2>每一份结论，都需要依据</h2>
        <p>规则主判 · 证据可溯<br />工程师复核与签发</p>
        <a href="#workflow">了解协作流程 <ArrowUpRight size={15} aria-hidden="true" /></a>
      </div>
      <span className="sidebar-footer">EXCAVAGUARD / 初始版本</span>
    </aside>
  );
}
