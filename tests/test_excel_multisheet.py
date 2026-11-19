"""All-sheet ingestion, rejection and original row provenance."""
import sys
import tempfile
import unittest
from pathlib import Path
from openpyxl import Workbook
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'确定性计算层/pipeline/stage1_data_preparation'))
from file_reader import read_monitoring_file

class ExcelSheets(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'SIMULATED.xlsx'

    def test_notes_first_and_all_data_sheets_with_original_rows(self):
        wb=Workbook();wb.active.title='数据说明';wb.active.append(['SIMULATED'])
        for name,point in [('地表沉降','A'),('拱顶沉降','B')]:
            ws=wb.create_sheet(name);ws.append(['point_id','timestamp','metric_key','value','unit','data_origin'])
            ws.append([None]*6);ws.append([point,'2026-11-11 00:00:00','crown_settlement',2,'mm','simulated'])
        wb.save(self.path)
        rows,report=read_monitoring_file(self.path)
        self.assertTrue(report['ok']);self.assertEqual(len(rows),2)
        self.assertEqual([r['source_metadata']['source_sheet'] for r in rows],['地表沉降','拱顶沉降'])
        self.assertEqual([r['source_metadata']['source_row'] for r in rows],[3,3])

    def test_invalid_later_sheet_rejects_whole_workbook(self):
        wb=Workbook();ws=wb.active;ws.title='有效数据'
        ws.append(['point_id','timestamp','metric','value','unit']);ws.append(['A','2026-11-11', '拱顶沉降',1,'mm'])
        wb.create_sheet('后续缺列').append(['point_id','value']);wb.save(self.path)
        rows,report=read_monitoring_file(self.path)
        self.assertFalse(report['ok']);self.assertEqual(rows,[])
        self.assertIn('后续缺列',' '.join(report['errors']))

    def test_two_wide_sheets_keep_channel_and_sheet_provenance(self):
        wb=Workbook();wb.remove(wb.active)
        for sheet,point in [('数据A','A-1'),('数据B','B-1')]:
            ws=wb.create_sheet(sheet);ws.append(['时间',f'地表沉降-{point}-累计值(mm)']);ws.append(['2026-11-11 00:00:00',2])
        wb.save(self.path);rows,report=read_monitoring_file(self.path)
        self.assertTrue(report['ok'],report);self.assertEqual(len(rows),2)
        self.assertEqual(report['channel_count'],2)
        self.assertEqual([r['source_metadata']['source_sheet'] for r in rows],['数据A','数据B'])

if __name__=='__main__':unittest.main()
