import{readFileSync,writeFileSync}from'node:fs';import{isDeepStrictEqual}from'node:util';import{resolve}from'node:path';import{runJudgement}from'@/server/skills/evaluate-thresholds/runner';
const root=resolve(process.env.EXCAVAGUARD_AGENT_EVAL_ROOT??'../验收结果/2026-11-04_三Agent作用验证');const fixture=JSON.parse(readFileSync(resolve(root,'SIMULATED_输入与预期.json'),'utf8'));
const rows=JSON.parse(readFileSync(resolve(root,'对照汇总.json'),'utf8'));
for(const r of rows){const s=JSON.parse(readFileSync(resolve(root,r.name,'execution.json'),'utf8')).state;const clean=structuredClone(s.engine_snapshot.payload);delete clean.project.supporting_context;
 // Compare calculated items and summary with the program; compare complete frozen input across all experimental conditions.
 const result=await runJudgement({adapterId:'tunnel-monitoring',context:fixture.context,records:fixture.records,reportDate:'2026-10-02',project:{name:'SIMULATED三Agent功能对照'}});
 r.computed_items_unchanged=isDeepStrictEqual(clean.items,result.result.items);r.summary_unchanged=isDeepStrictEqual(clean.summary,result.result.summary);
 const baseline=JSON.parse(readFileSync(resolve(root,rows[0].name,'execution.json'),'utf8')).state.engine_snapshot;
 r.frozen_input_unchanged=isDeepStrictEqual(s.engine_snapshot.payload,baseline.payload)&&s.engine_snapshot.ref.content_hash===baseline.ref.content_hash;
 if(!r.computed_items_unchanged||!r.summary_unchanged||!r.frozen_input_unchanged)throw new Error('FACT_CHANGE '+r.name);
 writeFileSync(resolve(root,r.name,'验证摘要.json'),JSON.stringify(r,null,2)+'\n');
 console.log(r.name,'same_frozen_input',r.frozen_input_unchanged,'same_items',r.computed_items_unchanged);
}
writeFileSync(resolve(root,'对照汇总.json'),JSON.stringify(rows,null,2)+'\n');
