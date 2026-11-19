"""Tunnel deformation: explicit metric semantics and metric-scoped confirmed project limits."""
import json,sys,hashlib,math,statistics,re
from pathlib import Path
from datetime import datetime,timezone,timedelta
from copy import deepcopy
from collections import Counter
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'确定性计算层/pipeline/stage1_data_preparation'))
sys.path.insert(0,str(ROOT/'确定性计算层/pipeline'))
from file_reader import read_monitoring_file
RULES=json.loads((Path(__file__).resolve().parents[1]/'rules.json').read_text(encoding='utf-8'))
SCOPE=json.loads((Path(__file__).resolve().parents[1]/'scope.json').read_text(encoding='utf-8'))

def safe(v):return "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v
def stable(v):return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def digest(v):return hashlib.sha256(stable(v).encode()).hexdigest()
def local_time(value):
 d=datetime.fromisoformat(str(value).replace(' ','T'));zone=timezone(timedelta(hours=8))
 return (d.replace(tzinfo=zone) if d.tzinfo is None else d).astimezone(zone)
def dates(rows):return sorted({local_time(r['timestamp']).date().isoformat() for r in rows})
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
  if end and local_time(row['timestamp']).date().isoformat()>end:continue
  groups.setdefault((row.get('point_id'),key),[]).append(row)
 base=template();prototype=deepcopy(base['items'][0])
 for (point,key),rows in sorted(groups.items(),key=lambda x:str(x[0])):
  rows.sort(key=lambda r:instant(r['timestamp']));prior=None;series=[];reference=None
  instants=[instant(r['timestamp']) for r in rows]
  if len(instants)!=len(set(instants)):raise ValueError('同测点同测项存在等价时间重复观测，需核对时区或测项别名')
  semantics=((ctx.get('metric_controls') or {}).get(key) or {}).get('value_semantics',ctx.get('value_semantics'))
  for row in rows:
   item=deepcopy(prototype);unit=row.get('unit');factor={'mm':1,'cm':10,'m':1000}.get(unit)
   value=float(row.get('value',row.get('current')))
   if not math.isfinite(value) or factor is None:raise ValueError('数值非有限或单位不支持；沉降支持mm/cm/m')
   current=value*factor;timestamp=local_time(row['timestamp']).isoformat(sep=' ');t=instant(timestamp);cumulative=None;baseline=None;flags=[]
   if semantics in ('cumulative_settlement','cumulative_displacement'):baseline=0;cumulative=current;flags.append('INPUT_CONVERGENCE_INWARD_POSITIVE' if semantics=='cumulative_displacement' else 'INPUT_CUMULATIVE_DOWNWARD_POSITIVE')
   else:
    supplied=row.get('baseline_value',row.get('baseline'))
    if supplied is not None:
     baseline=float(supplied)*factor
     if not math.isfinite(baseline):raise ValueError('初始基准必须为有限数值')
     if reference is not None and not math.isclose(reference,baseline,rel_tol=0,abs_tol=1e-8):raise ValueError('同测点初始基准变化，不能直接计算累计沉降')
     reference=baseline
    elif reference is not None:baseline=reference;flags.append('BASELINE_REUSED_FROM_PRIOR_INPUT')
    if baseline is not None:cumulative=baseline-current
   previous=prior[0] if prior else None;interval=t-prior[1] if prior else None
   if interval is not None and interval<=0:raise ValueError('相邻观测时间必须递增')
   change=(current-previous) if previous is not None else None
   if change is not None and semantics=='elevation':change=-change
   rate=abs(change)/interval if change is not None else None
   if any(v is not None and not math.isfinite(v) for v in (current,cumulative,change,rate)):raise ValueError('换算或派生计算结果非有限，需核对原始数值及时间间隔')
   series.append((t,cumulative))
   available=[(x,y) for x,y in series if y is not None]
   slope=None
   if len(available)>=3:
    mx=statistics.mean(x for x,y in available);my=statistics.mean(y for x,y in available);den=sum((x-mx)**2 for x,y in available)
    slope=sum((x-mx)*(y-my) for x,y in available)/den if den else None
   abstain=[];checks=[]
   if semantics=='elevation' and baseline is None:abstain.append('MISSING_INITIAL_BASELINE')
   if key not in RULES['metrics']:
    abstain.append('UNKNOWN_METRIC');cumulative=None;change=None;rate=None;slope=None
   if key in RULES['metrics'] and semantics not in RULES['metrics'][key]['semantics']:
    abstain.append('METRIC_VALUE_SEMANTICS_MISMATCH');cumulative=None;change=None;rate=None;slope=None
   controls=(ctx.get('metric_controls') or {}).get(key)
   if controls is None:
    controls={'source':ctx.get('control_source'),'confirmed':ctx.get('control_values_confirmed'),'cumulative_limit_mm':ctx.get('cumulative_limit_mm'),'rate_limit_mm_per_day':ctx.get('rate_limit_mm_per_day')} if key==ctx.get('control_metric') else {}
   if not controls.get('confirmed') or not str(controls.get('source') or '').strip():abstain.append('MISSING_CONFIRMED_PROJECT_CRITERIA')
   else:
    for name,value,limit in [('cumulative',cumulative,controls.get('cumulative_limit_mm')),('rate',rate,controls.get('rate_limit_mm_per_day'))]:
     if limit is None:continue
     if value is None:abstain.append('MISSING_'+name.upper());continue
     if name=='cumulative' and value<0:abstain.append('REVERSE_DIRECTION_CONTROL_NOT_PROVIDED');continue
     checks.append({'type':name,'value':value,'limit':limit,'unit':'mm' if name=='cumulative' else 'mm/d','utilization':abs(value)/limit,'verdict':'预警' if abs(value)>=limit else '未触发','limit_basis':'工程师确认项目控制值；非规范统一阈值'})
    if not checks and not abstain:abstain.append('NO_CONFIRMED_LIMIT')
   exceed=any(c['utilization']>=1 for c in checks)
   risk='预警' if exceed and key in RULES['metrics'] and 'METRIC_VALUE_SEMANTICS_MISMATCH' not in abstain else '未知' if abstain else '正常'
   source=controls.get('source') or '项目控制要求未确认'
   metadata=row.get('source_metadata') or {}
   if isinstance(metadata,str):metadata=json.loads(metadata)
   metadata={**metadata,'original_timestamp':str(row['timestamp']),'units':{'current':'mm','cumulative':'mm','single_change':'mm','rate':'mm/d','slope':'mm/d'}}
   item.update(point_id=point,metric_key=key,metric_name=RULES['metrics'].get(key,{}).get('display_name',key),timestamp=timestamp,data_origin=row.get('data_origin','real'),current=current,unit='mm',baseline=baseline,previous=previous,interval_days=interval,cumulative=cumulative,single_change=change,rate=rate,slope=slope,risk_level=risk,problem_category='变形监测待核' if risk=='未知' else '变形监测',checks=checks,utilization=max((c['utilization'] for c in checks),default=None),abstain=abstain,abstain_reasons=abstain,flags=flags,needs_review=bool(abstain),rule_id='tunnel-project-deformation/v1',source_metadata=metadata,
    evidence={'standard':source,'clause':'项目批准控制要求','note':'RAG仅查证适用要求，不改变本项限值'},effective_standard={'origin':'project_confirmed' if controls.get('confirmed') else 'unconfirmed','source_id':'PROJECT-CONTROL','source_label':source,'origin_display':'项目确认要求' if controls.get('confirmed') else '未确认项目要求'})
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
 base['standards_sources']=[{'source_id':'PROJECT-CONTROL','source_label':label,'source_type':'project_requirement'} for label in sorted({i['effective_standard']['source_label'] for i in items})]
 base['note']='本适配器计算地表、建筑、拱顶沉降和净空收敛；沉降向下为正、收敛向内为正。每测项单独确认项目控制值，不跨测项套用。未知不等于正常；反向变形、气体和应力等未配置判据须人工核查。规范候选不能自动修改冻结判据。'
 base['project']['tunnel_scope']={k:ctx[k] for k in ['tunnel_system','construction_method','project_stage','special_condition']}
 base['project']['tunnel_scope_display']='；'.join(label+'：'+SCOPE['query_labels'].get(ctx[key],ctx[key]) for key,label in [('tunnel_system','工程类别'),('construction_method','工法'),('project_stage','阶段'),('special_condition','特殊条件')])
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
 review=req.get('standard_evidence') or {}
 if req.get('require_full_coverage'):
  coverage=review.get('coverage') or {};entries=coverage.get('standards') or []
  catalog=json.loads((Path(__file__).resolve().parents[1]/'catalog.json').read_text(encoding='utf-8'))
  version_key=lambda value:re.sub(r'[^A-Z0-9]','',str(value).upper())
  expected={version_key(s['code']) for s in catalog['standards']};actual=[version_key(e['standard_version']) for e in entries]
  if not coverage.get('completed') or len(actual)!=len(set(actual)) or not expected.issubset(actual) or coverage.get('catalogue_count')!=len(entries) or any(e['status'] not in ('matched','no_relevant_hit','skipped_scope','skipped_status') for e in entries):
   raise ValueError('STANDARD_COVERAGE_INCOMPLETE：未完成全规范逐本核查，不能交付隧道报告')
  evidence_by_id={e['id']:e for e in review.get('evidence',[])}
  for entry in entries:
   ids=entry.get('retained_ids',[])
   if (entry['status']=='matched' and not ids) or any(eid not in evidence_by_id or version_key(evidence_by_id[eid]['metadata']['standard_version'])!=version_key(entry['standard_version']) for eid in ids):
    raise ValueError('STANDARD_COVERAGE_MISMATCH：逐本清单与冻结条文不一致')
 evidence=deepcopy((req.get('standard_evidence') or {}).get('evidence') or [])
 if len({e['id'] for e in evidence})!=len(evidence):raise ValueError('INVALID_EVIDENCE_SOURCE：证据ID重复')
 for e in evidence:reference_label(e)
 return {'sections':{'project':payload['project'],'monitoring_results':{'items':deepcopy(payload['items'])},'summary':payload['summary'],'narrative':walk(narrative) if narrative else None,'standard_evidence':evidence,'standard_review':deepcopy(req.get('standard_evidence') or {}),'engineer_feedback':deepcopy(analysis.get('engineer_feedback')),'period':payload.get('period'),'review_queue':payload.get('review_queue',[]),'supporting_context':analysis.get('supporting_context')},'template_version':req['template_version'],'review_required':True,'status':'draft','generation_notice':('模拟模型响应验收，不代表真实模型语义审查效果' if str(analysis.get('model','')).startswith('SIMULATED') else '模型草稿，须独立审查' if narrative else '模板模式，未执行模型语义审查')}

