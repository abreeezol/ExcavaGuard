import Link from "next/link";
import { ArrowDown, FileCheck2, FileUp, FolderOpen, ShieldCheck } from "lucide-react";
import { WorkflowOverview } from "@/components/workflow-overview";
import { WorkspaceSidebar } from "@/components/workspace-sidebar";

export default function HomePage() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace">跳到主要内容</a>
      <WorkspaceSidebar />
      <main className="workspace" id="workspace">
        <header className="topbar">
          <span>工作空间 <span className="breadcrumb-divider">/</span> 日报工作台</span>
          <span className="status-pill"><span className="status-dot" />计算层已接通</span>
        </header>

        <div className="workspace-content">
          <section className="intro" aria-labelledby="page-title">
            <div>
              <p className="eyebrow">EXCAVAGUARD · 监测日报工作台</p>
              <h1 id="page-title">让每一份日报，有据可循。</h1>
              <p>汇集监测数据、规范证据与施工工况，辅助工程师整理可追溯的日报草稿。</p>
            </div>
            <a className="outline-link" href="#workflow">查看协作流程 <ArrowDown size={16} aria-hidden="true" /></a>
          </section>

          <div className="notice">
            <ShieldCheck size={19} aria-hidden="true" />
            <p>
              确定性计算层已接通：可上传监测数据与用户规范，运行风险识别。
              日报生成与鉴权仍待实现。
            </p>
          </div>

          <section className="panel data-panel" aria-labelledby="data-title">
            <div className="section-heading">
              <div><span className="eyebrow">开始一份日报</span><h2 id="data-title">监测资料</h2></div>
              <span className="muted-label">尚未导入数据</span>
            </div>
            <div className="empty-upload">
              <div className="empty-icon"><FileUp size={30} strokeWidth={1.5} aria-hidden="true" /></div>
              <h3>从一份监测数据开始</h3>
              <p>上传监测 CSV，补充当日施工工况，运行确定性计算与风险识别。</p>
              <Link className="wb-link" href="/workbench">
                <FolderOpen size={16} aria-hidden="true" />进入可视化测试工作台
              </Link>
              <span id="upload-help" className="helper-text">
                支持 CSV / TSV / XLSX，自动探测编码与列名
              </span>
            </div>
            <div className="data-footer">
              <span>01 确认项目与规则</span><span>02 导入监测资料</span><span>03 复核日报草稿</span>
            </div>
          </section>

          <div className="workspace-grid">
            <WorkflowOverview />
            <section className="panel report-panel" id="report" aria-labelledby="report-title">
              <div className="section-heading">
                <div><span className="eyebrow">交付与复核</span><h2 id="report-title">日报草稿</h2></div>
                <span className="draft-tag">待生成</span>
              </div>
              <div className="report-empty">
                <FileCheck2 size={43} strokeWidth={1.2} aria-hidden="true" />
                <h3>还没有日报草稿</h3>
                <p>完成数据校验与分析后，<br />在这里查看草稿、证据与待确认项。</p>
              </div>
              <div className="review-note">
                <h3><ShieldCheck size={16} aria-hidden="true" />工程师保留最终判断</h3>
                <p>系统仅辅助生成草稿。正式预警、审核和签发由工程师完成。</p>
              </div>
            </section>
          </div>
          <footer className="workspace-footer">
            <span>规则主判，RAG 举证，模型表达。</span>
            <span>ExcavaGuard · 工程师的日报助手</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
