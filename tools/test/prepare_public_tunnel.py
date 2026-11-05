"""Lossless public DW ingestion for boundary validation, not engineering alarm evaluation."""
import csv,json,hashlib,collections
from pathlib import Path
repo=Path(__file__).resolve().parents[2];src=repo.parent/'sensors_public_dataset_v1.0.0/sensors_public_dataset';out=repo/'测试数据/隧道公开实测_脱敏v1';out.mkdir(parents=True,exist_ok=True)
for r in csv.DictReader((src/'FILE_MANIFEST.csv').open()):
 p=src/r['path']
 if p.stat().st_size!=int(r['bytes']) or hashlib.sha256(p.read_bytes()).hexdigest()!=r['sha256']:raise ValueError('来源清单校验失败：'+r['path'])
rows=list(csv.DictReader((src/'data/observations.csv').open()));counts=collections.Counter((r['sensor_id'],r['channel_id'],r['timestamp']) for r in rows)
clean=[];quarantine=[]
for line,r in enumerate(rows,2):
 if counts[(r['sensor_id'],r['channel_id'],r['timestamp'])]>1:quarantine.append(dict(source_line=line,**r));continue
 if r['sensor_type']!='DW':continue
 clean.append(dict(point_id=r['sensor_id']+'::'+r['channel_id'],timestamp=r['timestamp'],metric_key='public_dw_displacement_unclassified',value=r['engineering_value_signed'],unit=r['unit'],data_origin='real',source_metadata=json.dumps(dict(dataset_version='1.0.0',source_line=line,zone_id=r['zone_id'],section_id=r['section_id'],channel_id=r['channel_id'],quality_flag=r['quality_flag'],depth_m=r['depth_m'],date_shifted=True),ensure_ascii=False)))
with (out/'REAL_DW_2020-10-15至2022-08-30_未分类位移.csv').open('w',newline='',encoding='utf-8-sig') as f:w=csv.DictWriter(f,fieldnames=list(clean[0]));w.writeheader();w.writerows(clean)
(out/'重复观测隔离.json').write_text(json.dumps(quarantine,ensure_ascii=False,indent=2)+'\n')
(out/'核验清单.json').write_text(json.dumps(dict(source='用户提供的数据包，按包内说明为脱敏真实观测；本次未独立核验数据拥有者',original_records=len(rows),by_sensor_type=dict(collections.Counter(r['sensor_type'] for r in rows)),quarantined_records=len(quarantine),duplicate_keys=sum(n>1 for n in counts.values()),imported_dw_records=len(clean),channels=len({r['point_id'] for r in clean}),manifest_verified=True,original_observations_sha256=hashlib.sha256((src/'data/observations.csv').read_bytes()).hexdigest()),ensure_ascii=False,indent=2)+'\n')
(out/'README.md').write_text('''# 隧道公开脱敏观测：部分功能验证

来源为工作区sensors_public_dataset_v1.0.0，归属和真实性依包内README，本次未独立验证发布记录。原始数据保留不改动。按源文件清单逐项校验字节数和SHA256。

DW为多深度位移，现有说明不能证明其属于拱顶/地表/建筑沉降或净空收敛，因此保留未分类测项。不同深度分别保留独立通道。使用engineering_value_signed，不取绝对值，不重新归零；保留原单位、脱敏时间、质量标记和原行号。不读取daily_aligned的填充值为观测，不将训练集弱标签阈值当工程控制值。

源数据存在重复键，全部相关原行隔离到重复观测隔离.json，不任意挑选或平均。锚杆应力MPa及孔压kPa暂不适配，未混入位移CSV。

测试范围：原值和来源保真、通道隔离、日报2022-03-22、周报2022-03-16至22、稀疏缺测披露、未适配测项未知、模板报告及文件审计。日期经过统一偏移，不代表工程真实日历。测试中的轨道/矿山法分类只是软件执行配置，数据包没有证明真实工法；不能据此验证规范适用性。所有条目应未知且待核，不能据此评价报警准确率。

数据许可证依原包LICENSE-DATA.md为CC BY 4.0，引用信息保留于CITATION.cff；原包声明DOI 10.5281/zenodo.20768869，本次未联网核验。输出见outputs，复现脚本tools/test/prepare_public_tunnel.py，测试tests/tunnel-public-data.test.ts。
''')
print((out/'核验清单.json').read_text())
