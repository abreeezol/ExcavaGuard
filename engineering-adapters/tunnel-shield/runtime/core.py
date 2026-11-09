"""Shield surroundings settlement: deterministic calculations, confirmed project limits only."""
import json,sys,hashlib,math,statistics,re
from pathlib import Path
from datetime import datetime
from copy import deepcopy
from collections import Counter
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'确定性计算层/pipeline/stage1_data_preparation'))
sys.path.insert(0,str(ROOT/'确定性计算层/pipeline'))
from file_reader import read_monitoring_file
RULES=json.loads((Path(__file__).resolve().parents[1]/'rules.json').read_text(encoding='utf-8'))

def safe(v):return "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v
def stable(v):return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def digest(v):return hashlib.sha256(stable(v).encode()).hexdigest()
def dates(rows):return sorted({str(r.get('timestamp',''))[:10] for r in rows if len(str(r.get('timestamp','')))>=10})
def read(req):
 rows=req.get('records');reports=[]
 if rows is None:
  rows=[]
  paths=req.get('file_paths') or ([req.get('file_path')] if req.get('file_path') else [])
  for path in paths:
   records,report=read_monitoring_file(path)
   if not report.get('ok'):raise ValueError('输入表字段或格式不完整')
   rows.extend(records);reports.append(report)
 if not rows:raise ValueError('没有可用监测记录')
 if len(rows)>300000:raise ValueError('输入记录超过300000条')
 seen=set()
 for row in rows:
  key=(row.get('point_id'),row.get('metric_key',row.get('metric')),str(row.get('timestamp')))
  if key in seen:raise ValueError('跨文件或文件内重复观测，需先核对')
  seen.add(key)
 return rows,reports

def template():return deepcopy(json.loads((Path(__file__).resolve().parents[1]/'payload-template.json').read_text(encoding='utf-8')))
def summary(items):
 return {'total':len(items),'by_risk_level':dict(Counter(i['risk_level'] for i in items)),'by_problem_category':dict(Counter(i['problem_category'] for i in items)),
  'by_data_origin':dict(Counter(i['data_origin'] for i in items)),'abstain':dict(Counter(a for i in items for a in i['abstain'])),'overall_risk_level':'预警' if any(i['risk_level']=='预警' for i in items) else '未知' if any(i['risk_level']=='未知' for i in items) else '正常'}
def instant(t):
 text=str(t).replace(' ','T');d=datetime.fromisoformat(text)
 if d.tzinfo is None:from datetime import timezone,timedelta;d=d.replace(tzinfo=timezone(timedelta(hours=8)))
 return d.timestamp()/86400

