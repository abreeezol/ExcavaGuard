// Explicit live verification: public standard text + handwritten synthetic monitoring only.
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, mkdirSync, copyFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join, dirname } from 'node:path';
if (process.env.EXCAVAGUARD_TEST_PROJECT_STANDARD_LIVE !== '1') throw new Error('Explicit opt-in required.');
const root = mkdtempSync(join(tmpdir(), 'excavaguard-public-standard-live-'));
process.env.EXCAVAGUARD_PROJECT_STANDARDS_ROOT = root;
const { uploadProjectStandard } = await import('@/server/evidence/project-standard-library');
const { runJudgement } = await import('@/server/skills/evaluate-thresholds/runner');
const { executeAgentRun } = await import('@/server/agents/executor');
const projectId = '33333333-3333-4333-8333-333333333333';
try {
  const standard = await uploadProjectStandard(projectId, new File([readFileSync(resolve(process.env.EXCAVAGUARD_TEST_STANDARD_PDF))], 'public-local-standard.pdf'), {
    standard_name: process.env.EXCAVAGUARD_TEST_STANDARD_NAME || '城市地下工程施工与运行监测技术规程',
    standard_version: process.env.EXCAVAGUARD_TEST_STANDARD_CODE || 'DB33/T1266-2021',
    region: '浙江省', applicability: '公开标准与完全人工合成的基坑监测数据，仅作软件验收', confirmed: true,
  });
  const engine = await runJudgement({ records: [0, 12, 22, 35, 50, 60, 62].map((value, i) => ({
    point_id: 'SIMULATED-P-01', metric_key: 'wall_top_horizontal_displacement', timestamp: `2026-10-0${i + 1}`,
    value, unit: 'mm', data_origin: 'simulated' })), reportDate: '2026-10-07',
    project: { name: '完全人工合成监测_公开地方标准引用验收' },
    context: { safety_level: '一级', support_type: '地下连续墙', excavation_depth_m: 20 } });
  const started = Date.now();
  const result = await executeAgentRun({ enginePayload: engine.result, reportMode: 'ai', projectStandards: { project_id: projectId, documents: [standard] } });
  const out = resolve('../process_file/项目补充规范验收/真实AI与RAG'); mkdirSync(out, { recursive: true });
  writeFileSync(join(out, '验收结果.json'), JSON.stringify(result, null, 2));
  if (result.state.report_draft) for (const artifact of result.state.report_draft.artifacts) copyFileSync(resolve(artifact.relative_path), join(out, artifact.file_name));
  const evidence = result.state.evidence_snapshot?.artifact?.payload?.evidence ?? [];
  const projectEvidence = evidence.filter(e => e.provider === 'project');
  const narrative = result.state.report_draft?.payload?.sections?.narrative;
  const paragraphs = narrative ? [...narrative.analysis, ...narrative.recommendations, ...narrative.appendix_analysis.flatMap(a => [a.analysis, a.recommendation])] : [];
  const used = paragraphs.flatMap(p => p.evidence_ids).filter(id => projectEvidence.some(e => e.id === id));
  const summary = { only_public_standard_and_synthetic_observations: true, elapsed_seconds: (Date.now() - started) / 1000,
    terminal: result.terminalAction, pages: standard.page_count, chunks: standard.chunk_count,
    project_hits: projectEvidence.length, project_citations_in_authored_prose: [...new Set(used)].length,
    semantic_audit_ran: result.state.trace.some(t => t.capability === 'llm-audit' && t.status === 'success'),
    model_calls: result.state.limits.model_calls_used, audit: result.state.audit_result?.valid,
    errors: result.state.trace.flatMap(t => t.error ? [t.error] : []), output: out };
  writeFileSync(join(out, '验收摘要.json'), JSON.stringify(summary, null, 2));
  console.info(JSON.stringify(summary));
  assert.equal(summary.terminal.reason_code, 'AUDIT_PASSED');
  assert.ok(summary.project_hits > 0); assert.ok(summary.project_citations_in_authored_prose > 0);
  assert.ok(summary.semantic_audit_ran);
  assert.deepEqual(result.state.engine_snapshot.payload, engine.result);
  if (result.state.report_draft) for (const artifact of result.state.report_draft.artifacts) rmSync(dirname(resolve(artifact.relative_path)), { recursive: true, force: true });
} finally { rmSync(root, { recursive: true, force: true }); }