def detail_markdown(report,payload):
 def shown(v):return '—' if v is None else str(v).replace('|','\\|').replace('\n',' ')
 evidence={e['id']:e for e in report['sections']['standard_evidence']}
 def paragraph(p):
  refs=[]
  for eid in p.get('evidence_ids',[]):
   e=evidence[eid];m=e['metadata'];refs.append(f"《{m['standard_name']}》{m['standard_version']} · {m['clause']}")
  return p['text']+('〔依据：'+'；'.join(refs)+'〕' if refs else '')
 lines=['# 隧道变形监测报告','',f"工程：{payload['project'].get('name') or '未提供'}",f"报告日期：{payload['project'].get('report_date') or '未提供'}",report['generation_notice'],'工程监测草稿，须工程师复核；判据来自确认项目要求，规范检索不自动替换控制值。',payload.get('note',''),'','## 本期概况',f"{'通道代表记录' if payload.get('period') else '观测条目'}：{payload['summary']['total']}；整体状态：{payload['summary']['overall_risk_level']}"]
 lines+=[payload['project'].get('tunnel_scope_display','工程分类未提供')]
 period=payload.get('period')
 if period:
  lines += [f"报告区间：{period['start_date']} 至 {period['end_date']}",'附表为每通道区间最严重原观测，保留原观测日期，不代表期末值。',f"区间未知判定条目：{sum(i['risk_level']=='未知' for i in period.get('daily_items',[]))}；待复核条目：{len(payload.get('review_queue',[]))}。未知和缺测不等于正常。"]
 if period:
  lines += [f"区间原始观测：{period['observation_count']}条；监测通道：{period['channel_count']}；有观测日期：{period['observed_days']}天；整日缺测：{'、'.join(period['missing_dates']) or '无'}。",'通道变化中的首末值是原观测值；高程语义下不等同累计沉降。有观测日期不代表采样频率达标。']
  for title,matrix in period_tables(payload).items():
   if title=='周期观测明细':continue
   lines += ['', '## '+title,'| '+' | '.join(matrix[0])+' |','|'+'|'.join(['---']*len(matrix[0]))+'|']
   for row in matrix[1:]:lines.append('| '+' | '.join(shown(v) for v in row)+' |')
 narrative=report['sections']['narrative']
 if narrative:
  lines += ['','## 工况说明',paragraph(narrative['work_condition'])]
  for key,label in [('analysis','分析'),('recommendations','复核建议'),('limitations','局限与待核事项')]:lines+=['','## '+label]+[paragraph(p) for p in narrative.get(key,[])]
  for a in narrative.get('appendix_analysis',[]):lines+=['','### 变形分项分析',paragraph(a['analysis']),paragraph(a['recommendation'])]
 else:lines+=['','## 工况及局限','未执行模型正文分析；工况和巡视资料范围以本次冻结输入为准。']
 lines+=['','## 变形成果','| 测点 | 测项 | 时间 | 观测值(mm) | 累计变形(mm) | 单次变化(mm) | 绝对变化速率(mm/d) | 状态 | 判据来源 | 待核 |','|---|---|---|---|---|---|---|---|---|---|']
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
 return '\n'.join(line.rstrip() for line in '\n'.join(lines).splitlines())+'\n'

