import "server-only";
import type { ContextDocument } from "@/contracts/project-context";
import { adapterIdFromPayload, readScenePolicy } from "@/server/engineering-adapters/registry";
function tokens(text:string){const out=new Set<string>();for(const word of text.toLowerCase().match(/[a-z0-9_-]+|[\u3400-\u9fff]+/g)??[]){if(/[\u3400-\u9fff]/.test(word)){for(let i=0;i<word.length-1;i++)out.add(word.slice(i,i+2));}else out.add(word);}return out;}
export function retrieveSimilarCases(payload:unknown,documents:ContextDocument[]){
 const engine=payload as {items?:Array<{metric_key?:string;metric_name?:string}>;project?:{professional_parameters?:{case_context?:Record<string,string>}}};
 const policy=readScenePolicy(adapterIdFromPayload(payload));const context={...(engine.project?.professional_parameters?.case_context??{}),...policy.supporting_context.case_defaults};
 const metrics=new Set((engine.items??[]).map(i=>i.metric_key));
 const query=[...new Set((engine.items??[]).flatMap(i=>[i.metric_name??'',i.metric_key??'',...policy.form_rules.filter(([,terms])=>terms.some(t=>(i.metric_name??'').includes(t))).flatMap(([,terms])=>terms)]).filter(t=>t.length>1))];
 const rows=documents.filter(d=>d.kind==='case').flatMap(d=>d.records.map((r,index)=>({d,r,index,terms:tokens(r.text)})));
 const df=new Map<string,number>();for(const row of rows)for(const term of row.terms)df.set(term,(df.get(term)??0)+1);
 const queryTokens=tokens(query.join(' '));
 const hits=rows.flatMap(({d,r,index,terms})=>{
  const dimensions=['method','soil','stage','groundwater'] as const;
  const conflicts=dimensions.filter(k=>context[k]&&r[k]&&context[k]!==r[k]);if(conflicts.length)return [];
  const matches=[...r.metric_keys.filter(k=>metrics.has(k)),...query.filter(t=>r.text.includes(t))];
  const overlap=[...queryTokens].filter(t=>terms.has(t));if(!matches.length)return [];
  const conditions=dimensions.filter(k=>context[k]&&r[k]===context[k]);
  const score=matches.length*4+conditions.length*8+overlap.reduce((n,t)=>n+Math.log(1+(rows.length+1)/((df.get(t)??0)+1)),0)/Math.sqrt(Math.max(1,terms.size));
  return [{document_id:d.document_id,source_title:d.title,sha256:d.sha256,record_index:index,excerpt:r.text.slice(0,2000),source_location:r.source_location??`记录${index+1}`,source_truncated:r.text.length>2000,matched_terms:[...new Set(matches)],matched_conditions:conditions,score,method:'metric_condition_and_idf_keyword_ranking',similarity_limit:conditions.length?'条件仅按已提供标签匹配，不能证明因果或直接采用处置':'施工条件未充分提供，仅为内容相关候选，可比性待核'}];
 }).sort((a,b)=>b.score-a.score||a.document_id.localeCompare(b.document_id));
 return {status:!rows.length?'not_provided':hits.length?'matched':'no_relevant_case',cases:hits.slice(0,policy.supporting_context.max_case_hits),truncated:hits.length>policy.supporting_context.max_case_hits};
}
