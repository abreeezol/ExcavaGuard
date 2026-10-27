import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { mkdtempSync, rmSync, readFileSync, existsSync, mkdirSync, copyFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';

const root = mkdtempSync(join(tmpdir(), 'excavaguard-project-standards-'));
process.env.EXCAVAGUARD_PROJECT_STANDARDS_ROOT = join(root, 'project-standards');
process.env.EXCAVAGUARD_UPLOAD_ROOT = join(root, 'uploads');
process.env.EXCAVAGUARD_RUN_ROOT = join(root, 'runs');
process.env.EXCAVAGUARD_STORAGE_PROVIDER = 'local';
process.env.EXCAVAGUARD_PROJECT_ID = '11111111-1111-4111-8111-111111111111';
delete process.env.EXCAVAGUARD_ACCESS_PASSWORD;
delete process.env.EXCAVAGUARD_SESSION_SECRET;
const A = process.env.EXCAVAGUARD_PROJECT_ID;
const B = '22222222-2222-4222-8222-222222222222';
const library = await import('@/server/evidence/project-standard-library');
const route = await import('@/app/api/project-standards/route');
const { runJudgement } = await import('@/server/skills/evaluate-thresholds/runner');
const { executeAgentRun } = await import('@/server/agents/executor');
const { validateProjectStandardReferences } = await import('@/server/agents/project-standard-review');
const metadata = { standard_name: '合成监测规则（仅测试，非真实标准）', standard_version: 'TEST/T 999-2026',
  region: '测试地区', applicability: '合成测试基坑监测，不用于工程', confirmed: true };
const content = '5.1.1 基坑监测应核查水平位移和沉降监测结果，出现报警时应复测并核对监测日报。\n5.1.2 监测日报应包含异常情况和巡视记录。';
const file = () => new File([content], 'test-standard.txt');
const query = { query: '基坑监测 水平位移 预警 复测 监测日报 巡视', top_k: 4 };
let doc;
after(() => rmSync(root, { recursive: true, force: true }));

test('empty project has no supplement and creates no shared database', async () => {
  assert.deepEqual(await library.listProjectStandards(A), []);
  assert.equal(existsSync(join(root, 'project-standards', A)), false);
});
test('upload indexes original clauses and normalizes version', async () => {
  doc = await library.uploadProjectStandard(A, file(), metadata);
  assert.equal(doc.standard_version, 'TEST/T999-2026');
  assert.equal(doc.project_id, A); assert.ok(doc.chunk_count >= 2);
  const hits = await new library.ProjectStandardRetriever(A, [doc]).search(query);
  assert.ok(hits.length); assert.equal(hits[0].provider, 'project');
  assert.ok(hits.every(h => h.metadata.project_id === A && h.metadata.content_sha256 === doc.sha256));
  assert.ok(hits.some(h => h.metadata.clause === '5.1.1' && h.text.includes('出现报警时应复测')));
});
test('same upload is idempotent', async () => {
  const again = await library.uploadProjectStandard(A, file(), metadata);
  assert.equal(again.document_id, doc.document_id); assert.equal((await library.listProjectStandards(A)).length, 1);
});
test('same-version replacement preserves frozen original while only one source stays enabled', async () => {
  const updated = await library.uploadProjectStandard(A, new File([content + '\n5.1.3 监测数据应记录上传来源。'], 'updated.txt'), metadata);
  assert.notEqual(updated.document_id, doc.document_id);
  assert.deepEqual((await library.selectProjectStandards(A)).map(d => d.document_id), [updated.document_id]);
  assert.ok((await new library.ProjectStandardRetriever(A, [doc]).search(query)).length);
  await library.setProjectStandardActive(A, doc.document_id, true);
  assert.deepEqual((await library.selectProjectStandards(A)).map(d => d.document_id), [doc.document_id]);
});
test('project B cannot list, select, search or disable A documents', async () => {
  assert.deepEqual(await library.listProjectStandards(B), []);
  await assert.rejects(library.selectProjectStandards(B, [doc.document_id]), /当前项目/);
  await assert.rejects(library.setProjectStandardActive(B, doc.document_id, false), /当前项目/);
  assert.throws(() => new library.ProjectStandardRetriever(B, [doc]), /SCOPE_MISMATCH/);
  const same = await library.uploadProjectStandard(B, file(), metadata);
  assert.notEqual(same.document_id, doc.document_id);
  assert.equal((await library.listProjectStandards(A)).filter(d => d.active).length, 1);
});
test('version and region filters prevent unrelated hits', async () => {
  const retriever = new library.ProjectStandardRetriever(A, [doc]);
  assert.deepEqual(await retriever.search({ ...query, filters: { standard_versions: ['UNRELATED'] } }), []);
  assert.deepEqual(await retriever.search({ ...query, filters: { region: '其他地区' } }), []);
  assert.deepEqual(await retriever.search({ query: 'abcdefghzzzz' }), []);
});
test('disabled affects future runs but immutable selected revision remains retrievable', async () => {
  await library.setProjectStandardActive(A, doc.document_id, false);
  assert.deepEqual(await library.selectProjectStandards(A), []);
  await assert.rejects(library.selectProjectStandards(A, [doc.document_id]), /停用/);
  const frozen = await library.selectProjectStandards(A, [doc.document_id], false);
  assert.ok((await new library.ProjectStandardRetriever(A, frozen).search(query)).length);
  await library.setProjectStandardActive(A, doc.document_id, true);
});
test('reject unconfirmed, empty, unsupported and fake PDF files', async () => {
  await assert.rejects(library.uploadProjectStandard(A, file(), { ...metadata, confirmed: false }), /确认/);
  await assert.rejects(library.uploadProjectStandard(A, new File([], 'empty.txt'), metadata), /不能为空/);
  await assert.rejects(library.uploadProjectStandard(A, new File([content], 'x.exe'), metadata), /PDF/);
  await assert.rejects(library.uploadProjectStandard(A, new File([content], 'x.pdf'), metadata), /不是 PDF/);
});
test('combined retrieval queries both libraries; same-version project source stays project-only', async () => {
  let calls = 0;
  const shared = { provider: 'local', search: async () => { calls++; return []; } };
  const retriever = new library.CombinedStandardRetriever(shared, new library.ProjectStandardRetriever(A, [doc]));
  assert.ok((await retriever.search(query)).length); assert.equal(calls, 1);
  assert.ok((await retriever.search({ ...query, filters: { standard_versions: [doc.standard_version] } })).length);
  assert.equal(calls, 1);
});
test('upload API checks access and validates multipart metadata', async () => {
  const form = new FormData(); form.set('file', file());
  for (const [key, value] of Object.entries(metadata)) form.set(key, String(value));
  const response = await route.POST(new Request('http://localhost/api/project-standards', { method: 'POST', body: form }));
  assert.equal(response.status, 201, await response.clone().text());
  assert.equal((await response.json()).document.document_id, doc.document_id);
  const forbidden = await route.GET(new Request('http://localhost/api/project-standards', { headers: { origin: 'https://untrusted.example' } }));
  assert.equal(forbidden.status, 403);
});
test('AI prose cannot silently ignore retrieved project requirements', async () => {
  const hits = await new library.ProjectStandardRetriever(A, [doc]).search(query);
  const paragraph = { text: '需核对适用范围。', evidence_ids: [] };
  const narrative = { work_condition: paragraph, analysis: [paragraph], recommendations: [paragraph], limitations: [paragraph], appendix_analysis: [] };
  assert.throws(() => validateProjectStandardReferences(narrative, hits), /REFERENCE_REQUIRED/);
  validateProjectStandardReferences({ ...narrative, recommendations: [{ ...paragraph, evidence_ids: [hits[0].id] }] }, hits);
});

async function actualReport(documents) {
  const records = [0, 12, 25, 40].map((value, i) => ({ point_id: 'SIMULATED-P-01',
    metric_key: 'wall_top_horizontal_displacement', timestamp: `2026-10-0${i + 1}`, value, unit: 'mm', data_origin: 'simulated' }));
  const envelope = await runJudgement({ records, reportDate: '2026-10-04',
    context: { safety_level: '一级', support_type: '地下连续墙', excavation_depth_m: 20 }, project: { name: '项目补充规范_纯合成监测测试' } });
  const engineBefore = JSON.stringify(envelope.result);
  const result = await executeAgentRun({ enginePayload: envelope.result, reportMode: 'template',
    projectStandards: { project_id: A, documents } });
  assert.equal(result.terminalAction.reason_code, 'AUDIT_PASSED', JSON.stringify(result.terminalAction));
  assert.equal(JSON.stringify(result.state.engine_snapshot.payload), engineBefore);
  const evidence = result.state.evidence_snapshot.artifact.payload;
  assert.ok(evidence.evidence.some(e => e.provider === 'project'));
  assert.ok(evidence.coverage.completed);
  const draft = result.state.report_draft;
  assert.equal(draft.artifacts.length, 3);
  const workbook = draft.artifacts.find(a => a.kind === 'workbook');
  assert.ok(workbook.sheets.includes('项目补充要求核查'));
  const markdown = readFileSync(resolve(draft.artifacts.find(a => a.kind === 'cover_markdown').relative_path), 'utf8');
  assert.ok(markdown.includes(documents[0].standard_name));
  assert.ok(markdown.includes('本工程补充规范'));
  return result;
}
test('real render and artifact audit include project requirements without changing engine facts', async () => {
  const result = await actualReport([doc]);
  for (const artifact of result.state.report_draft.artifacts) rmSync(dirname(resolve(artifact.relative_path)), { recursive: true, force: true });
});
test('AI three-role orchestration consumes actual project retrieval and keeps citations through audit', async () => {
  const engine = await runJudgement({ records: [0, 15].map((value, i) => ({ point_id: 'SIMULATED-ONLY',
    metric_key: 'wall_top_horizontal_displacement', timestamp: `2026-10-0${i + 1}`, value, unit: 'mm', data_origin: 'simulated' })),
    reportDate: '2026-10-02', context: { safety_level: '一级', support_type: '地下连续墙', excavation_depth_m: 20 } });
  const roles = [];
  const result = await executeAgentRun({ enginePayload: engine.result, reportMode: 'ai', projectStandards: { project_id: A, documents: [doc] } }, {
    retrieve: async request => ({ status: 'abstained', code: 'EVIDENCE_NOT_FOUND', message: 'Test shared corpus is empty', evidence: [], notice: 'test stub',
      trace: { provider: 'local', query: request.query, filters: request.filters ?? { effective_status: 'active' }, limit: request.limit ?? 3, hit_count: 0, evidence_ids: [] } }),
    model: async request => {
      roles.push(request.role);
      let object;
      if (request.role === 'supervisor') object = { focus_indices: [0], evidence_topics: request.context.evidence_topics };
      else if (request.role === 'audit') object = { issues: [] };
      else {
        const evidence = request.context.evidence.evidence.filter(e => e.provider === 'project');
        assert.ok(evidence.length, 'Actual project database hits must reach report model');
        const paragraph = { text: '应结合本工程适用条件核对监测日报及复测要求，执行情况需工程师确认。', evidence_ids: [evidence[0].id] };
        object = { work_condition: { text: '未提供现场工况，需人工复核。', evidence_ids: [] }, analysis: [paragraph],
          recommendations: [paragraph], limitations: [{ text: '规范适用性须工程师复核。', evidence_ids: [] }],
          appendix_analysis: request.context.forms.map(form => ({ form, analysis: paragraph, recommendation: paragraph })) };
      }
      return { object, model: 'test-stub-not-live-LLM', usage: { input_tokens: 0, output_tokens: 0 } };
    },
  });
  assert.equal(result.terminalAction.reason_code, 'AUDIT_PASSED', JSON.stringify(result.terminalAction));
  assert.deepEqual(roles, ['supervisor', 'report-delivery', 'audit']);
  assert.ok(result.state.report_draft.citations.length);
  assert.equal(result.state.evidence_snapshot.artifact.payload.coverage.catalogue_count, 30);
  for (const artifact of result.state.report_draft.artifacts) rmSync(dirname(resolve(artifact.relative_path)), { recursive: true, force: true });
});
test('create-run API freezes supplement selection and rejects cross-project IDs', async () => {
  const { saveFile } = await import('@/server/storage/monitoring-file-store');
  const { POST } = await import('@/app/api/runs/route');
  const stored = await saveFile({ kind: 'monitoring', projectId: A, originalName: 'synthetic.csv', mediaType: 'text/csv',
    bytes: new TextEncoder().encode('point_id,timestamp,metric_key,value,unit\nSIMULATED-P-01,2026-10-01,wall_top_horizontal_displacement,0,mm\nSIMULATED-P-01,2026-10-02,wall_top_horizontal_displacement,12,mm\n') });
  const input = { project_id: A, monitoring_file_id: stored.file_id, report_date: '2026-10-02',
    context: { safety_level: '一级', support_type: '地下连续墙', excavation_depth_m: 20 } };
  const response = await POST(new Request('http://localhost/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) }));
  assert.equal(response.status, 200, await response.clone().text());
  const value = await response.json();
  assert.deepEqual(value.record.request.project_standard_ids, [doc.document_id]);
  assert.equal(value.record.result.project_standards[0].sha256, doc.sha256);
  const foreign = (await library.listProjectStandards(B))[0];
  const wrong = await POST(new Request('http://localhost/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...input, project_standard_ids: [foreign.document_id] }) }));
  assert.equal(wrong.status, 400);
});

const actualPath = process.env.EXCAVAGUARD_TEST_STANDARD_PDF;
test('special-font PDF is rejected instead of indexing unreadable glyph names', { skip: !process.env.EXCAVAGUARD_TEST_UNREADABLE_PDF }, async () => {
  const bytes = readFileSync(resolve(process.env.EXCAVAGUARD_TEST_UNREADABLE_PDF));
  await assert.rejects(library.uploadProjectStandard(A, new File([bytes], 'unreadable.pdf'), metadata), /字体编码|OCR/);
});
test('uploaded real local standard PDF enters final daily report and classification workbook', { skip: !actualPath }, async () => {
  const path = resolve(actualPath);
  const actual = await library.uploadProjectStandard(A, new File([readFileSync(path)], 'actual-standard.pdf'), {
    standard_name: process.env.EXCAVAGUARD_TEST_STANDARD_NAME || '建筑基坑工程技术规程',
    standard_version: process.env.EXCAVAGUARD_TEST_STANDARD_CODE || 'DB33/T1096-2014',
    region: '浙江省', applicability: '仅合成测试基坑监测；正式工程效力与适用性另行核验', confirmed: true,
  });
  assert.ok(actual.page_count > 10); assert.ok(actual.chunk_count > 10);
  const result = await actualReport([actual]);
  const out = resolve('../process_file/项目补充规范验收', actual.standard_version.replaceAll('/', '_')); mkdirSync(out, { recursive: true });
  for (const artifact of result.state.report_draft.artifacts) copyFileSync(resolve(artifact.relative_path), join(out, artifact.file_name));
  writeFileSync(join(out, '验收结果.json'), JSON.stringify(result, null, 2));
  console.info(JSON.stringify({ actual: actual.standard_name, pages: actual.page_count, chunks: actual.chunk_count,
    matches: result.state.evidence_snapshot.artifact.payload.evidence.length, audit: result.state.audit_result.valid, output: out }));
  for (const artifact of result.state.report_draft.artifacts) rmSync(dirname(resolve(artifact.relative_path)), { recursive: true, force: true });
});