def reference_label(e):
 m=e['metadata']
 if not all(m.get(k) for k in ('standard_name','standard_version','clause','source_location')):
  raise ValueError('INVALID_EVIDENCE_SOURCE：规范引用缺少名称、编号、条文或来源定位')
 return f"《{m['standard_name']}》 {m['standard_version']} · {m['clause']}（{m['source_location'].split('；原文件SHA256')[0]}）"

def paragraph_text(report,p):
 evidence={e['id']:e for e in report['sections']['standard_evidence']}
 return p.get('text','')+('\n规范依据：'+'；'.join(reference_label(evidence[eid]) for eid in dict.fromkeys(p.get('evidence_ids',[]))) if p.get('evidence_ids') else '')

def appendix_references(report):
 narrative=report['sections'].get('narrative') or {}
 return [paragraph_text(report,a[k]) for a in narrative.get('appendix_analysis',[]) for k in ('analysis','recommendation') if k in a]

def markdown_for(report,payload):
 sections=report['sections'];narrative=sections.get('narrative') or {};period=payload.get('period');review=sections.get('standard_review') or {}
 lines=['# 隧道变形监测报告（草稿）','',f"工程：{payload['project'].get('name') or '未提供'}",f"报告日期：{payload['project'].get('report_date') or '未提供'}",report['generation_notice'],'','## 一、工况描述',paragraph_text(report,narrative['work_condition']) if narrative else '未执行模型正文分析；工况及巡视以冻结资料为准。',payload['project'].get('tunnel_scope_display','工程分类未提供'),payload.get('note','')]
 supporting=sections.get('supporting_context') or {}
 lines += ['辅助资料：'+('、'.join(d['title'] for d in supporting.get('documents',[])) or '未提供；不得据此判定巡视正常。')]
 lines += ['','## 二、简要分析及判断性结论',f"{'通道代表记录' if period else '观测条目'}：{payload['summary']['total']}；整体状态：{payload['summary']['overall_risk_level']}", '风险分布：'+'；'.join(f'{k}={v}' for k,v in payload['summary'].get('by_risk_level',{}).items())]
 for key in ('analysis','recommendations'):lines += [paragraph_text(report,p) for p in narrative.get(key,[])]
 if period:lines += [f"报告区间：{period['start_date']} 至 {period['end_date']}",f"区间原始观测：{period['observation_count']}条；监测通道：{period['channel_count']}；整日缺测：{'、'.join(period['missing_dates']) or '无'}。",'附表为每通道区间最严重原观测，保留原观测日期，不代表期末值。']
 for title,matrix in period_tables(payload).items():
  if title=='周期观测明细':continue
  lines += ['', '## '+title,'| '+' | '.join(matrix[0])+' |','|'+'|'.join(['---']*len(matrix[0]))+'|']
  lines += ['| '+' | '.join(('—' if v is None else str(v)).replace('|','\\|').replace('\n',' ') for v in row)+' |' for row in matrix[1:]]
 lines += ['','## 三、待复核事项','未知和缺测不等于正常；未提供巡视资料不得表述为巡视正常。']
 lines += [f"{r.get('point_id')}／{r.get('metric_name')}／{r.get('timestamp')}："+'、'.join(r.get('abstain',[])) for r in payload.get('review_queue',[])]
 lines += [paragraph_text(report,p) for p in narrative.get('limitations',[])]
 for row in feedback_tables(report).get('工程师意见回应',[])[1:]:lines += ['原意见：'+row[1],'工程师意见回应：'+row[4],'回应状态：'+row[3]]
 lines += ['','## 四、规范核对依据（RAG知识库检索）','数值判级采用冻结的项目确认控制要求及已发布规则；以下检索候选不自动替代控制值，OCR内容及适用性须核对原页。']
 for e in sections['standard_evidence']:
  lines += ['',reference_label(e),'来源：'+e['metadata']['source_location'].split('；原文件SHA256')[0], '检索来源：'+e.get('provider','未提供'),'原文：'+e['text']]
 if not sections['standard_evidence']:lines += ['本次未检索到可交付规范证据，不代表没有相关要求；逐本核查结果见全规范清单。']
 matrix=coverage_table(report)
 lines += ['', '### 全规范逐本核查清单','| '+' | '.join(matrix[0])+' |','|'+'|'.join(['---']*len(matrix[0]))+'|']
 lines += ['| '+' | '.join(str(v).replace('|','\\|').replace('\n',' ') for v in row)+' |' for row in matrix[1:]]
 lines += ['检索缺口：'+str(g) for g in review.get('gaps',[])]
 coverage=review.get('coverage') or {}
 if coverage:
  lines += [f"规范目录覆盖：{coverage.get('queried_count')} / {coverage.get('catalogue_count')}；相关候选 {coverage.get('candidate_count')} 条，保留 {coverage.get('retained_count')} 条。",coverage.get('notice','')]
  lines += [f"《{e.get('standard_name')}》 {e.get('standard_version')}：{e.get('reason')}" for e in coverage.get('standards',[])]
 extended=review.get('extended_review') or {}
 if extended:lines += ['多日预警追加规范核查：'+str(extended.get('status')),extended.get('notice','')]
 lines += ['','## 五、签署','监测人：＿＿＿＿　计算人：＿＿＿＿　校核人：＿＿＿＿','审核人：＿＿＿＿　项目负责人：＿＿＿＿','（均为人工填写）','本报告为工程师复核草稿，不代表正式签发或自动发布预警。']
 return '\n'.join(line.rstrip() for line in '\n'.join(lines).splitlines())+'\n'