def judge(req):
 opt=req.get('options') or {};raw,reports=read({**req,**opt});ctx=req['context'];end=(opt.get('report_period') or {}).get('end_date') or opt.get('report_date');items=[];groups={}
 for row in raw:
  if not isinstance(row.get('point_id'),str) or not row['point_id'].strip():raise ValueError('测点编号必须非空')
  if row.get('data_origin','real') not in ('real','simulated'):raise ValueError('数据来源标识非法')
  key=str(row.get('metric_key') or row.get('metric') or '')
  for metric,definition in RULES['metrics'].items():
   if key in definition['aliases']:key=metric;break
  row={**row,'metric_key':key}
  if end and str(row.get('timestamp',''))[:10]>end:continue
  groups.setdefault((row.get('point_id'),key),[]).append(row)
 base=template();prototype=deepcopy(base['items'][0])
 for (point,key),rows in sorted(groups.items(),key=lambda x:str(x[0])):
  rows.sort(key=lambda r:instant(r['timestamp']));prior=None;series=[]
  for row in rows:
   item=deepcopy(prototype);unit=row.get('unit');factor={'mm':1,'cm':10,'m':1000}.get(unit)
   value=float(row.get('value',row.get('current')))
   if not math.isfinite(value) or factor is None:raise ValueError('数值非有限或单位不支持；沉降支持mm/cm/m')
   current=value*factor;timestamp=str(row['timestamp']);t=instant(timestamp);cumulative=None;baseline=None;flags=[]
   if ctx['value_semantics']=='cumulative_settlement':baseline=0;cumulative=current;flags.append('INPUT_CUMULATIVE_DOWNWARD_POSITIVE')
   else:
    supplied=row.get('baseline_value',row.get('baseline'))
    if supplied is not None:
     baseline=float(supplied)*factor
     if not math.isfinite(baseline):raise ValueError('初始基准必须为有限数值')
     cumulative=baseline-current
   previous=prior[0] if prior else None;interval=t-prior[1] if prior else None
   if interval is not None and interval<=0:raise ValueError('相邻观测时间必须递增')
   change=(current-previous) if previous is not None else None
   if change is not None and ctx['value_semantics']=='elevation':change=-change
   rate=abs(change)/interval if change is not None else None
   series.append((t,cumulative))
   available=[(x,y) for x,y in series if y is not None]
   slope=None
   if len(available)>=3:
    mx=statistics.mean(x for x,y in available);my=statistics.mean(y for x,y in available);den=sum((x-mx)**2 for x,y in available)
    slope=sum((x-mx)*(y-my) for x,y in available)/den if den else None
   abstain=[];checks=[]
   if key not in RULES['metrics']:abstain.append('UNKNOWN_METRIC')
   if not ctx.get('control_values_confirmed') or not ctx.get('control_source'):abstain.append('MISSING_CONFIRMED_PROJECT_CRITERIA')
   else:
    for name,value,limit in [('cumulative',cumulative,ctx.get('cumulative_limit_mm')),('rate',rate,ctx.get('rate_limit_mm_per_day'))]:
     if limit is None:continue
     if value is None:abstain.append('MISSING_'+name.upper());continue
     if name=='cumulative' and value<0:abstain.append('UPLIFT_CONTROL_NOT_PROVIDED');continue
     checks.append({'type':name,'value':value,'limit':limit,'unit':'mm' if name=='cumulative' else 'mm/d','utilization':abs(value)/limit,'verdict':'预警' if abs(value)>=limit else '未触发','limit_basis':'工程师确认项目控制值；非规范统一阈值'})
    if not checks and not abstain:abstain.append('NO_CONFIRMED_LIMIT')
   exceed=any(c['utilization']>=1 for c in checks)
   risk='预警' if exceed and key in RULES['metrics'] else '未知' if abstain else '正常'
   source=ctx.get('control_source') or '项目控制要求未确认'
   metadata=row.get('source_metadata') or {}
   if isinstance(metadata,str):metadata=json.loads(metadata)
   metadata={**metadata,'units':{'current':'mm','cumulative':'mm','single_change':'mm','rate':'mm/d','slope':'mm/d'}}
   item.update(point_id=point,metric_key=key,metric_name=RULES['metrics'].get(key,{}).get('display_name',key),timestamp=timestamp,data_origin=row.get('data_origin','real'),current=current,unit='mm',baseline=baseline,previous=previous,interval_days=interval,cumulative=cumulative,single_change=change,rate=rate,slope=slope,risk_level=risk,problem_category='沉降监测待核' if risk=='未知' else '沉降监测',checks=checks,utilization=max((c['utilization'] for c in checks),default=None),abstain=abstain,abstain_reasons=abstain,flags=flags,needs_review=bool(abstain),rule_id='shield-project-settlement/v1',source_metadata=metadata,
    evidence={'standard':source,'clause':'项目批准控制要求','note':'RAG仅查证适用要求，不改变本项限值'},effective_standard={'origin':'project_confirmed' if ctx.get('control_values_confirmed') else 'unconfirmed','source_id':'PROJECT-CONTROL','source_label':source,'origin_display':'项目确认要求'})
   items.append(item);prior=(current,t)
 base['project']=opt.get('project') or {};base['project']['report_date']=end;base['items']=items
 if opt.get('report_period'):
  from period_reports import period_statistics,validate_period
  spec=opt['report_period'];validate_period(spec);rows=[i for i in items if spec['start_date']<=i['timestamp'][:10]<=spec['end_date']];stats,reps=period_statistics(rows,spec)
  base.update(schema='excavaguard.period_report_input/v1',items=reps,period={**stats,'daily_items':rows});base['contract']['schema_file']='确定性计算层/contracts/period_report_input.schema.json'
 elif end:base['items']=[i for i in items if i['timestamp'][:10]==end]
 if not base['items']:raise ValueError('所选报告日期没有观测')
 base['summary']=summary(base['items']);base['alerts']=[i for i in base['items'] if i['risk_level']=='预警'];base['review_queue']=[i for i in (base.get('period') or {}).get('daily_items',base['items']) if i['needs_review'] or i['risk_level']=='未知']
 base['context'].update(real_records=sum(r.get('data_origin','real')=='real' for r in raw),simulated_records=sum(r.get('data_origin')=='simulated' for r in raw),records=len(raw),effective_standard_origin=None)
 base['standards_sources']=[{'source_id':'PROJECT-CONTROL','source_label':ctx.get('control_source') or '未确认项目控制值','source_type':'project_requirement'}]
 base['note']='仅支持盾构施工周边地表与建筑沉降；未知不代表正常；仅执行字段、单位、时间及有限数校验，未实施专业传感器诊断；负累计沉降表示上浮，未配置独立上浮判据时暂不判断该项。'
 return {'result':base,'summary':base['summary'],'trace':{'records':len(items),'source_records':len(raw),'read_report':reports}}

