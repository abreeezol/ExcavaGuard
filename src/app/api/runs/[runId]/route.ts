import { deleteRunRequestSchema } from "@/contracts/runs";
import { requireAccess, requireProjectAction } from "@/server/access";
import { apiError, apiErrorFromException, apiOk } from "@/server/api/respond";
import { deleteRun, readRun } from "@/server/storage/run-store";
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

export async function DELETE(request: Request, context: { params: Promise<{ runId: string }> }) {
  try {
    const access = requireProjectAction(request, "delete");
    const parsed = deleteRunRequestSchema.safeParse({
      expected_revision: Number(new URL(request.url).searchParams.get("expected_revision")),
    });
    if (!parsed.success) {
      return apiError(400, "INVALID_REQUEST", "请提供要删除的当前运行修订号。");
    }
    const { runId } = await context.params;
    return apiOk(await deleteRun(runId, parsed.data.expected_revision, access));
  } catch (error) {
    return apiErrorFromException(error);
  }
}