def appendices_markdown(report,payload):
 lines=['# 隧道监测报告附表及清单','','## 附表S 隧道变形监测成果']+appendix_references(report)
 detail=detail_markdown(report,payload)
 lines += [detail[detail.index('## 变形成果'):], '', '## 周期统计与来源追溯']
 for title,matrix in period_tables(payload).items():
  lines += ['','## '+title,'| '+' | '.join(str(v) for v in matrix[0])+' |','|'+'|'.join(['---']*len(matrix[0]))+'|']
  lines += ['| '+' | '.join(('—' if v is None else str(v)).replace('|','\\|').replace('\n',' ') for v in row)+' |' for row in matrix[1:]]
 matrix=coverage_table(report)
 lines += ['', '## 全规范逐本核查清单','| '+' | '.join(matrix[0])+' |','|'+'|'.join(['---']*len(matrix[0]))+'|']
 lines += ['| '+' | '.join(str(v).replace('|','\\|').replace('\n',' ') for v in row)+' |' for row in matrix[1:]]
 for title,matrix in feedback_tables(report).items():
  lines += ['', '## '+title,'| '+' | '.join(matrix[0])+' |','|'+'|'.join(['---']*len(matrix[0]))+'|']
  lines += ['| '+' | '.join(str(v).replace('|','\\|').replace('\n','<br>') for v in row)+' |' for row in matrix[1:]]
 lines += ['原始输入：'+json.dumps(payload['project'].get('pre_agent_preparation',{}).get('sources',[]),ensure_ascii=False),'逐条判据来源随成果保留；RAG解释依据见具名规范清单，不将项目控制要求冒充规范统一阈值。']
 return '\n'.join(line.rstrip() for line in '\n'.join(lines).splitlines())+'\n'

