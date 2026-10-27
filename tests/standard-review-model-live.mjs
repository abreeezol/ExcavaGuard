// Explicit live test using only hand-written synthetic observations, no uploaded files.
import assert from 'node:assert/strict';
import {resolve,dirname} from 'node:path';
import {mkdirSync,copyFileSync,writeFileSync,rmSync} from 'node:fs';
import {runJudgement} from '@/server/skills/evaluate-thresholds/runner';
import {executeAgentRun} from '@/server/agents/executor';
if(process.env.EXCAVAGUARD_TEST_SYNTHETIC_MODEL!=='1') throw new Error('Explicit opt-in required for synthetic live model test.');
const records=[0,5,12,22,35,52,60,62].map((value,i)=>({point_id:'SIMULATED-P-01',metric_key:'wall_top_horizontal_displacement',timestamp:`2026-10-0${i+1}`,value,unit:'mm',data_origin:'simulated'}));
assert.ok(records.every(r=>r.data_origin==='simulated'&&r.point_id==='SIMULATED-P-01'));
const engine=await runJudgement({records,reportDate:'2026-10-08',reportPeriod:{type:'weekly',start_date:'2026-10-02',end_date:'2026-10-08'},
 context:{safety_level:'一级',support_type:'地下连续墙',excavation_depth_m:20},project:{name:'完全人工合成测试_不含真实工程数据'}});
const result=await executeAgentRun({enginePayload:engine.result,reportMode:'ai'});
const output=resolve('../process_file/多规范检索验收/纯模拟数据_真实模型与RAG');mkdirSync(output,{recursive:true});
writeFileSync(resolve(output,'验收结果.json'),JSON.stringify(result,null,2));
if(result.state.report_draft) {
 for(const file of result.state.report_draft.artifacts)copyFileSync(resolve(file.relative_path),resolve(output,file.file_name));
 rmSync(dirname(resolve(result.state.report_draft.artifacts[0].relative_path)),{recursive:true,force:true});
}
const evidence=result.state.evidence_snapshot?.artifact?.payload;
console.info(JSON.stringify({data:'only_hand_written_simulated_records',terminal:result.terminalAction,
 queried:evidence?.coverage?.queried_count,standards:[...new Set(evidence?.evidence?.map(e=>e.metadata.standard_version)??[])],
 modelCalls:result.state.limits.model_calls_used,audit:result.state.audit_result?.valid,revision_count:result.state.run.revision_count,
 errors:result.state.trace.flatMap(t=>t.error?[{capability:t.capability,error:t.error}]:[])}));
assert.equal(result.terminalAction.reason_code,'AUDIT_PASSED');
assert.ok(result.state.trace.some(t=>t.capability==='llm-audit'&&t.status==='success'),'Semantic model audit must actually run; fallback is not a live-model pass');
assert.equal(evidence.coverage.queried_count,29);
assert.ok(new Set(evidence.evidence.map(e=>e.metadata.standard_version)).size>1);
assert.deepEqual(result.state.engine_snapshot.payload,engine.result);
