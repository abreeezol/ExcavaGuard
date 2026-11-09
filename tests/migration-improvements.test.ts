import { relevantStandardEvidence } from "@/server/agents/standard-review";
import { readScenePolicy } from "@/server/engineering-adapters/registry";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { describe,it,expect,beforeEach,afterEach,vi } from 'vitest';
import { mkdtempSync,rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { recommendReportWindows } from '@/server/skills/report-windows';
import { contextDocumentSchema } from '@/contracts/project-context';
import { analyzeWorkCondition } from '@/server/skills/analyze-work-condition/runner';
import { retrieveSimilarCases } from '@/server/skills/retrieve-similar-cases/runner';
import { POST as uploadContext,GET as listContext } from '@/app/api/project-context/route';
import { GET as reviewGet,POST as reviewPost } from '@/app/api/professional-review/route';
import { DEFAULT_PROJECT_ID } from '@/contracts/access';
let root:string;
beforeEach(()=>{root=mkdtempSync(join(tmpdir(),'migration-more-'));vi.stubEnv('EXCAVAGUARD_ACCESS_FILE',join(root,'access.json'));vi.stubEnv('EXCAVAGUARD_PROJECT_CONTEXT_ROOT',join(root,'context'));vi.stubEnv('EXCAVAGUARD_REVIEW_ROOT',join(root,'reviews'));vi.stubEnv('EXCAVAGUARD_ACCESS_PASSWORD','');vi.stubEnv('EXCAVAGUARD_PROJECT_ID',DEFAULT_PROJECT_ID);});
afterEach(()=>{vi.unstubAllEnvs();rmSync(root,{recursive:true,force:true});});
function doc(records:unknown[],kind='work_condition'){return contextDocumentSchema.parse({kind,title:'SIMULATED测试资料',records,document_id:crypto.randomUUID(),project_id:DEFAULT_PROJECT_ID,adapter_id:'foundation-pit',created_at:new Date().toISOString(),sha256:'a'.repeat(64),uploaded_by:'SIMULATED'});}
describe('周期推荐、资料接入、空间与评价留痕',()=>{
 it('推荐自然月/周/日，缺失日期保留披露，不把阶段月报冒充整月',()=>{
  const dates=Array.from({length:31},(_,i)=>`2026-10-${String(i+1).padStart(2,'0')}`).filter(d=>d!=='2026-10-05');
  const windows=recommendReportWindows(dates);expect(windows.some(w=>w.type==='monthly'&&w.missing_days.includes('2026-10-05'))).toBe(true);expect(windows.some(w=>w.type==='weekly')).toBe(true);
  expect(recommendReportWindows(['2026-10-02','2026-10-03']).some(w=>w.type==='monthly')).toBe(false);expect(recommendReportWindows(['2026-10-02'])[1].label).toContain('阶段月报');
 });
 it('上传CSV保留行号、结束时间与原文件指纹',async()=>{
  const form=new FormData();form.set('kind','work_condition');form.set('file',new File(['时间,结束时间,区段,作业内容,记录人\n2026-10-02 08:00:00,2026-10-02 12:00:00,A,SIMULATED作业,模拟甲\n'],'work.csv'));
  const response=await uploadContext(new Request('http://localhost/api/project-context',{method:'POST',body:form}));expect(response.status).toBe(201);const d=(await response.json()).document;expect(d.records[0]).toMatchObject({section:'A',source_location:'CSV第2行',end_timestamp:'2026-10-02 12:00:00'});expect(d.source_sha256).toMatch(/^[a-f0-9]{64}$/);expect((await (await listContext(new Request('http://localhost/api/project-context'))).json()).documents).toHaveLength(1);
 });
 it('可搜索PDF案例保留页码与原文件，扫描空白页拒绝假成功',async()=>{
  const create=(blank=false)=>execFileSync(resolve('.venv/bin/python'),['-c',`from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
import sys
w=PdfWriter();p=w.add_blank_page(612,792)
${blank?'':"font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')});p[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):w._add_object(font)})});s=DecodedStreamObject();s.set_data(b'BT /F1 12 Tf 50 700 Td (SIMULATED ground_settlement case review source) Tj ET');p[NameObject('/Contents')]=w._add_object(s)"}
import io
b=io.BytesIO();w.write(b);sys.stdout.buffer.write(b.getvalue())`]);
  const upload=async(blank=false)=>{const form=new FormData();form.set('kind','case');form.set('file',new File([create(blank)],'case.pdf'));return uploadContext(new Request('http://localhost/api/project-context',{method:'POST',body:form}));};
  const response=await upload();expect(response.status).toBe(201);expect((await response.json()).document.records[0].source_location).toContain('PDF第1页');expect((await upload(true)).status).toBe(400);
 });
 it('区段别名和已确认测点台账用于关联；台账与原观测冲突时待核',()=>{
  const payload={project:{report_date:'2026-10-02',professional_parameters:{section_aliases:{一区:'A'},point_sections:{P:'A'}}},items:[{point_id:'P',timestamp:'2026-10-02',source_metadata:{section_id:'A'}}]};
  const records=[doc([{timestamp:'2026-10-02',section:'一区',text:'SIMULATED'}])];expect(analyzeWorkCondition(payload,records).links).toHaveLength(1);
  payload.items[0].source_metadata.section_id='B';expect(analyzeWorkCondition(payload,records).pending).toHaveLength(1);
 });
 it('区间策略逐个观测时次关联，不能按天去重漏掉白天工况',()=>{
  const payload={project:{report_date:'2026-10-02',engineering_adapter:{id:'tunnel-shield'}},items:[{point_id:'P',metric_key:'ground_settlement',timestamp:'2026-10-02 00:00:00',source_metadata:{section_id:'A'}},{point_id:'P',metric_key:'ground_settlement',timestamp:'2026-10-02 12:00:00',source_metadata:{section_id:'A'}}]};
  const documents=[{...doc([{timestamp:'2026-10-02 08:00:00',end_timestamp:'2026-10-02 17:00:00',section:'A',text:'模拟作业'}]),adapter_id:'tunnel-shield'}];
  const result=analyzeWorkCondition(payload,documents);expect(result.links).toHaveLength(1);expect(result.links[0].item_index).toBe(1);
 });
 it('案例条件冲突排除，明确匹配工法和土层的案例优先',()=>{
  const payload={project:{professional_parameters:{case_context:{method:'盾构',soil:'黏土'}}},items:[{metric_key:'ground_settlement',metric_name:'地表沉降'}]};
  const d=doc([{text:'地表沉降',method:'矿山法',metric_keys:['ground_settlement']},{text:'地表沉降',method:'盾构',soil:'黏土',metric_keys:['ground_settlement']},{text:'地表沉降',metric_keys:['ground_settlement']}],'case');
  const result=retrieveSimilarCases(payload,[d]);expect(result.cases).toHaveLength(2);expect(result.cases[0].matched_conditions).toEqual(['method','soil']);
 });
 it('盾构场景自动带入已知工法，矿山法案例不得混入',()=>{
  const payload={project:{engineering_adapter:{id:'tunnel-shield'}},items:[{metric_key:'ground_settlement',metric_name:'地表沉降'}]};
  const d=doc([{text:'地表沉降',method:'矿山法'},{text:'地表沉降',method:'盾构'}],'case');
  expect(retrieveSimilarCases(payload,[d]).cases).toHaveLength(1);
 });
 it('项目上传的旧规范也不能绕过已知废止条文过滤',()=>{
  const item={id:'SIMULATED',provider:'project' as const,text:'9.1.1 监测应制定预警标准。',score:1,matched_terms:[],metadata:{standard_name:'城市轨道交通工程监测技术规范',standard_version:'GB50911-2013',clause:'9.1.1',source_location:'SIMULATED',applicability:['监测'],effective_status:'active' as const}};
  expect(relevantStandardEvidence(item,['监测'],readScenePolicy('tunnel-shield'))).toBe(false);
  expect(relevantStandardEvidence({...item,metadata:{...item.metadata,standard_version:'GB50490-2009'}},['监测'],readScenePolicy('tunnel-shield'))).toBe(false);
  expect(relevantStandardEvidence({...item,text:'9.1.2 监测应开展复核。',metadata:{...item.metadata,clause:'9.1.2'}},['监测'],readScenePolicy('tunnel-shield'))).toBe(true);
 });
 it('评价必须逐项提交并绑定版本，初始状态保持待工程师确认',async()=>{
  const initial=await (await reviewGet(new Request('http://localhost/api/professional-review'))).json();expect(initial.status).toBe('pending_engineer_review');
  const body={suite_hash:initial.suite_hash,adapter_digest:initial.adapter_digest,expected_revision:0,source_reference:'SIMULATED测试复核记录，不是真实工程师确认',evaluations:initial.suite.cases.map((c:{case_id:string})=>({case_id:c.case_id,decision:'pass',comment:'SIMULATED'}))};
  const request=()=>new Request('http://localhost/api/professional-review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  expect((await reviewPost(request())).status).toBe(200);expect((await reviewPost(request())).status).toBe(409);
 });
});
