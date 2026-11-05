"""Independent SIMULATED fixture audit. Production professional audit is not supplied."""
import json
from pathlib import Path
import sys
from openpyxl import load_workbook
req=json.load(sys.stdin)
root=Path(__file__).resolve().parents[3]
original=req['daily_report_input']['items']
artifact=next(a for a in req['artifacts'] if a['kind']=='workbook')
wb=load_workbook(root/artifact['relative_path'],data_only=True)
values=list(wb['M_验证测量'].values)[1:]
valid=req['report_payload']['rows']==original and values==[(r['point_id'],r['current']) for r in original]
print(json.dumps({'ok':True,'result':{'valid':valid,'checks':[{'name':'SIMULATED_independent_values','valid':valid}],'issues':[] if valid else [{'code':'SIMULATED_VALUE_MISMATCH','severity':'error','blocking':True,'responsibility':'report-delivery','path':'rows','message':'测试值不一致'}]}}))