def period_tables(payload):
 period=payload.get('period')
 if not period:return {}
 return {
  '每日汇总':[['日期','观测条数','预警条数','未知条数','当日最严重状态','整日无观测']]+[[r[k] for k in ['date','observation_count','warning_count','unknown_count','worst_known_risk','missing']] for r in period['daily_summaries']],
  '通道变化':[['测点','测项','有数据天数','缺测日期','预警天数','连续预警最长天数','未知天数','首次数值mm','末次数值mm','代表记录时间']]+[[r['point_id'],r.get('metric_name') or r['metric_key'],r['observed_days'],'、'.join(r['missing_dates']),r['warning_days'],r['max_consecutive_warning_days'],r['unknown_days'],r.get('first_current'),r.get('last_current'),r['representative_timestamp']] for r in period['channels']],
  '周期观测明细':[['测点','测项','时间','观测值mm','累计变形mm','变化速率mm每日','状态','判据来源','待核']]+[[r.get('point_id'),r.get('metric_name'),r.get('timestamp'),r.get('current'),r.get('cumulative'),r.get('rate'),r.get('risk_level'),r['effective_standard'].get('source_label'),'、'.join(r.get('abstain',[]))] for r in period['daily_items']]
 }

def coverage_table(report):
 review=report['sections'].get('standard_review') or {}
 coverage=review.get('coverage') or {}
 entries=coverage.get('standards')
 if entries is None:
  catalog=json.loads((Path(__file__).resolve().parents[1]/'catalog.json').read_text(encoding='utf-8'))
  entries=[{'standard_name':s['name'],'standard_version':s['code'],'effective_status':'待核','status':'not_queried','reason':'本次未完成逐本检索，不得声称全规范覆盖。','retained_ids':[]} for s in catalog['standards']]
 evidence={e['id']:e for e in report['sections']['standard_evidence']}
 labels={'matched':'取得候选，适用性待核','no_relevant_hit':'已检索，无适用候选','skipped_scope':'本工程不适用','skipped_status':'效力未确认或非现行','not_queried':'未检索','pending':'未完成','unavailable':'检索不可用'}
 rows=[['规范名称','规范编号','效力状态','本次核查结果','具体条文及页码','说明']]
 for entry in entries:
  refs=[reference_label(evidence[eid]) for eid in entry.get('retained_ids',[]) if eid in evidence]
  rows.append([entry['standard_name'],entry['standard_version'],entry['effective_status'],labels.get(entry['status'],entry['status']),'；'.join(refs) or '—',entry['reason']])
 return rows

