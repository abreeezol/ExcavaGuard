"""Frozen evidence presentation and independent file-audit regression."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engineering-adapters/tunnel-monitoring/runtime'))
import core
sys.path.insert(0, str(ROOT / 'tools/knowledge'))
from clause_labels import clause_label
from openpyxl import load_workbook

class TunnelReportTemplate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'var/report-artifacts')
        self.addCleanup(self.temp.cleanup)
        self.payload = core.template()
        self.payload['project'] = {'name': 'SIMULATED模板验证', 'report_date': '2026-11-17'}
        row = self.payload['items'][0]
        row.update(point_id='SIM-T1', metric_name='拱顶沉降', timestamp='2026-11-17', current=2, cumulative=2, effective_standard={'source_label': '模拟批准方案'}, source_metadata={'source_file': 'SIMULATED.csv', 'source_line': 2})
        self.payload['summary'] = core.summary(self.payload['items'])
        self.req = {'daily_report_input': self.payload, 'template_version': 'tunnel-monitoring/v2',
                    'artifact_output_dir': str(Path(self.temp.name) / 'report'),
                    'standard_evidence': {'evidence': [{'id': 'test-source', 'provider': 'local',
                        'text': '模拟引用原文，仅验证来源展示。', 'metadata': {
                        'standard_name': '模拟隧道监测规范', 'standard_version': 'SIMULATED-2026',
                        'clause': '第七条', 'source_location': '模拟规范.pdf 第12页'}}],
                        'gaps': ['模拟待核缺口']},
                    'work_condition_analysis': {'narrative': {
                        'work_condition': {'text': '施工条件待核。', 'evidence_ids': []},
                        'analysis': [{'text': '应核对监测要求。', 'evidence_ids': ['test-source']}],
                        'recommendations': [], 'limitations': [], 'appendix_analysis': [
                            {'form': 'S', 'analysis': {'text': '分项要求待核。', 'evidence_ids': ['test-source']},
                             'recommendation': {'text': '请复核。', 'evidence_ids': []}}]}}}

    def render(self):
        draft = core.render(self.req)
        return {**self.req, **draft}

    def test_literal_ocr_headings_preserve_page_and_uncertainty(self):
        original = 'PDF第62页（候选，条款待核）'
        text = '9.2.2 监测要求\n表9.2.2-1\n累计值\n0.04%Ls\n正文参见8.1.2条'
        label = clause_label(text, original)
        self.assertIn('9.2.2、表9.2.2-1', label)
        self.assertIn(original, label)
        self.assertNotIn('8.1.2', label)
        self.assertEqual(clause_label('0.04%Ls\n无编号正文', original), original)
        self.assertEqual(clause_label(text, '已确认第七条'), '已确认第七条')

    def test_required_coverage_cannot_omit_a_standard(self):
        self.req['require_full_coverage'] = True
        catalog = __import__('json').loads((ROOT / 'engineering-adapters/tunnel-monitoring/catalog.json').read_text())
        entries = [{'standard_name':e['name'],'standard_version':e['code'],'effective_status':'active','status':'skipped_scope','retained_ids':[],'reason':'模拟覆盖结构验证'} for e in catalog['standards']]
        self.req['standard_evidence']['coverage'] = {'completed':True,'catalogue_count':16,'standards':entries[:-1]}
        with self.assertRaisesRegex(ValueError, 'STANDARD_COVERAGE_INCOMPLETE'):
            core.render(self.req)

    def test_required_coverage_cannot_reference_missing_evidence(self):
        self.req['require_full_coverage'] = True
        catalog = __import__('json').loads((ROOT / 'engineering-adapters/tunnel-monitoring/catalog.json').read_text())
        entries = [{'standard_name':e['name'],'standard_version':e['code'],'effective_status':'active','status':'skipped_scope','retained_ids':[],'reason':'模拟覆盖结构验证'} for e in catalog['standards']]
        entries[0].update(status='matched',retained_ids=['missing'])
        self.req['standard_evidence']['coverage'] = {'completed':True,'catalogue_count':16,'standards':entries}
        with self.assertRaisesRegex(ValueError, 'STANDARD_COVERAGE_MISMATCH'):
            core.render(self.req)

    def test_required_coverage_accepts_equivalent_standard_number_format(self):
        self.req['require_full_coverage'] = True
        catalog = __import__('json').loads((ROOT / 'engineering-adapters/tunnel-monitoring/catalog.json').read_text())
        entries = [{'standard_name':e['name'],'standard_version':e['code'].replace('-', '—') + ' ','effective_status':'active','status':'skipped_scope','retained_ids':[],'reason':'模拟覆盖结构验证'} for e in catalog['standards']]
        self.req['standard_evidence']['coverage'] = {'completed':True,'catalogue_count':16,'standards':entries}
        core.report_payload(self.req)

    def test_engineer_feedback_and_actual_before_after_are_audited(self):
        analysis = self.req['work_condition_analysis']
        analysis['engineer_feedback'] = {'parent_run_id':'SIMULATED-parent','parent_revision':2,'items':[{'feedback_id':'review','comment':'请明确该处是待核而非正常。'}], 'prior_narrative':{'analysis':[{'text':'旧版待补充说明。','evidence_ids':[]}]}}
        analysis['narrative']['feedback_responses'] = [{'feedback_id':'review','status':'addressed','response':{'text':'已补充待核说明。','evidence_ids':[]}}]
        req = self.render()
        self.assertTrue(core.audit(req)['valid'])
        workbook = next(ROOT / a['relative_path'] for a in req['artifacts'] if a['kind'] == 'workbook')
        wb=load_workbook(workbook)
        self.assertIn('工程师意见回应',wb.sheetnames);self.assertIn('修订前后对照',wb.sheetnames)
        self.assertEqual(wb['工程师意见回应']['B2'].value,'请明确该处是待核而非正常。')
        self.assertIn('原意见：请明确',core.markdown_for(req['report_payload'],self.payload))
        wb['工程师意见回应']['E2']='伪造已回应';wb.save(workbook)
        self.assertFalse(core.audit(req)['valid'])

    def test_cover_appendix_and_excel_keep_exact_clause_and_location(self):
        req = self.render()
        self.assertTrue(core.audit(req)['valid'])
        files = {a['kind']: ROOT / a['relative_path'] for a in req['artifacts']}
        cover = files['cover_markdown'].read_text()
        appendix = files['appendices_markdown'].read_text()
        for title in ['一、工况描述', '二、简要分析及判断性结论', '三、待复核事项', '四、规范核对依据', '五、签署']:
            self.assertIn(title, cover)
        for text in ['模拟隧道监测规范', 'SIMULATED-2026', '第七条', '第12页']:
            self.assertIn(text, cover)
            self.assertIn(text, appendix)
        self.assertNotEqual(cover, appendix)
        self.assertIn('模拟待核缺口', cover)
        wb = load_workbook(files['workbook'])
        self.assertEqual(wb.sheetnames[0], '报告说明')
        self.assertIn('第七条', wb['附表S分析']['A2'].value)

    def test_modified_clause_or_omitted_citation_is_rejected(self):
        req = self.render()
        workbook = next(ROOT / a['relative_path'] for a in req['artifacts'] if a['kind'] == 'workbook')
        wb = load_workbook(workbook)
        wb['规范证据']['C2'] = '篡改条款'
        wb.save(workbook)
        self.assertFalse(core.audit(req)['valid'])

    def test_omitted_citation_is_rejected(self):
        req = self.render()
        req['citations'] = []
        self.assertFalse(core.audit(req)['valid'])

    def test_changed_citation_path_is_rejected(self):
        req = self.render()
        req['citations'][0]['report_path'] = 'sections.narrative.recommendations.0'
        self.assertFalse(core.audit(req)['valid'])

    def test_changed_original_source_is_rejected(self):
        req = self.render()
        workbook = next(ROOT / a['relative_path'] for a in req['artifacts'] if a['kind'] == 'workbook')
        wb = load_workbook(workbook)
        wb['来源追溯']['D2'] = '伪造来源'
        wb.save(workbook)
        self.assertFalse(core.audit(req)['valid'])

    def test_unknown_evidence_id_rejected(self):
        self.req['work_condition_analysis']['narrative']['analysis'][0]['evidence_ids'] = ['not-frozen']
        with self.assertRaises(ValueError):
            core.render(self.req)

    def test_no_evidence_is_disclosed(self):
        self.req['standard_evidence'] = None
        self.req['work_condition_analysis'] = None
        req = self.render()
        self.assertTrue(core.audit(req)['valid'])
        self.assertIn('不代表没有相关要求', core.markdown_for(req['report_payload'], self.payload))

if __name__ == '__main__':
    unittest.main()