def value_at(root,path):
 for key in path.split('.'):root=root[int(key)] if isinstance(root,list) else root[key]
 return root

def report_payload(req):
 payload=req['daily_report_input'];analysis=req.get('work_condition_analysis') or {};narrative=analysis.get('narrative')
 def resolve_text(text):
  def replace(match):
   value=value_at(payload,match[1]);
   if isinstance(value,list) and all(x is None or isinstance(x,(str,int,float,bool)) for x in value):value='、'.join(str(x) for x in value if x is not None)
   if value is not None and not isinstance(value,(str,int,float,bool)):raise ValueError('正文引用只能是标量')
   return str(value) if value is not None else '未提供'
  return re.sub(r'\{\{fact:([^{}]+)\}\}',replace,text)
 def walk(v):
  if isinstance(v,dict) and 'text' in v and 'evidence_ids' in v:
   stripped=re.sub(r'\{\{fact:[^{}]+\}\}','',v['text'])
   if re.search(r'[0-9{}]',stripped) or any(x in stripped for x in ['原因已经确认','已正式签发','无需人工复核']):raise ValueError('未绑定数值或越过工程责任边界')
   valid_ids={e['id'] for e in (req.get('standard_evidence') or {}).get('evidence',[])}
   if any(eid not in valid_ids for eid in v['evidence_ids']):raise ValueError('引用不属于冻结规范证据')
  if isinstance(v,dict):return {k:walk(x) for k,x in v.items()}
  if isinstance(v,list):return [walk(x) for x in v]
  return resolve_text(v) if isinstance(v,str) else v
 evidence=(req.get('standard_evidence') or {}).get('evidence') or []
 return {'sections':{'project':payload['project'],'monitoring_results':{'items':deepcopy(payload['items'])},'summary':payload['summary'],'narrative':walk(narrative) if narrative else None,'standard_evidence':evidence,'period':payload.get('period'),'review_queue':payload.get('review_queue',[]),'supporting_context':analysis.get('supporting_context')},'template_version':req['template_version'],'review_required':True,'status':'draft','generation_notice':('模拟模型响应验收，不代表真实模型语义审查效果' if str(analysis.get('model','')).startswith('SIMULATED') else '模型草稿，须独立审查' if narrative else '模板模式，未执行模型语义审查')}

