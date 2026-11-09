import { preparationSummarySchema } from '@/contracts/pre-agent-preparation';
export function PreparationSummary({payload}:{payload:unknown}){
  const data=preparationSummarySchema.safeParse((payload as {project?:{pre_agent_preparation?:unknown}}|undefined)?.project?.pre_agent_preparation);
  if(!data.success)return null;
  const {scene,facts,sources}=data.data;
  return <section aria-label="三智能体前置准备" className="wb-alert">
    <h3>① 场景适配与判据匹配</h3>
    <p>{scene.engineering_name} · {scene.settings_source==='project'?'采用已保存的项目设置':'采用本次工程设置'} · 项目补充规范{scene.project_standards}份 · 已确认补充规则{scene.supplemental_rules}条。</p>
    <details><summary>规范检索范围与实际采用依据</summary>
      <p>公共规范目录{scene.public_standards.length}本，其中有效且适用{scene.public_standards.filter(s=>s.status==='active'&&s.applicable).length}本。目录表示检索范围，实际判级只使用已配置并适用的规则。</p>
      {facts.adopted_criteria.map((c,i)=><p key={i}>{c.name} · {c.clause||'条款待核'}</p>)}
      {!facts.adopted_criteria.length&&<p>未形成可展示的已采用判据，请核对待核事项。</p>}
    </details>
    <h3>② 确定性计算、规则判级与事实冻结</h3>
    <p>{facts.start_date} 至 {facts.end_date} · {sources.length}份监测文件 · {facts.channels}个通道 · {facts.observations}条观测。</p>
    <p>未知{facts.unknown}条，待核{facts.pending}条。数据、采用判据及版本已固定，交由三智能体协同分析与核验。</p>
    {facts.gaps.length>0&&<details><summary>查看缺口与待核事项</summary>{facts.gaps.map((g,i)=><p key={i}>{g}</p>)}</details>}
  </section>;
}
