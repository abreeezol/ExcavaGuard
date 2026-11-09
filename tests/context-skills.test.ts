import { mkdtempSync, rmSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_PROJECT_ID } from "@/contracts/access";
import { contextDocumentSchema } from "@/contracts/project-context";
import { buildContextSnapshot } from "@/server/context/snapshot";
import { runJudgement } from "@/server/skills/evaluate-thresholds/runner";
import { executeAgentRun } from "@/server/agents/executor";
import { GET,POST,PATCH } from "@/app/api/project-context/route";
import { listProjectContext } from "@/server/context/library";
const P=DEFAULT_PROJECT_ID;
let root:string;
beforeEach(()=>{root=mkdtempSync(join(tmpdir(),'context-skills-'));vi.stubEnv('EXCAVAGUARD_ACCESS_FILE',join(root,'access.json'));vi.stubEnv('EXCAVAGUARD_ACCESS_PASSWORD','');vi.stubEnv('EXCAVAGUARD_PROJECT_CONTEXT_ROOT',join(root,'context'));vi.stubEnv('EXCAVAGUARD_PROJECT_ID',P);});
afterEach(()=>{vi.unstubAllEnvs();rmSync(root,{recursive:true,force:true});});
const payload={schema:'excavaguard.daily_report_input/v1',project:{report_date:'2026-10-02'},items:[{point_id:'SIM-P',metric_key:'wall_top_horizontal_displacement',metric_name:'围护墙顶部水平位移',timestamp:'2026-10-02',source_metadata:{section_id:'A'}}]};
function document(kind:'case'|'work_condition'|'patrol',records:unknown[],title:string=kind) {
 return contextDocumentSchema.parse({document_id:crypto.randomUUID(),project_id:P,adapter_id:'foundation-pit',sha256:'a'.repeat(64),created_at:new Date().toISOString(),uploaded_by:'SIMULATED',kind,title,records});
}
const request=(body?:unknown,method='POST')=>new Request('http://localhost/api/project-context',body?{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);
describe('案例检索与工况分析',()=>{
 it('缺资料不阻塞，不把巡视未提供写成正常',()=>{const context=buildContextSnapshot(P,payload,[]);expect(context.case_retrieval.status).toBe('not_provided');expect(context.work_analysis.patrol_status).toBe('not_provided');expect(context.work_analysis.links).toEqual([]);});
 it('同日同区段关联，不同区段排除，位置不明待核，其他日期排除',()=>{
  const doc=document('work_condition',[{text:'A区作业',timestamp:'2026-10-02',section:'A'},{text:'B区作业',timestamp:'2026-10-02',section:'B'},{text:'位置未知',timestamp:'2026-10-02'},{text:'其他日期',timestamp:'2026-10-03',section:'A'}]);
  const analysis=buildContextSnapshot(P,payload,[doc]).work_analysis;
  expect(analysis.links).toHaveLength(1);expect(analysis.links[0].text).toBe('A区作业');expect(analysis.pending).toHaveLength(1);expect(analysis.notice).toContain('不改变监测风险');
 });
 it('周期报告关联每日冻结观测，不能只分析最严重一天',()=>{
  const periodPayload={...payload,items:[{...payload.items[0],timestamp:'2026-10-03'}],period:{start_date:'2026-10-01',end_date:'2026-10-03',daily_items:[payload.items[0]]}};
  const doc=document('work_condition',[{timestamp:'2026-10-02',section:'A',text:'模拟日内作业'}]);
  expect(buildContextSnapshot(P,periodPayload,[doc]).work_analysis.links).toHaveLength(1);
 });
 it('相同时间位置同一断言互相矛盾时保留冲突，不判断原因',()=>{
  const docs=[document('patrol',[{text:'记录无渗水',timestamp:'2026-10-02',section:'A',assertion_key:'seepage',assertion_value:false}]),document('work_condition',[{text:'记录存在渗水',timestamp:'2026-10-02',section:'A',assertion_key:'seepage',assertion_value:true}])];
  const analysis=buildContextSnapshot(P,payload,docs).work_analysis;expect(analysis.conflicts).toHaveLength(1);expect(analysis.links).toHaveLength(2);
 });
 it('案例只按显式测项或关键词检索，非相关案例不使用，不能跨项目或场景',()=>{
  const doc=document('case',[{text:'水平位移发展与现场施工关系需核验'},{text:'无关材料采购记录'}]);
  expect(buildContextSnapshot(P,payload,[doc]).case_retrieval.cases).toHaveLength(1);
  expect(()=>buildContextSnapshot(P,payload,[{...doc,project_id:crypto.randomUUID()}])).toThrow('SCOPE_MISMATCH');
  expect(()=>buildContextSnapshot(P,payload,[{...doc,adapter_id:'verification-monitoring'}])).toThrow('SCOPE_MISMATCH');
 });
 it('真实上传、重复去重、停用与历史快照独立；错误输入不保存',async()=>{
  const body={kind:'case',title:'SIMULATED案例',records:[{text:'水平位移监测需复核'}]};
  const response=await POST(request(body));expect(response.status).toBe(201);const doc=(await response.json()).document;
  const frozen=buildContextSnapshot(P,payload,await listProjectContext(P));
  expect((await POST(request(body))).status).toBe(201);expect((await (await GET(request())).json()).documents).toHaveLength(1);
  expect((await PATCH(request({document_id:doc.document_id,active:false},'PATCH'))).status).toBe(200);
  expect(buildContextSnapshot(P,payload,await listProjectContext(P)).documents).toHaveLength(0);expect(frozen.documents).toHaveLength(1);
  expect((await POST(request({kind:'patrol',title:'缺少日期',records:[{text:'待核'}]}))).status).toBe(400);
 });
 it('辅助资料贯通三Agent模板、Excel/Markdown与独立审计，不修改冻结数值',async()=>{
  const computed=await runJudgement({context:{safety_level:'一级',support_type:'地下连续墙',excavation_depth_m:20},reportDate:'2026-10-02',records:[{point_id:'SIM-P',timestamp:'2026-10-01',metric:'wall_top_horizontal_displacement',value:0,unit:'mm',data_origin:'simulated'},{point_id:'SIM-P',timestamp:'2026-10-02',metric:'wall_top_horizontal_displacement',value:5,unit:'mm',data_origin:'simulated'}]});
  const support=buildContextSnapshot(P,computed.result,[document('case',[{text:'水平位移案例仅供关联参考'}],'SIMULATED历史案例'),document('work_condition',[{timestamp:'2026-10-02',point_id:'SIM-P',text:'SIMULATED作业记录'}])]);
  const execution=await executeAgentRun({enginePayload:computed.result,supportingContext:support,reportMode:'template'});
  const draft=execution.state.report_draft;
  try{
   expect(execution.state.audit_result?.valid).toBe(true);expect(execution.state.context_snapshot?.payload).toEqual(support);
   expect(execution.state.trace.some(t=>t.capability==='retrieve-similar-cases')).toBe(true);
   expect(execution.state.trace.some(t=>t.capability==='analyze-work-condition')).toBe(true);
   const cover=draft!.artifacts.find(a=>a.kind==='cover_markdown')!;const text=readFileSync(resolve(cover.relative_path),'utf8');expect(text).toContain('SIMULATED历史案例');expect(text).toContain('SIMULATED作业记录');expect(text).toContain('不证明因果');
   expect((execution.state.engine_snapshot.payload as {items:unknown}).items).toEqual((computed.result as {items:unknown}).items);
  }finally{if(draft?.artifacts[0])rmSync(dirname(resolve(draft.artifacts[0].relative_path)),{recursive:true,force:true});}
 });
 it('模拟三模型调用时辅助事实占位符可生成并通过真实Python文件审计',async()=>{
  const computed=await runJudgement({context:{safety_level:'一级',support_type:'地下连续墙',excavation_depth_m:20},reportDate:'2026-10-02',records:[{point_id:'SIM-P',timestamp:'2026-10-01',metric:'wall_top_horizontal_displacement',value:0,unit:'mm',data_origin:'simulated'},{point_id:'SIM-P',timestamp:'2026-10-02',metric:'wall_top_horizontal_displacement',value:5,unit:'mm',data_origin:'simulated'}]});
  const support=buildContextSnapshot(P,computed.result,[document('case',[{text:'水平位移案例仅供线索，不证明因果'}])]);
  const paragraph=(text='建议工程师核验。')=>({text,evidence_ids:[]});
  const roles:string[]=[];
  const execution=await executeAgentRun({enginePayload:computed.result,supportingContext:support,reportMode:'ai'},{
   retrieve:async request=>({status:'abstained',code:'EVIDENCE_NOT_FOUND',message:'SIMULATED无命中',notice:'SIMULATED',evidence:[],trace:{provider:'local',query:(request as {query:string}).query,filters:(request as {filters:{effective_status:"active"}}).filters??{},limit:(request as {limit:number}).limit??3,hit_count:0,evidence_ids:[]}}),
   model:async request=>{roles.push(request.role);return {model:'SIMULATED',usage:{input_tokens:1,output_tokens:1},object:request.role==='supervisor'?{focus_indices:[0],evidence_topics:(request.context as {evidence_topics:string[]}).evidence_topics}:request.role==='audit'?{issues:[]}:{work_condition:paragraph('工况与巡视资料未提供。'),analysis:[paragraph('参考案例：{{fact:project.supporting_context.case_retrieval.cases.0.excerpt}}，仅作为线索。')],recommendations:[paragraph()],limitations:[paragraph('案例不证明当前异常原因。')],appendix_analysis:[{form:'A',analysis:paragraph(),recommendation:paragraph()}]}};}
  });
  const draft=execution.state.report_draft;
  try{expect(execution.state.audit_result?.valid).toBe(true);expect(roles).toEqual(['supervisor','report-delivery','audit']);expect(draft?.payload).toBeTruthy();}
  finally{if(draft?.artifacts[0])rmSync(dirname(resolve(draft.artifacts[0].relative_path)),{recursive:true,force:true});}
 });

});
