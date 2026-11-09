import { z } from "zod";
import { requireAccess, requireProjectAction } from "@/server/access";
import { apiOk, apiErrorFromException } from "@/server/api/respond";
import { AppError } from "@/server/api/errors";
import { changeDecisionSchema } from "@/contracts/standard-changes";
import { readStandardChanges, analyzeStandardChange, decideStandardChange, previewStandardChange } from "@/server/standard-changes/service";
export const runtime="nodejs";
export const dynamic="force-dynamic";
export const maxDuration=300;
const input=z.discriminatedUnion("action",[
  z.strictObject({action:z.literal("preview"),id:z.uuid(),run_id:z.uuid(),expected_version:z.number().int().nonnegative()}),
  z.strictObject({action:z.literal("analyze"),document_id:z.uuid(),expected_version:z.number().int().nonnegative(),previous_id:z.uuid().optional()}),
  z.strictObject({action:z.enum(["publish","return","reject","disable"]),id:z.uuid(),expected_version:z.number().int().nonnegative(),note:z.string().trim().max(3000),decisions:z.array(changeDecisionSchema).max(40).default([])}),
]);
export async function GET(request:Request){try{return apiOk({state:await readStandardChanges(requireAccess(request).project_id)});}catch(e){return apiErrorFromException(e);}}
export async function POST(request:Request){try{
  if(Number(request.headers.get("content-length"))>256000)throw new AppError(413,"FILE_TOO_LARGE","变更请求过大。");
  const parsed=input.safeParse(await request.json().catch(()=>null));
  if(!parsed.success)throw new AppError(400,"INVALID_REQUEST","请检查变更操作、版本和逐条确认内容。");
  const body=parsed.data;
  const access=requireProjectAction(request,["analyze","preview"].includes(body.action)?"standards":"review");
  const actor=access.actor?.id??access.owner_id;
  if(body.action==="preview")return apiOk({preview:await previewStandardChange(access,body.id,body.run_id)});
  const state=body.action==="analyze"?await analyzeStandardChange(access.project_id,body.document_id,actor,body.expected_version,body.previous_id):
    await decideStandardChange(access.project_id,body.id,body.expected_version,actor,body.action,body.note,body.decisions);
  return apiOk({state});
}catch(e){return apiErrorFromException(e);}}
