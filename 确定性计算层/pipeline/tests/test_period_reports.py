"""Period regressions with hand-verifiable values and real Python report artifacts."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "确定性计算层" / "pipeline"
sys.path.insert(0, str(PIPELINE))
from period_reports import build_period_report_input, cutoff_records, period_statistics, validate_period, validate_period_payload
from orchestrator import run_pipeline
from risk_identifier import ProjectContext
sys.path.insert(0, str(ROOT / "确定性计算层" / "tools"))
from validate_daily_report_input import validate

CTX = ProjectContext(safety_level="一级", support_type="地下连续墙", excavation_depth_m=20)

def records():
    return [{"point_id": "W-01", "metric_key": "wall_top_horizontal_displacement",
             "timestamp": f"2026-10-{day:02d}", "value": value, "unit": "mm", "data_origin": "simulated"}
            for day, value in [(1, 0), (2, 5), (3, 12), (4, 22), (5, 35), (6, 52), (7, 60), (8, 62)]]

def payload(start="2026-10-02", end="2026-10-08", kind="weekly", rows=None, ctx=CTX):
    result = run_pipeline(cutoff_records(rows if rows is not None else records(), end), ctx)
    return build_period_report_input(result, {"type": kind, "start_date": start, "end_date": end},
                                     project={"name": "SIMULATED_周期验证", "monitoring_unit": "测试单位"})

class PeriodFactsTests(unittest.TestCase):
    def test_history_preserved_and_no_future(self):
        p = payload()
        self.assertEqual(p['schema'], 'excavaguard.period_report_input/v1')
        self.assertEqual(p['period']['calendar_days'], 7)
        self.assertEqual(p['period']['observation_count'], 7)
        self.assertEqual(p['period']['channels'][0]['first_current'], 5)
        self.assertEqual(p['period']['daily_items'][0]['cumulative'], 5)
        self.assertEqual(p['period']['daily_items'][0]['baseline'], 0)
        self.assertTrue(p['period']['recurring_warnings'])
        self.assertEqual(validate(p), [])
        future = records() + [{**records()[-1], 'timestamp': '2026-10-20', 'value': 99999}]
        self.assertEqual(payload(rows=future), p)

    def test_missing_end_and_interior_day(self):
        rows = [r for r in records() if r['timestamp'] not in ('2026-10-04','2026-10-08')]
        p = payload(rows=rows)
        self.assertEqual(p['period']['missing_dates'], ['2026-10-04','2026-10-08'])
        self.assertEqual(p['period']['observed_days'], 5)
        self.assertEqual(p['period']['channels'][0]['missing_dates'], ['2026-10-04','2026-10-08'])
        self.assertEqual(validate(p), [])

    def test_missing_conditions_abstain_not_safe(self):
        p = payload(rows=[{**r, 'value': .01 * i} for i,r in enumerate(records())],
                    ctx=ProjectContext(safety_level='一级',support_type='地下连续墙',excavation_depth_m=None))
        self.assertGreater(p['period']['unknown_observation_count'],0)
        self.assertTrue(p['review_queue'])
        self.assertFalse(p['period']['recurring_warnings'])

    def test_distinct_days_not_samples_and_metric_separation(self):
        rows = [dict(payload()['period']['daily_items'][0], timestamp='2026-10-02T08:00:00', risk_level='预警'),
                dict(payload()['period']['daily_items'][0], timestamp='2026-10-02T09:00:00', risk_level='报警'),
                dict(payload()['period']['daily_items'][0], timestamp='2026-10-03', risk_level='正常', metric_key='other')]
        stats, reps = period_statistics(rows, {'type':'custom','start_date':'2026-10-02','end_date':'2026-10-03'})
        self.assertEqual(stats['channel_count'], 2)
        self.assertEqual(stats['warning_point_days'], 1)
        self.assertEqual(stats['recurring_warnings'], [])
        self.assertEqual(len(reps),2)

    def test_consecutive_warning_breaks_on_gap(self):
        base = payload()['period']['daily_items'][0]
        rows = [dict(base,timestamp=f'2026-10-{d:02}',risk_level='预警') for d in (2,3,5,7)]
        stats,_ = period_statistics(rows, {'type':'custom','start_date':'2026-10-02','end_date':'2026-10-07'})
        self.assertEqual(stats['channels'][0]['warning_days'],4)
        self.assertEqual(stats['channels'][0]['max_consecutive_warning_days'],2)

    def test_leap_month_and_invalid_ranges(self):
        self.assertEqual(len(validate_period({'type':'monthly','start_date':'2024-02-01','end_date':'2024-02-29'})),29)
        for spec in [
            {'type':'weekly','start_date':'2026-10-01','end_date':'2026-10-03'},
            {'type':'monthly','start_date':'2026-02-01','end_date':'2026-02-29'},
            {'type':'monthly','start_date':'2026-10-02','end_date':'2026-10-31'},
            {'type':'custom','start_date':'2026-10-03','end_date':'2026-10-01'},
            {'type':'custom','start_date':'2024-01-01','end_date':'2026-01-01'},
        ]:
            with self.subTest(spec=spec), self.assertRaises(ValueError): validate_period(spec)

    def test_empty_period_rejected(self):
        with self.assertRaises(ValueError): payload('2026-11-01','2026-11-07')

    def test_timezone_and_invalid_timestamp(self):
        r = [{'timestamp':'2026-10-01T18:00:00Z','value':1}]
        self.assertEqual(cutoff_records(r,'2026-10-01'),[])
        self.assertTrue(cutoff_records(r,'2026-10-02')[0]['timestamp'].startswith('2026-10-02'))
        with self.assertRaises(ValueError): cutoff_records([{'timestamp':'nonsense'}],'2026-10-02')

    def test_summary_and_source_hash_tampering(self):
        original = payload()
        for change in ('warning_days','content_hash','summary'):
            p=copy.deepcopy(original)
            if change=='warning_days': p['period']['channels'][0]['warning_days']=99
            elif change=='content_hash': p['period']['daily_summaries'][0]['content_hash']='a'*64
            else: p['summary']['total']=99
            self.assertTrue(validate_period_payload(p))

class PeriodArtifactTests(unittest.TestCase):
    def call(self, skill, script, body):
        process=subprocess.run([sys.executable,str(ROOT/'skills'/skill/'scripts'/script)],
                               input=json.dumps(body,ensure_ascii=False),text=True,capture_output=True,cwd=ROOT)
        self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        return json.loads(process.stdout)['result']

    def test_render_audit_and_changed_statistic(self):
        p=payload(); uid=str(uuid4()); folder=ROOT/'var/report-artifacts'/uid
        try:
            rendered=self.call('render-daily-report','render_daily_report.py',{
                'daily_report_input':p,'artifact_id':uid,'artifact_output_dir':str(folder)})
            self.assertIn('监测周报',rendered['report_payload']['title'])
            self.assertIn('周期最严重原观测',rendered['report_payload']['markdown'])
            book=next(a for a in rendered['artifacts'] if a['kind']=='workbook')
            self.assertIn('周期统计',book['sheets']); self.assertIn('每日变化',book['sheets'])
            self.assertIn('周期逐日明细',book['sheets'])
            audit_req={'daily_report_input':p,'report_payload':rendered['report_payload'],'template_version':rendered['template_version'],
                       **{k:rendered[k] for k in ('fact_bindings','artifacts','artifact_bindings','citations')}}
            audit=self.call('validate-report','validate_report.py',audit_req)
            self.assertTrue(audit['valid'],str(audit['issues']))
            import openpyxl
            path=ROOT/book['relative_path']; wb=openpyxl.load_workbook(path)
            wb['周期统计']['D3']=999; wb.save(path); wb.close()
            # Even if a file's descriptor hash is refreshed, semantic cell binding must fail.
            book['sha256']=hashlib.sha256(path.read_bytes()).hexdigest(); book['size_bytes']=path.stat().st_size
            audit=self.call('validate-report','validate_report.py',audit_req)
            self.assertFalse(audit['valid'])
            self.assertTrue(any(x['code']=='WORKBOOK_CELL_MISMATCH' for x in audit['issues']))
        finally:
            shutil.rmtree(folder,ignore_errors=True)

if __name__=='__main__': unittest.main(verbosity=2)
