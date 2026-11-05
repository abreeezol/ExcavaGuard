"""Parse auxiliary CSV/PDF; never infer engineering facts from filenames."""
import base64,csv,io,json,sys,re
r=json.load(sys.stdin)
try:
 data=base64.b64decode(r['bytes'],validate=True);ext=r['extension'];kind=r['kind'];records=[]
 if len(data)>20*1024*1024:raise ValueError('文件超过20MB')
 if ext=='.csv':
  text=None
  for enc in ['utf-8-sig','gb18030']:
   try:text=data.decode(enc);break
   except UnicodeDecodeError:pass
  if text is None:raise ValueError('CSV编码无法识别')
  aliases={'时间':'timestamp','开始时间':'timestamp','结束时间':'end_timestamp','区段':'section','测点':'point_id','测项':'metric_keys','作业内容':'text','现象':'text','记录人':'recorder','工法':'method','土层':'soil','阶段':'stage','地下水':'groundwater'}
  for i,row in enumerate(csv.DictReader(io.StringIO(text))):
   row={aliases.get(k.strip(),k.strip()):v.strip() for k,v in row.items() if k and v and v.strip()}
   allowed={'text','timestamp','end_timestamp','section','point_id','recorder','method','soil','stage','groundwater','assertion_key','assertion_value','metric_keys'}
   row={k:v for k,v in row.items() if k in allowed}
   if not row.get('text'):raise ValueError('CSV每条记录必须有text/作业内容/现象列')
   if 'metric_keys' in row:row['metric_keys']=[k.strip() for k in re.split('[,;|、]',row['metric_keys']) if k.strip()]
   if row.get('assertion_value') in ['true','false']:row['assertion_value']=json.loads(row['assertion_value'])
   row['source_location']=f'CSV第{i+2}行';records.append(row)
 elif ext=='.pdf':
  from pypdf import PdfReader
  reader=PdfReader(io.BytesIO(data))
  if reader.is_encrypted:raise ValueError('不支持加密PDF')
  if len(reader.pages)>300:raise ValueError('辅助资料PDF不能超过300页')
  if kind!='case':raise ValueError('PDF只支持案例；工况/巡视请用结构化CSV或JSON')
  empty=[]
  for i,page in enumerate(reader.pages):
   text=page.extract_text() or ''
   if len(re.sub(r'\s','',text))<20:empty.append(i+1);continue
   if len(re.findall(r'/G\d+',text))>10:raise ValueError('PDF字体乱码，请OCR后重试')
   for j in range(0,len(text),6000):records.append({'text':text[j:j+6000],'source_location':f'PDF第{i+1}页，片段{j//6000+1}'})
  if empty:raise ValueError(f'PDF有{len(empty)}页缺少可靠文字层，请OCR后重试，不能静默漏页')
 else:raise ValueError('不支持的格式')
 if not records or len(records)>200:raise ValueError('记录数量需在1至200之间')
 print(json.dumps({'ok':True,'result':{'records':records}},ensure_ascii=False))
except Exception as e:print(json.dumps({'ok':False,'error':{'code':'INVALID_INPUT','message':str(e)}}));sys.exit(2)
