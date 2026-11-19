import { it, expect } from 'vitest';
import { readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { runJudgement } from '@/server/skills/evaluate-thresholds/runner';
import { executeAgentRun } from '@/server/agents/executor';
import { readStandardCatalog } from '@/server/evidence/standard-catalog';

it('隧道模板也逐本检索并交付16本规范覆盖清单，使用真实本地RAG', async () => {
  const base = '测试数据/隧道模拟_2026-11-01至14';
  const context = JSON.parse(readFileSync(resolve(base, '工程参数_SIMULATED.json'), 'utf8'));
  const engine = await runJudgement({adapterId:'tunnel-monitoring',context,
    filePath:resolve(base,'SIMULATED_隧道监测_2026-11-14.csv'),reportDate:'2026-11-14'});
  const run = await executeAgentRun({enginePayload:engine.result,reportMode:'template'});
  expect(run.state.audit_result?.valid, JSON.stringify(run.terminalAction)).toBe(true);
  const frozen = run.state.evidence_snapshot!.artifact!.payload as {coverage:{completed:boolean;catalogue_count:number;standards:Array<{standard_version:string;status:string;retained_ids:string[]}>};evidence:Array<{id:string;metadata:{standard_version:string}}>};
  expect(frozen.coverage.completed).toBe(true);
  expect(frozen.coverage.catalogue_count).toBe(16);
  expect(frozen.coverage.standards.map(s=>s.standard_version).sort()).toEqual(readStandardCatalog('tunnel-monitoring',context).map(s=>s.standard_version).sort());
  expect(new Set(frozen.evidence.map(e=>e.metadata.standard_version)).size).toBeGreaterThan(1);
  for (const entry of frozen.coverage.standards) {
    expect(['matched','no_relevant_hit','skipped_status','skipped_scope']).toContain(entry.status);
    if(entry.status==='matched')expect(entry.retained_ids.length).toBeGreaterThan(0);
  }
  const target=resolve('var/acceptance/tunnel-standard-coverage');mkdirSync(target,{recursive:true});
  const draft=run.state.report_draft!;
  expect(draft.artifacts[0].sheets).toContain('规范检索覆盖');
  for(const a of draft.artifacts)copyFileSync(resolve(a.relative_path),resolve(target,a.file_name));
  writeFileSync(resolve(target,'规范逐本核查.json'),JSON.stringify(frozen,null,2));
  writeFileSync(resolve(target,'文件审计.json'),JSON.stringify(run.state.audit_result,null,2));
},120000);
