import json,sys,sqlite3,hashlib,re,math
from collections import Counter
from pathlib import Path
r=json.load(sys.stdin)
try:
 root=Path(__file__).resolve().parents[3];adapter=r['adapter_id']
 if not re.fullmatch('[a-z][a-z0-9-]{1,63}',adapter):raise ValueError('适配器ID非法')
 m=json.loads((root/'engineering-adapters'/adapter/'manifest.json').read_text());path=(root/m['retrieval']['local_index']).resolve();path.relative_to(root/ 'engineering-adapters'/adapter/'knowledge') if 'engineering-adapters/' in m['retrieval']['local_index'] else path.relative_to(root/'var/rag')
 km=json.loads((root/m['knowledge_manifest']).read_text());sha=hashlib.sha256(path.read_bytes()).hexdigest()
 if sha!=km['index_sha256']:raise ValueError('知识库内容版本与清单不一致')
 scope=json.loads((root/m['standard_scope']).read_text()) if m.get('standard_scope') else {}
 parameters=r.get('scene_parameters') or {}
 db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True);query=r['query'];text=query['query'];terms=set(re.findall('[a-zA-Z0-9_-]+',text))
 for word in re.findall('[\u3400-\u9fff]+',text):terms.update(word[i:i+2] for i in range(len(word)-1))
 versions=query.get('filters',{}).get('standard_versions');out=[];revoked={s['code']:s['revoked_clauses'] for s in km['sources']}
 for eid,body,metadata in db.execute('SELECT id,text,metadata FROM evidence'):
  meta=json.loads(metadata)
  if versions and meta['standard_version'] not in versions:continue
  if meta['effective_status']!=query.get('filters',{}).get('effective_status','active'):continue
  skip=False
  for rule in scope.get('chunk_rules',[]) if r.get('enforce_scope',True) else []:
   value=parameters.get(rule['parameter']);selected=rule.get('expansions',{}).get(value,[value]);mentioned=[key for key,pattern in rule['patterns'].items() if re.search(pattern,body)]
   if mentioned and not any(k in selected for k in mentioned):skip=True;break
  if skip:continue
  normalized=re.sub(r'\s','',body)
  if meta['effective_status']=='active' and any(c=='*' or re.search(r'(?<![\d.])'+re.escape(c)+r'(?![\d.])',normalized) for c in revoked.get(meta['standard_version'],[])):continue
  matches=[t for t in terms if t in body]
  if matches:out.append({'id':eid,'text':body,'metadata':meta,'provider':'local','score':len(matches)/max(1,len(terms)),'matched_terms':sorted(matches)[:50]})
 # Deterministic BM25-style ranking over the scoped candidate texts, with character length normalization.
 if out:
  frequencies=Counter(t for e in out for t in e['matched_terms']);n=len(out);average=sum(len(e['text']) for e in out)/n
  for e in out:
   e['score']=sum(math.log(1+(n-frequencies[t]+.5)/(frequencies[t]+.5))*(e['text'].count(t)*2.2)/(e['text'].count(t)+1.2*(.25+.75*len(e['text'])/average)) for t in e['matched_terms'])
 out.sort(key=lambda e:(-e['score'],e['id']));print(json.dumps({'ok':True,'result':out[:query.get('top_k',3)]},ensure_ascii=False))
except Exception as e:print(json.dumps({'ok':False,'error':{'code':'INVALID_INPUT','message':str(e)}},ensure_ascii=False));sys.exit(2)
