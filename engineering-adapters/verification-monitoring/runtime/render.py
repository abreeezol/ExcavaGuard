"""SIMULATED non-pit renderer used only to exercise the common report pipeline."""
import hashlib
import json
from pathlib import Path
import sys
from openpyxl import Workbook
req = json.load(sys.stdin)
root = Path(__file__).resolve().parents[3]
target = Path(req['artifact_output_dir']).resolve()
target.relative_to(root / 'var' / 'report-artifacts')
target.mkdir(parents=True, exist_ok=False)
rows = req['daily_report_input']['items']
wb = Workbook(); ws = wb.active; ws.title = 'M_验证测量'
ws.append(['SIMULATED_ONLY', 'value'])
for row in rows: ws.append([row['point_id'], row['current']])
workbook = target / 'SIMULATED.xlsx'; wb.save(workbook)
artifacts=[]
for kind,name,media in [('workbook','SIMULATED.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),('cover_markdown','SIMULATED_封面.md','text/markdown'),('appendices_markdown','SIMULATED_附表.md','text/markdown')]:
    path=target/name
    if kind != 'workbook': path.write_text('SIMULATED_ONLY：仅接口测试，非工程报告。\n'+json.dumps(rows,ensure_ascii=False),encoding='utf-8')
    data=path.read_bytes()
    artifacts.append({'kind':kind,'file_name':name,'relative_path':path.relative_to(root).as_posix(),'media_type':media,'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data),'sheets':['M_验证测量'] if kind=='workbook' else []})
print(json.dumps({'ok':True,'result':{'report_payload':{'simulated_only':True,'rows':rows},'fact_bindings':[],'artifact_bindings':[],'citations':[],'artifacts':artifacts,'template_version':req['template_version'],'review_required':True}},ensure_ascii=False))
