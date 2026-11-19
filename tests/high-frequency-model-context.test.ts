import { it, expect } from 'vitest';
import { buildReportModelContext } from '@/server/agents/report-model';

it('高频正文有界选取关键原观测，保留原始索引及全部冻结明细',()=>{
 const items=Array.from({length:3456},(_,i)=>({point_id:`SIM-${Math.floor(i/144)}`,metric_key:'crown_settlement',metric_name:'拱顶沉降',timestamp:`2026-11-17 ${String(Math.floor(i%144/6)).padStart(2,'0')}:${String(i%6*10).padStart(2,'0')}:00`,current:i,cumulative:i,rate:i%144===50?10:0,risk_level:i%144===50?'预警':i%144===0?'未知':'正常',utilization:i%144===50?2:0}));
 const input={project:{engineering_adapter:{id:'tunnel-monitoring'}},items,summary:{total:3456}};
 const frozen=JSON.stringify(input);const model=buildReportModelContext(input);
 expect(JSON.stringify(input)).toBe(frozen);expect(model.item_count).toBe(3456);expect(model.items.length).toBeLessThanOrEqual(200);
 for(let channel=0;channel<24;channel++){
  const spike=channel*144+50,last=channel*144+143,unknown=channel*144;
  for(const i of [spike,last,unknown])expect(model.items.some(row=>row.index===i)).toBe(true);
  expect(model.facts[`items.${spike}.risk_level`]).toBe('预警');
  expect(model.form_items.S).toContain(spike);
 }
 expect(model.facts['summary.total']).toBe(3456);
 expect(model.facts['items.1.current']).toBeUndefined();
});
