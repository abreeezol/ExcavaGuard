import { z } from "zod";
import { requireProjectAction } from "@/server/access";
import { getFile,materializeStoredFile } from "@/server/storage/monitoring-file-store";
import { inspectMonitoringFile } from "@/server/skills/parse-monitoring-data/runner";
import { projectEngineering } from "@/server/engineering-adapters/project";
import { recommendReportWindows } from "@/server/skills/report-windows";
import { apiOk,apiError,apiErrorFromException } from "@/server/api/respond";
export const runtime='nodejs';export const dynamic='force-dynamic';
export async function POST(request:Request){try{
 const access=requireProjectAction(request,'write');const body=z.strictObject({file_ids:z.array(z.uuid()).min(1).max(10).refine(a=>new Set(a).size===a.length)}).safeParse(await request.json().catch(()=>null));
 if(!body.success)return apiError(400,'INVALID_REQUEST','请选择1至10份不同监测文件。');
 const scene=projectEngineering(access.project_id);const dates:string[]=[];const metrics=new Map<string,{key:string;name:string;supported:boolean}>();
 for(const id of body.data.file_ids){const file=await getFile(id);if(!file||file.project_id!==access.project_id||file.kind!=='monitoring')return apiError(404,'FILE_NOT_FOUND','未找到当前工程监测文件。');
  const local=await materializeStoredFile(id);if(!local)return apiError(404,'FILE_NOT_FOUND','文件不可用。');
  try{const inspected=await inspectMonitoringFile(local.path,scene.adapter.id);const coverage=inspected.report.temporal_coverage as {dates?:string[]}|undefined;dates.push(...coverage?.dates??[]);for(const metric of (inspected.report.detected_metrics??[]) as Array<{key:string;name:string;supported:boolean}>)metrics.set(metric.key,metric);}finally{await local.cleanup();}
 }
 return apiOk({detected_metrics:[...metrics.values()],windows:recommendReportWindows(dates).filter(w=>scene.adapter.supported_reports.includes(w.type)),notice:'按输入有记录日期推荐；不代表所有测点完整覆盖。缺测仍须在报告中披露。'});
}catch(error){return apiErrorFromException(error);}}