def feedback_tables(report):
 feedback=report['sections'].get('engineer_feedback')
 if not feedback:return {}
 narrative=report['sections'].get('narrative') or {}
 responses={r['feedback_id']:r for r in narrative.get('feedback_responses',[])}
 table=[['意见编号','原意见','关联对象','处理状态','本次回应']]
 for item in feedback.get('items',[]):
  response=responses.get(item['feedback_id'])
  table.append([item['feedback_id'],item['comment'],stable(item.get('target')) if item.get('target') else '整份日报',response['status'] if response else '待处理',paragraph_text(report,response['response']) if response else '未回应，不代表问题已解决'])
 def paragraphs(value):
  result={}
  if not isinstance(value,dict):return result
  if value.get('work_condition'):result['工况描述']=value['work_condition']
  for key,label in [('analysis','分析'),('recommendations','建议'),('limitations','待核事项')]:
   for i,paragraph in enumerate(value.get(key,[])):result[f'{label}.{i+1}']=paragraph
  for entry in value.get('appendix_analysis',[]):
   for key in ('analysis','recommendation'):
    if key in entry:result[f"附表{entry['form']}.{key}"]=entry[key]
  return result
 prior=paragraphs(feedback.get('prior_narrative'));current=paragraphs(narrative)
 diff=[['正文位置','原版内容（历史保留）','本版内容','是否变化']]
 for key in dict.fromkeys([*prior,*current]):
  before=prior.get(key,{}).get('text','—');after=paragraph_text(report,current[key]) if key in current else '—'
  diff.append([key,before,after,'有修订' if before!=current.get(key,{}).get('text','—') else '未变化'])
 return {'工程师意见回应':table,'修订前后对照':diff}

def provenance_table(payload):
 rows=payload.get('period',{}).get('daily_items',payload['items'])
 return [['测点','测项','观测时间','原始来源及预处理记录','采用判据','判据条文及说明']]+[[r.get('point_id'),r.get('metric_name'),r.get('timestamp'),stable(r.get('source_metadata',{})),stable(r.get('effective_standard',{})),stable(r.get('evidence',{}))] for r in rows]

