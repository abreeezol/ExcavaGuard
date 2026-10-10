import { apiError, apiErrorFromException, apiOk } from "@/server/api/respond";
import { EngineError, EngineUnavailableError } from "@/server/skills/python-bridge";
import { inspectMonitoringFile } from "@/server/skills/parse-monitoring-data/runner";
import { listFiles, localPathOf, saveFile } from "@/server/storage/monitoring-file-store";
import type { ReadReport } from "@/contracts/monitoring-files";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** 列出已上传的监测数据文件（新→旧）。 */
export async function GET() {
  return apiOk({ files: await listFiles("monitoring") });
}

/**
 * 上传监测数据文件（multipart/form-data，字段名 `file`）。
 *
 * 落盘后立即调用引擎的读取器做解析检查，把「编码 / 分隔符 / 列映射 / 缺必填列」
 * 一并返回，用户不必等到运行分析才知道文件能不能用。
 * **解析检查失败不影响上传结果** —— 文件已保存，报告里带上具体原因。
 */
export async function POST(request: Request) {
  const mediaType = request.headers.get("content-type")?.split(";")[0].trim().toLowerCase();
  if (mediaType !== "multipart/form-data") {
    return apiError(415, "UNSUPPORTED_MEDIA_TYPE", "请使用 multipart/form-data 上传文件。");
  }

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return apiError(400, "INVALID_REQUEST", "无法解析 multipart 表单。");
  }

  const file = form.get("file");
  if (!(file instanceof File)) {
    return apiError(400, "INVALID_REQUEST", "缺少 file 字段。", { fields: ["file"] });
  }

  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const stored = await saveFile({
      kind: "monitoring",
      originalName: file.name,
      bytes,
      mediaType: file.type,
    });

    let readReport: ReadReport | null = null;
    const abs = await localPathOf(stored.file_id);
    if (abs) {
      try {
        readReport = (await inspectMonitoringFile(abs)).report;
      } catch (error) {
        if (error instanceof EngineError || error instanceof EngineUnavailableError) {
          readReport = { ok: false, errors: [error.message] };
        } else {
          throw error;
        }
      }
    }

    return apiOk({ file: stored, read_report: readReport }, 201);
  } catch (error) {
    return apiErrorFromException(error);
  }
}
