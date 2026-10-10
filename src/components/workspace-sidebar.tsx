import Link from "next/link";
import { ArrowUpRight, FileText, FlaskConical, GitBranch, LayoutDashboard, ShieldCheck } from "lucide-react";

export function WorkspaceSidebar() {
  return (
    <aside className="sidebar">
      <Link className="brand" href="/" aria-label="ExcavaGuard 工作台">
        <span className="brand-symbol"><ShieldCheck size={24} aria-hidden="true" /></span>
        <span>ExcavaGuard<small>基坑监测日报助手</small></span>
      </Link>
      <p className="nav-label">工作空间</p>
      <nav aria-label="工作台导航">
        <Link href="/"><LayoutDashboard size={18} aria-hidden="true" />日报工作台</Link>
        <Link href="/workbench"><FlaskConical size={18} aria-hidden="true" />可视化测试工作台</Link>
        <Link href="/#workflow"><GitBranch size={18} aria-hidden="true" />协作流程</Link>
        <Link href="/#report"><FileText size={18} aria-hidden="true" />日报草稿</Link>
      </nav>
      <div className="sidebar-note">
        <ShieldCheck size={21} aria-hidden="true" />
        <h2>每一份结论，都需要依据</h2>
        <p>规则主判 · 证据可溯<br />工程师复核与签发</p>
        <Link href="/#workflow">了解协作流程 <ArrowUpRight size={15} aria-hidden="true" /></Link>
      </div>
      <span className="sidebar-footer">EXCAVAGUARD / 初始版本</span>
    </aside>
  );
}
