"""Select the requested day after full-history calculations; validate the handoff."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'确定性计算层/pipeline'))
sys.path.insert(0,str(ROOT/'确定性计算层/tools'))
from period_reports import day_of
from orchestrator import _summarize_report_items
from validate_daily_report_input import validate
RANK={'未知':-1,'正常':0,'关注':1,'预警':2,'报警':3,'危险报警':4}

def finalize(req):
    p=req['payload']
    if not isinstance(p.get('items'),list) or not isinstance(p.get('project'),dict):raise ValueError('事实载荷不完整')
    day=req.get('report_date')
    if not p.get('period') and day:
        p['items']=[x for x in p['items'] if day_of(x.get('timestamp'))==day]
        if not p['items']:raise ValueError('所选报告日没有观测，不能生成空白正常日报')
        p['summary']=_summarize_report_items(p['items'])
        p['alerts']=[i for i in p['items'] if RANK.get(i.get('risk_level'),-1)>=2]
        p['review_queue']=[i for i in p['items'] if i.get('needs_review') or i.get('risk_level')=='未知']
        p['context']['records']=len(p['items'])
        p['context']['item_date']=day
        p['context']['real_records']=sum(i.get('data_origin')=='real' for i in p['items'])
        p['context']['simulated_records']=sum(i.get('data_origin')=='simulated' for i in p['items'])
    problems=validate(p)
    if problems:raise ValueError('报告事实载荷不符合冻结契约：'+'；'.join(problems[:5]))
    return p
if __name__=='__main__':
    try:
        result=finalize(json.load(sys.stdin))
        print(json.dumps({'schema':'excavaguard.skill_result/v1','skill':'prepare-engineering-facts','ok':True,'result':result},ensure_ascii=False,allow_nan=False))
    except (ValueError,TypeError,KeyError) as e:
        print(json.dumps({'ok':False,'error':{'code':'DATA_QUALITY','message':str(e)}},ensure_ascii=False));sys.exit(1)
