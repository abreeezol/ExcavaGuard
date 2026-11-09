"""Offline, restartable OCR of every declared tunnel PDF; publish only after complete coverage."""
from pathlib import Path
import hashlib,json,sqlite3,re,os,sys,shutil,argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import pymupdf as fitz
ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'var/rag/tunnel-shield'
OCR=None

def meaningful(text):
 for watermark in ('住房城乡建设部信息公开','浏览专用','www.mohurd.gov.cn'):text=text.replace(watermark,'')
 return len(re.sub(r'\s','',text))>=30 and len(re.findall(r'[\u3400-\u9fffA-Za-z]',text))>=15

def page_text(task):
 global OCR
 path,index,cache=task;p=Path(cache)
 if p.exists():
  old=json.loads(p.read_text())
  if old.get('method')=='ocr' or meaningful(old.get('text','')):return old
 pdf=fitz.open(path);page=pdf[index];text=page.get_text();method='text';scores=[]
 if not meaningful(text):
  if OCR is None:
   from rapidocr_onnxruntime import RapidOCR
   OCR=RapidOCR(intra_op_num_threads=1,inter_op_num_threads=1)
  pix=page.get_pixmap(matrix=fitz.Matrix(1.7,1.7));result,_=OCR(pix.tobytes('png'))
  lines=[r for r in (result or []) if r[2]>=.65];text='\n'.join(r[1] for r in lines);scores=[r[2] for r in lines];method='ocr'
 value={'page':index+1,'text':text,'method':method,'min_confidence':min(scores) if scores else None,'requires_human_review':method=='ocr'}
 temporary=p.with_suffix('.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False));os.replace(temporary,p);return value

def load_sources():
 declared=json.loads((ROOT/'tools/knowledge/tunnel-sources.json').read_text());directory=ROOT.parent/declared['source_directory'];actual={str(p.relative_to(directory)) for p in directory.rglob('*.pdf')};expected={s['relative_path'] for s in declared['sources']}
 if actual!=expected:raise ValueError('目录与声明不同，先更新tunnel-sources.json；未声明='+str(actual-expected))
 return directory,declared['sources']

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=8);parser.add_argument('--extract-only',action='store_true');args=parser.parse_args();DEST.mkdir(parents=True,exist_ok=True)
 directory,sources=load_sources();tasks=[];prepared=[]
 for s in sources:
  path=directory/s['relative_path'];sha=hashlib.sha256(path.read_bytes()).hexdigest();cache=DEST/'pages'/sha;cache.mkdir(parents=True,exist_ok=True);count=len(fitz.open(path));prepared.append((s,sha,cache,count))
  tasks.extend((str(path),i,str(cache/f'{i+1:04}.json')) for i in range(count))
 with ProcessPoolExecutor(max_workers=max(1,min(args.workers,32))) as pool:
  pending={pool.submit(page_text,t):t for t in tasks}
  for n,f in enumerate(as_completed(pending),1):
   f.result()
   if n%25==0 or n==len(tasks):print('OCR_PROGRESS',n,'/',len(tasks),flush=True)
 if args.extract_only:return
 for source,sha,_,_ in prepared:
  if hashlib.sha256((directory/source['relative_path']).read_bytes()).hexdigest()!=sha:raise ValueError('源PDF在构建中发生变化，未发布')
 rows=[];metadata=[];catalogue=[]
 for s,sha,cache,count in prepared:
  excluded=[];empty=[];ocr_pages=0;start_count=len(rows)
  for i in range(count):
   page=json.loads((cache/f'{i+1:04}.json').read_text());normalized=re.sub(r'\s','',page['text']);ocr_pages+=page['method']=='ocr'
   if any(re.search(r'(?<![\d.])'+re.escape(c)+r'(?![\d.])',normalized) for c in s['revoked_clauses']):excluded.append(page['page']);continue
   if len(normalized)<20:empty.append(page['page']);continue
   for start in range(0,len(page['text']),1400):
    text=page['text'][start:start+1600]
    if not text.strip():continue
    eid=f'{s["code"]}:p{page["page"]}:{start//1400}'
    meta={'standard_name':s['name'],'standard_version':s['code'],'clause':f'PDF第{page["page"]}页（候选，条款待核）','source_location':f'{Path(s["relative_path"]).name} PDF第{page["page"]}页；SHA256 {sha}；{page["method"]}待原页复核','applicability':['隧道',*s['systems'],*s['methods'],*s['stages'],*([s['special_condition']] if s['special_condition'] else [])],'effective_status':s['effective_status'],'content_sha256':hashlib.sha256(text.encode()).hexdigest()}
    rows.append((eid,text,json.dumps(meta,ensure_ascii=False)))
  entry={**s,'source_sha256':sha,'page_count':count,'record_count':len(rows)-start_count,'excluded_pages':excluded,'empty_pages':empty,'ocr_pages':ocr_pages,'extraction':'page_candidates_require_original_review'};metadata.append(entry)
  if entry['record_count']==0:raise ValueError('规范没有检索片段：'+s['code'])
  catalogue.append({'code':s['code'],'name':s['name'],'category':'tunnel','scope_note':s['status_note'],'systems':s['systems'],'methods':s['methods'],'stages':s['stages'],'special_condition':s['special_condition'],'conditions':{'system':s['systems'],'method':s['methods'],'stage':s['stages'],**({'special':[s['special_condition']]} if s['special_condition'] else {})}})
 temporary=DEST/'building.sqlite3'
 if temporary.exists():temporary.unlink()
 db=sqlite3.connect(temporary);db.execute('CREATE TABLE evidence(id TEXT PRIMARY KEY,text TEXT,metadata TEXT)');db.executemany('INSERT INTO evidence VALUES(?,?,?)',rows);db.commit();db.close();os.replace(temporary,DEST/'knowledge.sqlite3')
 version=hashlib.sha256((DEST/'knowledge.sqlite3').read_bytes()).hexdigest();manifest={'schema':'excavaguard.knowledge_manifest/v1','adapter_id':'tunnel-monitoring','index_sha256':version,'record_count':len(rows),'source_count':len(sources),'page_count':len(tasks),'sources':metadata,'notice':'全部原件均建候选；废止仅历史检索、unknown不得作为已确认依据；OCR和条件适用性须原页复核。'}
 for adapter_id in ['tunnel-monitoring']:
  base=ROOT/'engineering-adapters'/adapter_id;(base/'knowledge').mkdir(parents=True,exist_ok=True);shutil.copy2(DEST/'knowledge.sqlite3',base/'knowledge/knowledge.sqlite3');(base/'knowledge-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');(base/'catalog.json').write_text(json.dumps({'standards':catalogue},ensure_ascii=False,indent=2)+'\n');(base/'standard-status.json').write_text(json.dumps({'standards':{s['code']:{'effective_status':s['effective_status'],'preferred_category':'tunnel'} for s in sources}},ensure_ascii=False,indent=2)+'\n')
 print('COMPLETE',len(sources),len(tasks),len(rows),version,flush=True)
if __name__=='__main__':main()
