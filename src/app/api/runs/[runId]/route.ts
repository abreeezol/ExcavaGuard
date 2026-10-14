import { requireAccess } from "@/server/access";
import { apiErrorFromException, apiOk } from "@/server/api/respond";
import { readRun } from "@/server/storage/run-store";
import { runView } from "@/server/runs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request, context: { params: Promise<{ runId: string }> }) {
  try {
    const access = requireAccess(request);
    const { runId } = await context.params;
    return apiOk(runView(await readRun(runId, access)));
  } catch (error) {
    return apiErrorFromException(error);
  }
}
