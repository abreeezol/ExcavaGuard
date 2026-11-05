"""Execute approved project rules before the Agent snapshot; no arbitrary code/formulas."""
import json, sys, math
from pathlib import Path
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'确定性计算层/pipeline'))
from period_reports import period_statistics
RANK={'未知':-1,'正常':0,'关注':1,'预警':2,'报警':3,'危险报警':4}

def apply(payload, context, snapshot):
    payload=deepcopy(payload)
    period=payload.get('period')
    rows=period.get('daily_items',[]) if period else payload['items']
    for item in rows:
        applied=[]
        for rule in snapshot['rules']:
            if rule['metric_key']!=item['metric_key'] or (rule['point_ids'] and item['point_id'] not in rule['point_ids']):continue
            missing=[k for k in rule['conditions'] if context.get(k) in (None,'')]
            mismatch=[k for k,v in rule['conditions'].items() if k in context and (isinstance(context[k],bool)!=isinstance(v,bool) or context[k]!=v)]
            if missing or mismatch:
                applied.append({'rule_id':rule['id'],'status':'missing_conditions' if missing else 'not_applicable','conditions':missing or mismatch})
                continue
            value=item.get(rule['field'])
            unit=item.get('source_metadata',{}).get('units',{}).get(rule['field']) or ('mm/d' if rule['field']=='rate' and item.get('unit')=='mm' else item.get('unit'))
            # No recovery from invalid semantics, malformed units or blocked observations.
            allowed_missing={'MISSING_CONFIRMED_PROJECT_CRITERIA','NO_CONFIRMED_LIMIT','MISSING_RATE','MISSING_CUMULATIVE','NO_LIMIT','NO_APPLICABLE_RULE'}
            blocked=any(x not in allowed_missing for x in item.get('abstain',[]))
            if blocked or not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or unit!=rule['unit'] or value<0:
                applied.append({'rule_id':rule['id'],'status':'invalid_or_unsupported_value'})
                continue
            hit=value>=rule['threshold'] if rule['operator']=='>=' else value>rule['threshold']
            applied.append({'rule_id':rule['id'],'status':'triggered' if hit else 'not_triggered','source_label':rule['source_label']})
            item.setdefault('checks',[]).append({'type':rule['field'],'value':value,'limit':rule['threshold'],'unit':rule['unit'],
                'utilization':value/rule['threshold'],'verdict':rule['risk_level'] if hit else '未触发','limit_basis':rule['source_label'],
                'rule_id':rule['id'],'document_id':rule['document_id'],'clause':rule['clause'],'quote':rule['quote']})
            if hit and RANK.get(item['risk_level'],-1)<RANK[rule['risk_level']]:
                item['risk_level']=rule['risk_level']
                item['evidence']={'standard':rule['source_label'],'clause':rule['clause'],'note':'工程师确认的项目补充规则触发；不解除其他待核事项'}
                item['effective_standard']={'origin':'user_uploaded','source_id':rule['document_id'],'source_label':rule['source_label'],'origin_display':'项目补充规则'}
                item['rule_id']=rule['id']
            item['utilization']=max(item.get('utilization') or 0,value/rule['threshold'])
        item['project_rule_checks']=applied
        if any(x['status'] in ['missing_conditions','invalid_or_unsupported_value'] for x in applied):
            item['needs_review']=True
            item.setdefault('abstain',[]).append('PROJECT_RULE_NOT_EVALUATED')
            item.setdefault('abstain_reasons',[]).append('项目补充规则缺少适用条件或有效量值，未能完成核查')
            if RANK.get(item['risk_level'],-1)<RANK['预警']:item['risk_level']='未知'
    if period:
        spec={k:period[k] for k in ['type','start_date','end_date']}
        stats,reps=period_statistics(rows,spec)
        payload['period']={**period,**stats,'daily_items':rows}
        payload['items']=reps
    from orchestrator import _summarize_report_items
    items=payload['items']
    payload['summary']=_summarize_report_items(items)
    payload['alerts']=[i for i in items if RANK.get(i['risk_level'],-1)>=2]
    payload['review_queue']=[i for i in rows if i.get('needs_review') or i['risk_level']=='未知']
    payload['project']['rule_change_snapshot']=snapshot
    payload.setdefault('standards_sources',[]).extend({'source_id':r['document_id'],'source_label':r['source_label'],'source_type':'project_requirement'} for r in snapshot['rules'] if not any(s.get('source_id')==r['document_id'] for s in payload.get('standards_sources',[])))
    notices=[f"项目补充规则版本：{snapshot['version']}；与原判据并行执行，不降低原等级。"]
    notices.extend(f"采用要求：{r['source_label']}，{r['metric_key']} {r['field']} {r['operator']} {r['threshold']} {r['unit']}，适用条件：{json.dumps(r['conditions'],ensure_ascii=False)}。" for r in snapshot['rules'])
    notices.extend('待核：'+gap for gap in snapshot.get('gaps',[]))
    payload['note']=payload.get('note','')+' '+' '.join(notices)
    return payload

if __name__=='__main__':
    try:
        req=json.load(sys.stdin)
        result=apply(req['payload'],req['context'],req['snapshot'])
        print(json.dumps({'schema':'excavaguard.skill_result/v1','skill':'review-standard-changes','ok':True,'result':result},ensure_ascii=False))
    except Exception:
        print(json.dumps({'ok':False,'error':{'code':'INVALID_STANDARD','message':'项目规则执行失败；未交付未经核验结果。'}},ensure_ascii=False))
        sys.exit(1)
