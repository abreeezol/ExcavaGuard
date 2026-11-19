"""Deterministic 7-day, 10-minute tunnel fixtures. No normative control values."""
import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'final_test/tunnel-7day-10min/inputs'
START = datetime(2026, 11, 11)
COUNT = 7 * 24 * 6
METRICS = [('ground_settlement', '地表沉降', 20), ('building_settlement', '建筑沉降', 15),
           ('crown_settlement', '拱顶沉降', 25), ('tunnel_convergence', '净空收敛', 12)]
SCENARIOS = ['平稳变化', '累计逐渐超限', '短时速率超限后恢复', '反向变形待核', '厘米单位累计超限平台', '持续速率超限']
DATASET = 'SIMULATED_TUNNEL_7D_10MIN_20261118'
HEADER = ['point_id', 'timestamp', 'metric_key', 'value', 'unit', 'data_origin', 'source_metadata']


def value_mm(limit, scenario, n):
    rate_limit = limit * .2
    if scenario == 0:
        return limit * (.1 + .2 * n / (COUNT - 1))
    if scenario == 1:
        return limit * (.1 + 1.2 * n / (COUNT - 1))
    if scenario == 2:
        return limit * .2 + .0002 * n + (rate_limit / 144 * 3 if 360 <= n < 366 else 0)
    if scenario == 3:
        return -limit * .1 - .0005 * n
    if scenario == 4:
        return limit * 1.1
    return .1 * limit + rate_limit * 1.3 * n / 144


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    wb = Workbook(); wb.remove(wb.active)
    note = wb.create_sheet('数据说明')
    for line in ['全部为SIMULATED模拟数据，控制值仅为测试设置，并非规范限值。',
                 '时间：2026-11-11 00:00至2026-11-17 23:50，上海时区；每测点每10分钟观测。',
                 '四种监测类型分别存入四个数据sheet，每类型六个测点。',
                 'P1平稳；P2累计渐超；P3第361条速率突增、第367条恢复；P4反向待核；P5厘米平台；P6持续速率超限。',
                 '没有提供施工日志或巡视资料。异常挑战文件独立保存，不与主数据重复上传。',
                 '本文件保留人工构造的原始序列；原始采样间隔均为10分钟。']:
        note.append([line])
    context = {'tunnel_system':'rail', 'construction_method':'mining', 'project_stage':'construction',
               'special_condition':'none', 'metric_controls':{}}
    all_rows = []; expected = []; expected_records = []
    for mi, (metric, name, limit) in enumerate(METRICS):
        sheet = wb.create_sheet(name); sheet.append(HEADER)
        context['metric_controls'][metric] = {'source':f'SIMULATED_{name}测试方案_非规范要求', 'confirmed':True,
            'cumulative_limit_mm':limit, 'rate_limit_mm_per_day':limit*.2,
            'value_semantics':'cumulative_displacement' if metric=='tunnel_convergence' else 'cumulative_settlement'}
        for n in range(COUNT):
            timestamp = (START + timedelta(minutes=10*n)).isoformat(' ')
            for scenario in range(6):
                unit = 'cm' if scenario == 4 else 'mm'
                value = round(value_mm(limit, scenario, n) / (10 if unit=='cm' else 1), 9)
                point = f'SIM10-T{mi+1}-P{scenario+1}'
                row = [point, timestamp, metric, value, unit, 'simulated', json.dumps({
                    'source_dataset':DATASET, 'scenario':SCENARIOS[scenario]},ensure_ascii=False)]
                sheet.append(row); all_rows.append(row)
                current = value * (10 if unit=='cm' else 1)
                previous = round(value_mm(limit,scenario,n-1)/(10 if unit=='cm' else 1),9)*(10 if unit=='cm' else 1) if n else None
                change = current-previous if previous is not None else None
                rate = abs(change)*144 if change is not None else None
                exceeded = current>=limit or (rate is not None and rate>=limit*.2)
                risk = '预警' if exceeded else '未知' if scenario==3 or not n else '正常'
                expected_records.append({'point_id':point,'timestamp':timestamp,'metric_key':metric,'current':current,
                    'cumulative':current,'single_change':change,'rate':rate,'risk_level':risk,'needs_review':scenario==3 or not n})
        for scenario in range(6):
            expected.append({'point_id':f'SIM10-T{mi+1}-P{scenario+1}', 'metric_key':metric,
                'scenario':SCENARIOS[scenario], 'records':COUNT, 'final_cumulative_mm':round(value_mm(limit,scenario,COUNT-1),9),
                'expected_final_risk':'未知' if scenario==3 else '预警' if scenario in (1,4,5) else '正常'})
        sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
        for cell in sheet[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='244760')
        for col,width in [('A',23),('B',23),('C',25),('D',18),('E',12),('F',15),('G',70)]:sheet.column_dimensions[col].width=width
    workbook = DEST/'SIMULATED_隧道监测_7天_10分钟_多工作表.xlsx';wb.save(workbook)
    with (DEST/'SIMULATED_隧道监测_7天_10分钟_等价长表.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f,lineterminator="\n");writer.writerow(HEADER);writer.writerows(all_rows)
    with (DEST/'预期逐条结果_SIMULATED.jsonl').open('w') as f:
        for item in expected_records:f.write(json.dumps(item,ensure_ascii=False)+'\n')
    (DEST/'工程参数_SIMULATED.json').write_text(json.dumps(context,ensure_ascii=False,indent=2)+'\n')
    (DEST/'预期结果_SIMULATED.json').write_text(json.dumps({'dataset':DATASET,'days':7,'interval_minutes':10,'samples_per_channel':COUNT,
        'channels':24,'records':len(all_rows),'per_sheet_records':6048,'start':'2026-11-11 00:00:00','end':'2026-11-17 23:50:00',
        'spike_sample_index':360,'recovery_sample_index':366,'channels_expected':expected},ensure_ascii=False,indent=2)+'\n')
    # Negative fixtures deliberately isolated; do not turn bad data into a passing main dataset.
    for kind in ['重复观测','缺少单位列','后续工作表缺列']:
        bad=Workbook();bad.active.title='地表沉降';bad.active.append(HEADER);bad.active.append(all_rows[0])
        if kind=='重复观测':bad.active.append(all_rows[0])
        elif kind=='缺少单位列':bad.active.delete_cols(5)
        else:
            ws=bad.create_sheet('拱顶沉降');ws.append(['point_id','timestamp','metric_key','value']);ws.append(['SIM-BAD','2026-11-11 00:00:00','crown_settlement',1])
        bad.save(DEST/f'SIMULATED_挑战_{kind}.xlsx')
    split = DEST/'separate-files'; split.mkdir(exist_ok=True)
    for _, name, _ in METRICS:
        out=Workbook();out.active.title=name
        for row in wb[name].iter_rows(values_only=True):out.active.append(row)
        out.active.freeze_panes='A2';out.active.auto_filter.ref=out.active.dimensions
        out.save(split/f'SIMULATED_{name}.xlsx')
    files=[{'file':p.relative_to(DEST).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(DEST.rglob('*')) if p.is_file() and p.name.startswith(('SIMULATED_', '工程参数_SIMULATED', '预期')) and p.suffix in ('.xlsx','.csv','.json','.jsonl')]
    (DEST/'文件清单.json').write_text(json.dumps({'data_origin':'simulated','files':files},ensure_ascii=False,indent=2)+'\n')
    (DEST/'README.md').write_text('''# 七天十分钟隧道模拟数据

生成日期：2026-11-18。全部为人工构造的模拟数据，不是真实工程记录；每测项控制值仅为测试设置。

主文件：`SIMULATED_隧道监测_7天_10分钟_多工作表.xlsx`。首个sheet是说明，其余分别为地表沉降、建筑沉降、拱顶沉降、净空收敛；每类6点，每点1008条，合计24192条。时间从2026-11-11 00:00至11-17 23:50，每10分钟一次。另提供等价CSV用于核对；二者不可同时上传，避免重复观测。

P1平稳、P2累计渐超、P3短时速率超限后恢复、P4反向待核、P5厘米单位累计超限平台、P6持续速率超限。各测项使用不同累计/速率测试限值。首条没有前值，需按事实披露速率缺失。主文件没有缺测；错误场景在三个独立挑战文件中，不能混入主数据。

工程参数、预期结果和SHA256清单均在同目录。复现：`.venv/bin/python tools/test/generate_tunnel_10min.py`。数据包使用说明见上一级`README.md`；自动验收结果保存在仓库`var/acceptance/`；程序测试使用隔离工程，不修改真实账号。
''')
    print(json.dumps({'directory':str(DEST),'workbook':workbook.name,'records':len(all_rows),'bytes':workbook.stat().st_size},ensure_ascii=False))

if __name__ == '__main__':main()
