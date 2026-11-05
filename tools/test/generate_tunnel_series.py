"""Reproducible synthetic fixtures; values and controls are NOT normative."""
import csv,json,hashlib
from pathlib import Path
from datetime import datetime,timedelta
root=Path(__file__).resolve().parents[2]/'测试数据/隧道模拟_2026-11-01至14'
root.mkdir(parents=True,exist_ok=True)
metrics=['ground_settlement','building_settlement','crown_settlement','tunnel_convergence']
controls={m:dict(source='SIMULATED测试控制值，非规范要求',confirmed=True,cumulative_limit_mm=20,rate_limit_mm_per_day=4,value_semantics='cumulative_displacement' if m=='tunnel_convergence' else 'cumulative_settlement') for m in metrics}
ctx=dict(tunnel_system='rail',construction_method='mining',project_stage='construction',special_condition='none',metric_controls=controls)
(root/'工程参数_SIMULATED.json').write_text(json.dumps(ctx,ensure_ascii=False,indent=2)+'\n')
header=['point_id','timestamp','metric_key','value','unit','data_origin'];allrows=[];manifest=[]
for day in range(14):
 rows=[]
 for hour in range(0,24,3):
  n=day*8+hour//3
  for mi,m in enumerate(metrics):
   for p in range(6):
    # 24 channels: stable, gradual crossing, burst, reverse, missing history, plateau.
    v=[1+n*.02,1+n*.25,1+n*.03+(8 if n>=40 else 0),-1-n*.02,2+n*.02,min(22,1+n*.4)][p]
    unit='cm' if p==5 else 'mm';v=v/10 if unit=='cm' else v
    rows.append([f'SIM-T{mi+1}-P{p+1}',(datetime(2026,11,1)+timedelta(days=day,hours=hour)).isoformat(' '),m,round(v,6),unit,'simulated'])
 date=(datetime(2026,11,1)+timedelta(days=day)).date().isoformat();path=root/f'SIMULATED_隧道监测_{date}.csv'
 with path.open('w',newline='',encoding='utf-8-sig') as f:w=csv.writer(f);w.writerow(header);w.writerows(rows)
 allrows+=rows;manifest.append(dict(file=path.name,records=len(rows),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
with (root/'SIMULATED_隧道监测_2026-11-01至14_合并.csv').open('w',newline='',encoding='utf-8-sig') as f:w=csv.writer(f);w.writerow(header);w.writerows(allrows)
(root/'数据清单.json').write_text(json.dumps(dict(simulated=True,days=14,channels=24,sampling_hours=3,records=len(allrows),files=manifest),ensure_ascii=False,indent=2)+'\n')
(root/'README.md').write_text('''# 隧道模拟时序测试包

全部为人工构造数据与测试控制值，不是真实工程数据或规范默认值。14天、24通道（四测项各6点）、每3小时采样，每日192条，共2688条。

上传时选择“逐日文件”或“合并文件”其中一种，不能重复上传同一批观测。工程配置使用同目录工程参数；工法为轨道矿山法。所有测项测试累计限值20mm、速率4mm/d。

## 场景与预期

每测项P1稳定，P2逐步累计越限，P3在11月6日00:00突增且速率预警，P4反向变形待核，P5稳定，P6以cm输入并达到累计限值。首日首条无前值，配置速率控制时应披露缺项。11月14日日报应仅含当日192条；前日历史保留用于首条速率计算。周报分别覆盖11月1日至7日、8日至14日，每周1344条。周报应保留周期内突增与持续超限，不能只看期末数值。未上传工况/巡视，不得写“巡视正常”，不能据突增自行认定施工原因。

P5作为无突变对照组，缺失历史由首日首条和测试中剔除前史验证。所有数值可由tools/test/generate_tunnel_series.py重现。

报告输出见outputs，生成方式见tests/tunnel-series.test.ts。默认使用模板模式验证确定性计算及文件审计，不代表已做真实模型语义审查或工程师专业验收。
''')
print(root,len(allrows))