def markdown_for(report,payload):
 def shown(v):return '—' if v is None else str(v).replace('|','\\|').replace('\n',' ')
 evidence={e['id']:e for e in report['sections']['standard_evidence']}
 def paragraph(p):
  refs=[]
  for eid in p.get('evidence_ids',[]):
   e=evidence[eid];m=e['metadata'];refs.append(f"《{m['standard_name']}》{m['standard_version']} · {m['clause']}")
  return p['text']+('〔依据：'+'；'.join(refs)+'〕' if refs else '')
 lines=['# 盾构施工周边沉降报告','',f"工程：{payload['project'].get('name') or '未提供'}",f"报告日期：{payload['project'].get('report_date') or '未提供'}",report['generation_notice'],'工程监测草稿，须工程师复核；判据来自确认项目要求，规范检索不自动替换控制值。',payload.get('note',''),'','## 本期概况',f"观测条目：{payload['summary']['total']}；整体状态：{payload['summary']['overall_risk_level']}"]
 period=payload.get('period')
 if period:
  lines += [f"报告区间：{period['start_date']} 至 {period['end_date']}",'附表为每通道区间最严重原观测，保留原观测日期，不代表期末值。',f"区间未知判定条目：{sum(i['risk_level']=='未知' for i in period.get('daily_items',[]))}；待复核条目：{len(payload.get('review_queue',[]))}。未知和缺测不等于正常。"]
 narrative=report['sections']['narrative']
 if narrative:
  lines += ['','## 工况说明',paragraph(narrative['work_condition'])]
  for key,label in [('analysis','分析'),('recommendations','复核建议'),('limitations','局限与待核事项')]:lines+=['','## '+label]+[paragraph(p) for p in narrative.get(key,[])]
  for a in narrative.get('appendix_analysis',[]):lines+=['','### 沉降分项分析',paragraph(a['analysis']),paragraph(a['recommendation'])]
 else:lines+=['','## 工况及局限','未执行模型正文分析；工况和巡视资料范围以本次冻结输入为准。']
 lines+=['','## 沉降成果','| 测点 | 测项 | 时间 | 观测值(mm) | 累计沉降(mm) | 单次变化(mm) | 绝对变化速率(mm/d) | 状态 | 判据来源 | 待核 |','|---|---|---|---|---|---|---|---|---|---|']
 for row in payload['items']:
  values=[row.get(k) for k in ['point_id','metric_name','timestamp','current','cumulative','single_change','rate','risk_level']]+[row['effective_standard'].get('source_label'),'、'.join(row['abstain'])]
  lines.append('| '+' | '.join(shown(v) for v in values)+' |')
 supporting=report['sections'].get('supporting_context') or {}
 if supporting:
  lines += ['','## 辅助资料核对',supporting.get('notice','仅供线索，不证明因果。')]
  for d in supporting.get('documents',[]):lines.append('资料：'+d['title'])
  cases=supporting.get('case_retrieval') or {};work=supporting.get('work_analysis') or {}
  for candidate in cases.get('cases',[]):lines.append(f"案例《{candidate['source_title']}》：{shown(candidate['excerpt'])}；仅为关联线索。")
  for link in work.get('links',[])[:20]:lines.append(f"记录《{link['source_title']}》 {link.get('timestamp','')} {link.get('section') or link.get('point_id') or '位置待核'}：{shown(link['text'])}")
  lines.append(f"位置待核{len(work.get('pending',[]))}条；结构化冲突{len(work.get('conflicts',[]))}组。")
  if work.get('patrol_status')=='not_provided':lines.append('本次未提供巡视资料，不据此判定巡视正常。')
  if work.get('truncated') or cases.get('truncated'):lines.append('辅助候选按预算截断，完整来源见冻结记录。')
 lines+=['','## 规范候选依据' ,'以下为检索候选；OCR内容、条文效力和工程适用性须核对原页。']
 for e in evidence.values():
  m=e['metadata'];lines += ['',f"### 《{m['standard_name']}》{m['standard_version']} · {m['clause']}",m['source_location'].split('；原文件SHA256')[0],e['text']]
 if not evidence:lines.append('本次未检索到可交付规范证据，不代表没有相关要求。')
 return '\n'.join(lines)+'\n'

