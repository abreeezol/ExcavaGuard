"""Verify repository-distributed synthetic inputs without LLM, accounts or RAG."""
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'final_test/tunnel-7day-10min/inputs'
sys.path.insert(0,str(ROOT/'确定性计算层/pipeline/stage1_data_preparation'))
from file_reader import read_monitoring_file


def main():
    manifest=json.loads((BASE/'文件清单.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        path=BASE/item['file']
        if path.stat().st_size!=item['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('输入文件清单不一致：'+item['file'])
    rows,report=read_monitoring_file(BASE/'SIMULATED_隧道监测_7天_10分钟_多工作表.xlsx')
    csv_rows,csv_report=read_monitoring_file(BASE/'SIMULATED_隧道监测_7天_10分钟_等价长表.csv')
    if not report['ok'] or not csv_report['ok']:raise ValueError('模拟主数据解析失败')
    def key(row):return (row['point_id'],row['timestamp'],row['metric'],float(row['value']),row['unit'],row['data_origin'])
    split_rows=[]
    for path in sorted((BASE/'separate-files').glob('*.xlsx')):
        part,parsed=read_monitoring_file(path)
        if not parsed['ok'] or len(part)!=6048:raise ValueError('分文件解析异常：'+path.name)
        split_rows.extend(part)
    if len(rows)!=24192 or sorted(map(key,rows))!=sorted(map(key,csv_rows)) or sorted(map(key,rows))!=sorted(map(key,split_rows)):
        raise ValueError('XLSX、CSV及四文件输入不等价')
    groups=defaultdict(list)
    for row in rows:
        if row['data_origin']!='simulated':raise ValueError('缺少模拟标记')
        meta=row['source_metadata']
        if not all(meta.get(field) for field in ('source_dataset','source_sheet','source_row')):raise ValueError('来源元数据缺失')
        groups[(row['point_id'],row['metric'])].append(datetime.fromisoformat(row['timestamp']))
    if len(groups)!=24:raise ValueError('通道数异常')
    for values in groups.values():
        values.sort()
        if len(values)!=1008 or len(set(values))!=1008 or any((b-a).total_seconds()!=600 for a,b in zip(values,values[1:])):
            raise ValueError('采样频率或时刻数异常')
    result={'passed':True,'input_files':len(manifest['files']),'records':len(rows),'channels':len(groups),
        'samples_per_channel':1008,'interval_minutes':10,'xlsx_csv_four_files_equivalent':True,'manifest_verified':True}
    target=ROOT/'var/acceptance/tunnel-7day-10min';target.mkdir(parents=True,exist_ok=True)
    (target/'数据完整性核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
