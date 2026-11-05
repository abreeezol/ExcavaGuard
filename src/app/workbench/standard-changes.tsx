"use client";
import { useEffect, useState } from "react";
import type { ProjectStandardDocument } from "@/contracts/project-standards";
import type { StandardChangeState, ChangeDecision, ProposedRule } from "@/contracts/standard-changes";
const statusLabel={pending:"待确认",returned:"已退回",published:"已发布",rejected:"未采用",disabled:"已停用"};
export function StandardChanges({projectId,documents,disabled,canReview,onBusyChange}:{projectId:string;documents:ProjectStandardDocument[];disabled:boolean;canReview:boolean;onBusyChange:(v:boolean)=>void}){
  const [state,setState]=useState<StandardChangeState|null>(null);
  const [busy,setBusy]=useState(false);const [message,setMessage]=useState("");
  const [notes,setNotes]=useState<Record<string,string>>({});
  const [choices,setChoices]=useState<Record<string,ChangeDecision>>({});
  const [edits,setEdits]=useState<Record<string,ProposedRule>>({});
  const [runs,setRuns]=useState<{run_id:string;report_date?:string}[]>([]);
  const [runId,setRunId]=useState('');
  const [previews,setPreviews]=useState<Record<string,{affected_count:number;rule_count:number;notice:string;samples:{point_id:string;timestamp:string;before:string;after:string}[]}>>({});
  useEffect(()=>{let cancelled=false;
    void fetch('/api/project-standards/changes',{headers:{'X-Excavaguard-Project':projectId}}).then(async response=>{const data=await response.json();if(!response.ok)throw new Error(data.error?.message??'加载失败');if(!cancelled)setState(data.state);}).catch(e=>{if(!cancelled)setMessage(e.message);});
    return()=>{cancelled=true;};
  },[projectId]);
  useEffect(()=>{let cancelled=false;void fetch('/api/runs',{headers:{'X-Excavaguard-Project':projectId}}).then(async r=>{if(!r.ok)return;const data=await r.json();if(!cancelled){setRuns(data.runs??[]);setRunId(data.runs?.[0]?.run_id??'');}}).catch(()=>{});return()=>{cancelled=true;};},[projectId]);
  async function act(payload:Record<string,unknown>){
    if(!state)return;setBusy(true);onBusyChange(true);setMessage("");
    try{const response=await fetch('/api/project-standards/changes',{method:'POST',headers:{'Content-Type':'application/json','X-Excavaguard-Project':projectId},body:JSON.stringify({...payload,expected_version:state.version})});
      const data=await response.json();if(!response.ok)throw new Error(data.error?.message??'操作失败');
      if(data.preview){setPreviews(v=>({...v,[String(payload.id)]:data.preview}));return;}
      setState(data.state);setChoices({});setEdits({});setMessage('已保存。只有已发布且适用的规则参与后续新报告，历史报告保持原版本。');
    }catch(e){setMessage(e instanceof Error?e.message:'操作失败');}finally{setBusy(false);onBusyChange(false);}
  }
  const blocked=disabled||busy||!state;
  return <section aria-label="规范变更确认"><h3>规范变更审查与确认</h3>
    <p className="wb-hint">三智能体分析新增要求、整理关键差异并核验原文。请集中确认适用条件和规则；可修改候选或填写意见退回。已发布补充规则与原判据并行核查，不降低原等级。区间、公式等未支持要求会明确列为待核。</p>
    {documents.filter(d=>d.active).map(d=><div key={d.document_id} className="wb-actions"><span>《{d.standard_name}》</span><button className="wb-btn wb-btn-sm" disabled={blocked} onClick={()=>void act({action:'analyze',document_id:d.document_id})}>分析规则变更</button></div>)}
    {busy&&<p role="status">正在处理，请稍候；规范分析需要三角色依次核验。</p>}
    {message&&<p role="status">{message}</p>}
    {state?.changes.slice().reverse().map(change=>{
      const editable=canReview&&['pending','returned'].includes(change.status);
      return <details key={change.id} className="wb-alert" open={editable}><summary>《{change.standard_name}》 · {statusLabel[change.status]} · 修订{change.revision_round}/2轮</summary>
        <p>{change.proposal.summary}</p>
        <p className="wb-hint">规则记录版本：{state.version}；创建：{change.created_at}。确认仅代表本项目草稿采用要求，不代表正式签发。</p>
        {change.proposal.unresolved.map((x,i)=><p key={i}>待核：{x}</p>)}
        {['pending','returned'].includes(change.status)&&runs.length>0&&<div className="wb-actions"><label>试算记录<select disabled={blocked} value={runId} onChange={e=>setRunId(e.target.value)}>{runs.map(r=><option key={r.run_id} value={r.run_id}>{r.report_date??'区间报告'} · {r.run_id.slice(0,8)}</option>)}</select></label><button className="wb-btn wb-btn-sm" disabled={blocked||!runId} onClick={()=>void act({action:'preview',id:change.id,run_id:runId})}>试算原候选规则的影响</button></div>}
        {previews[change.id]&&<div><p>可试算规则{previews[change.id].rule_count}条；等级变化{previews[change.id].affected_count}条。</p><p>{previews[change.id].notice}</p>{previews[change.id].samples.map((s,i)=><p key={i}>{s.point_id} · {s.timestamp}：{s.before} → {s.after}</p>)}</div>}
        {change.audit.issues.map((x,i)=><p key={i}>审查问题〔{x.rule_id}〕：{x.message}</p>)}
        {change.proposal.rules.map(rule=>{const key=change.id+':'+rule.id;const edited=edits[key]??rule;
          const update=(patch:Partial<ProposedRule>)=>setEdits(v=>({...v,[key]:{...edited,...patch}}));
          return <div key={rule.id} className="wb-alert"><strong>{rule.metric_key} · {rule.kind==='control'?'固定控制要求':'仅供查证要求'}</strong>
            <p>{rule.explanation}</p><p>来源：《{change.standard_name}》 {change.standard_version} · {rule.clause} · 第{change.source_pages[rule.source_chunk_id]??'待核'}页</p>
            <blockquote style={{whiteSpace:'pre-wrap'}}>{rule.quote}</blockquote>
            <p>判据：{rule.field==='rate'?'变化速率':'累计量'} {rule.operator} {rule.threshold} {rule.unit} → {rule.risk_level}；正向变形。</p>
            {(change.validation[rule.id]??[]).map((x,i)=><p key={i}>程序校验：{x}</p>)}
            {editable&&<fieldset disabled={blocked} style={{border:0}}>
              <label className="wb-field">本条决定<select value={choices[key]?.action??''} onChange={e=>setChoices(v=>({...v,[key]:{rule_id:rule.id,action:e.target.value as 'accept'|'reject',note:v[key]?.note??''}}))}><option value="" disabled>请选择</option><option value="accept">接受</option><option value="reject">不采用</option></select></label>
              <details><summary>修改候选规则</summary>
                <label className="wb-field">阈值（必须能对应原文）<input type="number" min="0" step="any" value={edited.threshold} onChange={e=>update({threshold:Number(e.target.value)})}/></label>
                <label className="wb-field">比较关系<select value={edited.operator} onChange={e=>update({operator:e.target.value as '>='|'>'})}><option value=">=">达到或超过</option><option value=">">超过</option></select></label>
                <label className="wb-field">适用测点（逗号分隔，留空为全部）<input value={edited.point_ids.join(',')} onChange={e=>update({point_ids:e.target.value.split(/[,，]/).map(x=>x.trim()).filter(Boolean)})}/></label>
                {Object.entries(edited.conditions).map(([field,value])=><label className="wb-field" key={field}>适用条件：{field}<input value={String(value)} onChange={e=>update({conditions:{...edited.conditions,[field]:typeof value==='number'?Number(e.target.value):typeof value==='boolean'?e.target.value==='true':e.target.value}})}/></label>)}
              </details>
              <label className="wb-field">本条意见／修改理由<input maxLength={1500} value={choices[key]?.note??''} onChange={e=>setChoices(v=>({...v,[key]:{rule_id:rule.id,action:v[key]?.action??'reject',note:e.target.value}}))}/></label>
            </fieldset>}
          </div>;
        })}
        {change.feedback.map((f,i)=><p key={i}>处理意见（{f.at}）：{f.text}</p>)}
        {(editable||(canReview&&change.status==='published'))&&<label className="wb-field">集中确认说明／退回意见<textarea disabled={blocked} maxLength={3000} value={notes[change.id]??''} onChange={e=>setNotes(v=>({...v,[change.id]:e.target.value}))}/></label>}
        <div className="wb-actions">
          {editable&&<><button className="wb-btn" disabled={blocked||change.proposal.rules.some(r=>!choices[change.id+':'+r.id])} onClick={()=>void act({action:'publish',id:change.id,note:notes[change.id]??'',decisions:change.proposal.rules.map(r=>{const k=change.id+':'+r.id;return {...choices[k],...(edits[k]?{edited:edits[k]}:{})};})})}>确认并发布接受的规则</button>
          <button className="wb-btn wb-btn-sm" disabled={blocked} onClick={()=>void act({action:'return',id:change.id,note:notes[change.id]??''})}>退回修改</button>
          <button className="wb-btn wb-btn-sm" disabled={blocked} onClick={()=>void act({action:'reject',id:change.id,note:notes[change.id]??''})}>不采用本提案</button></>}
          {change.status==='returned'&&change.revision_round<2&&<button className="wb-btn" disabled={blocked} onClick={()=>void act({action:'analyze',document_id:change.document_id,previous_id:change.id})}>按意见重新分析</button>}
          {change.status==='returned'&&change.revision_round>=2&&<p>已达自动修订上限，请人工修改候选规则或不采用。</p>}
          {canReview&&change.status==='published'&&<button className="wb-btn wb-btn-sm" disabled={blocked} onClick={()=>void act({action:'disable',id:change.id,note:notes[change.id]??''})}>停用本组补充规则</button>}
        </div>
      </details>;
    })}
  </section>;
}
