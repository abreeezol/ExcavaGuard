#!/usr/bin/env python3
"""SIMULATED transport fixture. No engineering threshold or professional certification."""
import json
import sys
request = json.load(sys.stdin)
records = request.get("records") or []
from copy import deepcopy
from pathlib import Path
base = Path(__file__).resolve().parents[1]
payload = json.loads((base / 'payload-template.json').read_text(encoding='utf-8'))
items = []
for row in records:
    item = deepcopy(payload['items'][0])
    item.update(point_id=row.get('point_id', 'SIM-ONLY'), current=row.get('value'))
    items.append(item)
payload.update(project=request['options']['project'], items=items, review_queue=items)
payload['summary'].update(total=len(items), by_risk_level={'未知': len(items)}, by_data_origin={'simulated': len(items)}, abstain={'TEST_ONLY_NO_ENGINEERING_RULE':len(items)})
payload['context'].update(records=len(items), simulated_records=len(items))
print(json.dumps({'schema':'excavaguard.skill_result/v1','skill':'evaluate-thresholds','ok':True,'result':payload,'trace':{'records':len(items),'fixture':'SIMULATED_ONLY'}},ensure_ascii=False))