def report_tables(payload,report):
 return {**period_tables(payload),'来源追溯':provenance_table(payload),'规范检索覆盖':coverage_table(report),**feedback_tables(report)}

def render(req):
 from openpyxl import Workbook
 target=Path(req['artifact_output_dir']).resolve();target.relative_to(ROOT/'var/report-artifacts');target.mkdir(parents=True,exist_ok=False)
 report=report_payload(req);payload=req['daily_report_input'];wb=Workbook();sheet=wb.active;sheet.title='变形成果';sheet.append(['测点','测项','时间','观测值mm','累计变形mm','本次变化mm','变化速率mm每日','状态','判据来源','待核'])
 bindings=[];cells=[]
 fields=['point_id','metric_name','timestamp','current','cumulative','single_change','rate','risk_level']
 for i,row in enumerate(payload['items']):
  sheet.append([safe(v) for v in [row.get(k) for k in fields]+[row['effective_standard'].get('source_label'),';'.join(row['abstain'])]])
  for j,key in enumerate(fields):
   path=f'items.{i}.{key}';bindings.append({'binding_id':f'item-{i}-{key}','report_path':f'sections.monitoring_results.items.{i}.{key}','fact_path':path,'fact_value_hash':digest(row.get(key))})
   cells.append({'artifact_kind':'workbook','location':f'变形成果!{sheet.cell(i+2,j+1).coordinate}','fact_path':path,'fact_value_hash':digest(row.get(key)),'rendered_value_hash':digest(safe(row.get(key)))})
 for title,matrix in report_tables(payload,report).items():
  ws=wb.create_sheet(title)
  for row in matrix:ws.append([safe(v) for v in row])
  ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
 evidence=report['sections']['standard_evidence'];ws=wb.create_sheet('规范证据');ws.append(['名称','编号','条款','原文','定位'])
 for e in evidence:ws.append([safe(v) for v in [e['metadata']['standard_name'],e['metadata']['standard_version'],e['metadata']['clause'],e['text'],e['metadata']['source_location']]])
 markdown=markdown_for(report,payload)
 appendix=appendices_markdown(report,payload)
 ws=wb.create_sheet('附表S分析');ws.append(['分项分析及规范依据'])
 for line in appendix_references(report):ws.append([safe(line)])
 for ws in wb:
  ws.freeze_panes='A2'
  from openpyxl.styles import Alignment, Font, PatternFill
  for cell in ws[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='244760')
  for col in ws.columns:
   ws.column_dimensions[col[0].column_letter].width=min(80,max(18,max(len(str(c.value or '')) for c in col)+2))
   for cell in col:cell.alignment=Alignment(vertical='top',wrap_text=True)
 cover=wb.create_sheet('报告说明',0)
 for line in markdown.splitlines():cover.append([safe(line)])
 workbook=target/'隧道变形报告.xlsx';wb.save(workbook);artifacts=[]
 for kind,name,media in [('workbook','隧道变形报告.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),('cover_markdown','隧道变形报告_封面.md','text/markdown'),('appendices_markdown','隧道变形报告_附表.md','text/markdown')]:
  path=target/name
  if kind!='workbook':path.write_text(markdown if kind=='cover_markdown' else appendix,encoding='utf-8')
  data=path.read_bytes();artifacts.append({'kind':kind,'file_name':name,'relative_path':path.relative_to(ROOT).as_posix(),'media_type':media,'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data),'sheets':wb.sheetnames if kind=='workbook' else []})
 citations=[]
 def gather(v,path='sections.narrative'):
  if isinstance(v,dict):
   for eid in v.get('evidence_ids',[]):citations.append({'citation_id':f'c-{len(citations)}','report_path':path,'evidence_id':eid})
   for key,x in v.items():gather(x,f'{path}.{key}')
  elif isinstance(v,list):
   for i,x in enumerate(v):gather(x,f'{path}.{i}')
 gather(report['sections']['narrative'])
 return {'report_payload':report,'fact_bindings':bindings,'artifact_bindings':cells,'citations':citations,'artifacts':artifacts,'template_version':req['template_version'],'review_required':True}

def audit(req):
 from openpyxl import load_workbook
 expected=report_payload(req);valid=expected==req['report_payload'];checks=[{'name':'frozen_report_projection','valid':valid}];issues=[]
 artifact=next(a for a in req['artifacts'] if a['kind']=='workbook');path=(ROOT/artifact['relative_path']).resolve();path.relative_to(ROOT/'var/report-artifacts');wb=load_workbook(path,data_only=True)
 fields=['point_id','metric_name','timestamp','current','cumulative','single_change','rate','risk_level']
 for i,row in enumerate(req['daily_report_input']['items']):
  for j,key in enumerate(fields+['effective_standard.source_label','abstain']):
   actual=wb['变形成果'].cell(i+2,j+1).value;value=safe(row['effective_standard'].get('source_label') if key=='effective_standard.source_label' else ';'.join(row['abstain']) if key=='abstain' else row.get(key))
   if value=='':value=None
   same=math.isclose(actual,value,rel_tol=1e-12,abs_tol=1e-10) if isinstance(actual,(float,int)) and isinstance(value,(float,int)) else actual==value
   valid=valid and same
 for title,matrix in report_tables(req['daily_report_input'],expected).items():
  if title not in wb.sheetnames:valid=False;continue
  ws=wb[title];valid=valid and ws.max_row==len(matrix) and ws.max_column==len(matrix[0])
  for i,row in enumerate(matrix):
   for j,value in enumerate(row):
    actual=ws.cell(i+1,j+1).value;wanted=safe(value);wanted=None if wanted=='' else wanted
    same=math.isclose(actual,wanted,rel_tol=1e-12,abs_tol=1e-10) if isinstance(actual,(float,int)) and isinstance(wanted,(float,int)) else actual==wanted
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
  if artifact['kind']!='workbook':valid=valid and (ROOT/artifact['relative_path']).read_text(encoding='utf-8')==(expected_markdown if artifact['kind']=='cover_markdown' else appendices_markdown(expected,req['daily_report_input']))
 refs=appendix_references(expected)
 valid=valid and wb['附表S分析'].max_row==len(refs)+1
 for i,line in enumerate(refs):valid=valid and wb['附表S分析'].cell(i+2,1).value==safe(line)
 expected_citations=[]
 def gather(v,path='sections.narrative'):
  if isinstance(v,dict):
   for eid in v.get('evidence_ids',[]):expected_citations.append((eid,path))
   for key,x in v.items():gather(x,f'{path}.{key}')
  elif isinstance(v,list):
   for i,x in enumerate(v):gather(x,f'{path}.{i}')
 gather(expected['sections']['narrative'])
 valid=valid and [(c['evidence_id'],c['report_path']) for c in req.get('citations',[])]==expected_citations
 if not valid:issues.append({'code':'TUNNEL_REPORT_MISMATCH','severity':'error','blocking':True,'responsibility':'report-delivery','path':'report','message':'报告文件与冻结事实不一致'})
 return {'valid':valid,'checks':checks+[{'name':'independent_cell_check','valid':valid}],'issues':issues}

def main(action):
 try:
  req=json.load(sys.stdin)
  if action=='judge':out=judge(req);print(json.dumps({'ok':True,**out},ensure_ascii=False));return
  if action in ('inspect','normalize'):
   rows,reports=read(req);report=reports[0] if len(reports)==1 else {'ok':True};report['temporal_coverage']={'dates':dates(rows),'source_record_count':len(rows)}
   detected={}
   for row in rows:
    key=str(row.get('metric_key') or row.get('metric') or '')
    for candidate,definition in RULES['metrics'].items():
     if key in definition['aliases']:key=candidate;break
    detected[key]={'key':key,'name':RULES['metrics'].get(key,{}).get('display_name',key),'supported':key in RULES['metrics']}
   report['detected_metrics']=list(detected.values())
   result=report if action=='inspect' else {'records':rows,'read_report':report}
  elif action=='render':result=render(req)
  elif action=='audit':result=audit(req)
  else:raise ValueError('隧道控制值通过工程配置确认，不接受基坑阈值JSON覆盖')
  print(json.dumps({'ok':True,'result':result,'trace':{'records':len(rows) if action in ('inspect','normalize') else 0}},ensure_ascii=False,default=str))
 except Exception as e:print(json.dumps({'ok':False,'error':{'code':'INVALID_INPUT','message':str(e)}},ensure_ascii=False));sys.exit(2)
