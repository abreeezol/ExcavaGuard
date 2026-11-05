import { instant,localDay,intervalEnd } from "@/server/context/time";
import "server-only";
import type { ContextDocument } from "@/contracts/project-context";
import { adapterIdFromPayload, readScenePolicy } from "@/server/engineering-adapters/registry";
function field(value: unknown,path:string): unknown { return path.split('.').reduce<unknown>((v,k)=>v&&typeof v==='object'?(v as Record<string,unknown>)[k]:undefined,value); }
export function analyzeWorkCondition(payload: unknown, documents: ContextDocument[]) {
  const engine = payload as {items?: Array<Record<string,unknown>>;project?:{report_date?:string;professional_parameters?:Record<string,unknown>};period?:{start_date:string;end_date:string;daily_items?:Array<Record<string,unknown>>};context?:{item_date?:string}};
  const policy=readScenePolicy(adapterIdFromPayload(payload)).supporting_context;
  const params=engine.project?.professional_parameters??{};
  const aliases=(params.section_aliases??{}) as Record<string,string>;
  const points=(params.point_sections??{}) as Record<string,string>;
  const canonical=(value:unknown)=>typeof value==='string'?(aliases[value]??value):undefined;
  const dayOf=(value:string|undefined)=>localDay(value,policy.timezone,policy.utc_offset);
  const records=documents.filter(d=>d.kind!=="case").flatMap(d=>d.records.map((r,i)=>({...r,kind:d.kind,document_id:d.document_id,source_title:d.title,record_index:i})));
  const end=engine.period?.end_date??engine.project?.report_date??engine.context?.item_date;
  const start=engine.period?.start_date??end;
  const relevant=records.filter(r=>start&&end&&r.timestamp&&dayOf(r.end_timestamp??r.timestamp)>=start.slice(0,10)&&dayOf(r.timestamp)<=end.slice(0,10));
  const links:Array<Record<string,unknown>>=[];
  const pending:Array<Record<string,unknown>>=[];
  const observations=engine.period?.daily_items??engine.items??[];
  const seen=new Set<string>();
  const byDay=new Map<string,typeof relevant>();
  for(const record of relevant){const day=dayOf(record.timestamp);byDay.set(day,[...(byDay.get(day)??[]),record]);}
  for(const [index,item] of observations.entries()) {
    const identity=JSON.stringify([item.point_id,item.metric_key,policy.time_policy==='same_day'?String(item.timestamp??end??"").slice(0,10):String(item.timestamp??end??"")]);
    if(seen.has(identity))continue;seen.add(identity);
    const originalSection=canonical(policy.section_fields.map(p=>field(item,p)).find(v=>typeof v==='string'&&v.trim()));
    const ledgerSection=canonical(points[String(item.point_id)]);
    const section=ledgerSection??originalSection;
    const positionConflict=ledgerSection&&originalSection&&ledgerSection!==originalSection;
    const day=dayOf(String(item.timestamp??end??""));
    for(const raw of policy.time_policy==='interval_overlap'?relevant:byDay.get(day)??[]) {
      const record={...raw,section:canonical(raw.section??(raw.point_id?points[raw.point_id]:undefined))};
      if(policy.time_policy==='interval_overlap') {
        const observation=instant(String(item.timestamp??end??''),policy.utc_offset);
        const begin=instant(record.timestamp,policy.utc_offset);const finish=intervalEnd(record.end_timestamp??record.timestamp,policy.utc_offset);
        const observationEnd=intervalEnd(String(item.timestamp??end??''),policy.utc_offset);
        if(observation===null||begin===null||finish===null)continue;
        const span=policy.time_window_hours*3600000;
        if((observationEnd??observation)<begin-span||observation>finish+span)continue;
      }
      if(positionConflict){pending.push({item_index:index,...record,text:record.text.slice(0,1000),relationship:"测点台账与观测区段冲突，不能自动关联"});continue;}
      const samePoint=record.point_id&&record.point_id===item.point_id;
      if (record.section && section && record.section !== section) {
        if(samePoint)pending.push({item_index:index,observation_scope:engine.period?"period.daily_items":"items",...record,text:record.text.slice(0,1000),relationship:"同测点与区段标识矛盾，位置关系待核"});
        continue;
      }
      if(record.point_id && record.point_id!==item.point_id) continue;
      const candidate={item_index:index,observation_scope:engine.period?"period.daily_items":"items",...record,text:record.text.slice(0,1000),source_truncated:record.text.length>1000,relationship:"按配置时间窗口且同区段或明确同测点，仅为关联线索，不证明因果"};
      if(samePoint || (section&&record.section===section)) links.push(candidate);
      else pending.push({...candidate,relationship:"位置关系未确认，不作为关联证据"});
    }
  }
  const groups=new Map<string,typeof relevant>();
  for(const record of relevant) if(record.assertion_key && (record.section||record.point_id)) {
    const key=JSON.stringify([instant(record.timestamp,policy.utc_offset),canonical(record.section??(record.point_id?points[record.point_id]:undefined))??null,record.assertion_key]);
    groups.set(key,[...(groups.get(key)??[]),record]);
  }
  const conflictGroups=[...groups.values()].filter(rows=>new Set(rows.map(r=>JSON.stringify(r.assertion_value))).size>1);
  const conflicts=conflictGroups.slice(0,10).map(rows=>rows.slice(0,5).map(r=>({...r,text:r.text.slice(0,1000)})));
  return {links:links.slice(0,policy.max_links),pending:pending.slice(0,policy.max_links),conflicts,
    truncated:links.length>policy.max_links||pending.length>policy.max_links||conflictGroups.length>10||conflictGroups.some(rows=>rows.length>5),
    work_condition_status:documents.some(d=>d.kind==='work_condition')?(relevant.some(r=>r.kind==='work_condition')?'provided_in_window':'no_record_in_window'):'not_provided',
    patrol_status:documents.some(d=>d.kind==='patrol')?(relevant.some(r=>r.kind==='patrol')?'provided_in_window':'no_record_in_window'):'not_provided',
    notice:"未提供不等于正常；同日不代表同一时刻；冲突或位置不明交由工程师核验，不改变监测风险。"};
}