def render(req):
 from openpyxl import Workbook
 target=Path(req['artifact_output_dir']).resolve();target.relative_to(ROOT/'var/report-artifacts');target.mkdir(parents=True,exist_ok=False)
 report=report_payload(req);payload=req['daily_report_input'];wb=Workbook();sheet=wb.active;sheet.title='沉降成果';sheet.append(['测点','测项','时间','观测值mm','累计沉降mm','本次变化mm','变化速率mm每日','状态','判据来源','待核'])
 bindings=[];cells=[]
 fields=['point_id','metric_name','timestamp','current','cumulative','single_change','rate','risk_level']
 for i,row in enumerate(payload['items']):
  sheet.append([safe(v) for v in [row.get(k) for k in fields]+[row['effective_standard'].get('source_label'),';'.join(row['abstain'])]])
  for j,key in enumerate(fields):
   path=f'items.{i}.{key}';bindings.append({'binding_id':f'item-{i}-{key}','report_path':f'sections.monitoring_results.items.{i}.{key}','fact_path':path,'fact_value_hash':digest(row.get(key))})
   cells.append({'artifact_kind':'workbook','location':f'沉降成果!{sheet.cell(i+2,j+1).coordinate}','fact_path':path,'fact_value_hash':digest(row.get(key)),'rendered_value_hash':digest(safe(row.get(key)))})
 evidence=report['sections']['standard_evidence'];ws=wb.create_sheet('规范证据');ws.append(['名称','编号','条款','原文','定位'])
 for e in evidence:ws.append([safe(v) for v in [e['metadata']['standard_name'],e['metadata']['standard_version'],e['metadata']['clause'],e['text'],e['metadata']['source_location']]])
 markdown=markdown_for(report,payload)
 cover=wb.create_sheet('报告说明')
 for line in markdown.splitlines():cover.append([safe(line)])
 workbook=target/'盾构沉降报告.xlsx';wb.save(workbook);artifacts=[]
 for kind,name,media in [('workbook','盾构沉降报告.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),('cover_markdown','盾构沉降报告_封面.md','text/markdown'),('appendices_markdown','盾构沉降报告_附表.md','text/markdown')]:
  path=target/name
  if kind!='workbook':path.write_text(markdown,encoding='utf-8')
  data=path.read_bytes();artifacts.append({'kind':kind,'file_name':name,'relative_path':path.relative_to(ROOT).as_posix(),'media_type':media,'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data),'sheets':wb.sheetnames if kind=='workbook' else []})
 citations=[]
 def gather(v):
  if isinstance(v,dict):
   for eid in v.get('evidence_ids',[]):citations.append({'citation_id':f'c-{len(citations)}','report_path':'sections.narrative','evidence_id':eid})
   for x in v.values():gather(x)
  elif isinstance(v,list):
   for x in v:gather(x)
 gather(report['sections']['narrative'])
 return {'report_payload':report,'fact_bindings':bindings,'artifact_bindings':cells,'citations':citations,'artifacts':artifacts,'template_version':req['template_version'],'review_required':True}

def audit(req):
 from openpyxl import load_workbook
 expected=report_payload(req);valid=expected==req['report_payload'];checks=[{'name':'frozen_report_projection','valid':valid}];issues=[]
 artifact=next(a for a in req['artifacts'] if a['kind']=='workbook');path=(ROOT/artifact['relative_path']).resolve();path.relative_to(ROOT/'var/report-artifacts');wb=load_workbook(path,data_only=True)
 fields=['point_id','metric_name','timestamp','current','cumulative','single_change','rate','risk_level']
 for i,row in enumerate(req['daily_report_input']['items']):
  for j,key in enumerate(fields):
   actual=wb['沉降成果'].cell(i+2,j+1).value;value=safe(row.get(key))
   same=math.isclose(actual,value,rel_tol=1e-12,abs_tol=1e-10) if isinstance(actual,(float,int)) and isinstance(value,(float,int)) else actual==value
   valid=valid and same
 evidence=expected['sections']['standard_evidence']
 valid=valid and wb['规范证据'].max_row==len(evidence)+1
 for i,e in enumerate(evidence):
  row=[e['metadata']['standard_name'],e['metadata']['standard_version'],e['metadata']['clause'],e['text'],e['metadata']['source_location']]
  for j,value in enumerate(row):valid=valid and wb['规范证据'].cell(i+2,j+1).value==safe(value)
 expected_markdown=markdown_for(expected,req['daily_report_input'])
 valid=valid and wb['报告说明'].max_row==len(expected_markdown.splitlines())
 for i,line in enumerate(expected_markdown.splitlines()):valid=valid and wb['报告说明'].cell(i+1,1).value==(safe(line) if line else None)
 for artifact in req['artifacts']:
  if artifact['kind']!='workbook':valid=valid and (ROOT/artifact['relative_path']).read_text(encoding='utf-8')==expected_markdown
 if not valid:issues.append({'code':'SHIELD_REPORT_MISMATCH','severity':'error','blocking':True,'responsibility':'report-delivery','path':'report','message':'报告文件与冻结事实不一致'})
 return {'valid':valid,'checks':checks+[{'name':'independent_cell_check','valid':valid}],'issues':issues}

def main(action):
 try:
  req=json.load(sys.stdin)
  if action=='judge':out=judge(req);print(json.dumps({'ok':True,**out},ensure_ascii=False));return
  if action in ('inspect','normalize'):
   rows,reports=read(req);report=reports[0] if len(reports)==1 else {'ok':True};report['temporal_coverage']={'dates':dates(rows),'source_record_count':len(rows)}
   result=report if action=='inspect' else {'records':rows,'read_report':report}
  elif action=='render':result=render(req)
  elif action=='audit':result=audit(req)
  else:raise ValueError('盾构控制值通过工程配置确认，不接受基坑阈值JSON覆盖')
  print(json.dumps({'ok':True,'result':result,'trace':{'records':len(rows) if action in ('inspect','normalize') else 0}},ensure_ascii=False,default=str))
 except Exception as e:print(json.dumps({'ok':False,'error':{'code':'INVALID_INPUT','message':str(e)}},ensure_ascii=False));sys.exit(2)
