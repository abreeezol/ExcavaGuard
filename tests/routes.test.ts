import { afterEach, describe, expect, it, vi } from "vitest";
import { GET as healthGET } from "@/app/api/health/route";
import { GET as listMonitoringGET, POST as uploadMonitoringPOST } from "@/app/api/monitoring-files/route";
import { GET as sampleGET } from "@/app/api/monitoring-files/sample/route";
import { POST as runsPOST } from "@/app/api/runs/route";
import { POST as standardsPOST } from "@/app/api/standards/route";
import { apiErrorSchema } from "@/contracts/api";

/**
 * 接口边界测试（**不依赖 Python 引擎**）。
 *
 * 这里只验证协议层：媒体类型、JSON 解析、契约校验、资源不存在。
 * 需要真正调用引擎的端到端用例在 `tests/upload-and-run.test.ts`。
 */

const validRunInput = {
  project_id: "11111111-1111-4111-8111-111111111111",
  monitoring_file_id: "22222222-2222-4222-8222-222222222222",
  report_date: "2026-10-09",
  context: {
    safety_level: "一级",
    support_type: "地下连续墙",
    excavation_depth_m: 20,
  },
};

function jsonRequest(url: string, body: unknown, contentType = "application/json; charset=utf-8") {
  return new Request(url, {
    method: "POST",
    headers: { "Content-Type": contentType },
    body: JSON.stringify(body),
  });
}

afterEach(() => vi.unstubAllEnvs());

describe("存活检查", () => {
  it("不暴露密钥，也不表示外部依赖健康", async () => {
    vi.stubEnv("LLM_API_KEY", "test-only-secret-canary");
    const response = healthGET();
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual({
      status: "ok",
      service: "ExcavaGuard",
      stage: "scaffold",
    });
  });
});

describe("POST /api/runs · 协议与契约边界", () => {
  it("拒绝非 JSON 请求", async () => {
    const response = await runsPOST(
      new Request("http://localhost/api/runs", { method: "POST", body: "invalid" }),
    );
    expect(response.status).toBe(415);
    expect(apiErrorSchema.parse(await response.json()).error.code).toBe("UNSUPPORTED_MEDIA_TYPE");
  });

  it("非法 JSON 返回可读错误", async () => {
    const response = await runsPOST(
      new Request("http://localhost/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{",
      }),
    );
    expect(response.status).toBe(400);
    expect(apiErrorSchema.parse(await response.json()).error.code).toBe("INVALID_JSON");
  });

  it.each([
    ["空对象", {}],
    ["空正文值", null],
    ["数组", []],
    ["缺失项目", { ...validRunInput, project_id: undefined }],
    ["非法 UUID", { ...validRunInput, project_id: "not-a-project" }],
    ["无效日期", { ...validRunInput, report_date: "2026-02-29" }],
    ["日期含时间", { ...validRunInput, report_date: "2026-10-09T00:00:00Z" }],
    ["缺工程条件", { ...validRunInput, context: undefined }],
    ["非法安全等级", { ...validRunInput, context: { ...validRunInput.context, safety_level: "特级" } }],
    ["开挖深度为负", { ...validRunInput, context: { ...validRunInput.context, excavation_depth_m: -1 } }],
    ["工程条件含未知字段", { ...validRunInput, context: { ...validRunInput.context, foo: 1 } }],
    ["额外顶层字段", { ...validRunInput, threshold: "unconfirmed" }],
  ])("拒绝%s", async (_, input) => {
    const response = await runsPOST(jsonRequest("http://localhost/api/runs", input));
    expect(response.status).toBe(400);
    const body = apiErrorSchema.parse(await response.json());
    expect(body.error.code).toBe("INVALID_REQUEST");
  });

  it("接受合法闰日格式，但文件不存在时明确 404", async () => {
    const response = await runsPOST(
      jsonRequest("http://localhost/api/runs", { ...validRunInput, report_date: "2028-02-29" }),
    );
    expect(response.status).toBe(404);
    expect(apiErrorSchema.parse(await response.json()).error.code).toBe("FILE_NOT_FOUND");
  });

  it("未提供基坑深度是合法的（引擎会弃权而非放宽限值）", async () => {
    const response = await runsPOST(
      jsonRequest("http://localhost/api/runs", {
        ...validRunInput,
        context: { ...validRunInput.context, excavation_depth_m: null },
      }),
    );
    // 契约通过，只是文件不存在
    expect(response.status).toBe(404);
  });
});

describe("POST /api/monitoring-files · 上传边界", () => {
  it("拒绝非 multipart 请求", async () => {
    const response = await uploadMonitoringPOST(
      jsonRequest("http://localhost/api/monitoring-files", { hello: "world" }),
    );
    expect(response.status).toBe(415);
    expect(apiErrorSchema.parse(await response.json()).error.code).toBe("UNSUPPORTED_MEDIA_TYPE");
  });

  it("multipart 缺少 file 字段时 400", async () => {
    const form = new FormData();
    form.set("wrong_field", "x");
    const response = await uploadMonitoringPOST(
      new Request("http://localhost/api/monitoring-files", { method: "POST", body: form }),
    );
    expect(response.status).toBe(400);
    const body = apiErrorSchema.parse(await response.json());
    expect(body.error.code).toBe("INVALID_REQUEST");
    expect(body.error.fields).toContain("file");
  });

  it("GET 返回文件列表结构", async () => {
    vi.stubEnv("EXCAVAGUARD_UPLOAD_ROOT", "/tmp/excavaguard-test-empty-list");
    const response = await listMonitoringGET();
    expect(response.status).toBe(200);
    const body = (await response.json()) as { files: unknown[] };
    expect(Array.isArray(body.files)).toBe(true);
  });
});

describe("POST /api/standards · 上传边界", () => {
  it("拒绝不支持的媒体类型", async () => {
    const response = await standardsPOST(
      new Request("http://localhost/api/standards", { method: "POST", body: "x" }),
    );
    expect(response.status).toBe(415);
  });

  it("结构不合法时 400 INVALID_STANDARD", async () => {
    const response = await standardsPOST(
      jsonRequest("http://localhost/api/standards", { payload: { source_id: "X" } }),
    );
    expect(response.status).toBe(400);
    expect(apiErrorSchema.parse(await response.json()).error.code).toBe("INVALID_STANDARD");
  });

  it("metrics 为空时 400", async () => {
    const response = await standardsPOST(
      jsonRequest("http://localhost/api/standards", {
        payload: { source_id: "X", source_label: "Y", metrics: {} },
      }),
    );
    expect(response.status).toBe(400);
    expect(apiErrorSchema.parse(await response.json()).error.code).toBe("INVALID_STANDARD");
  });
});

describe("GET /api/monitoring-files/sample · 示例数据", () => {
  it("返回带 BOM 的 CSV，且不含派生列", async () => {
    const response = sampleGET();
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("text/csv");
    // 注意：response.text() 会按规范剥掉 BOM，必须查原始字节
    const bytes = new Uint8Array(await response.arrayBuffer());
    expect([bytes[0], bytes[1], bytes[2]]).toEqual([0xef, 0xbb, 0xbf]);
    const text = new TextDecoder("utf-8").decode(bytes);
    expect(text).toContain("测点编号,观测日期,监测项目,本次观测值,单位,方向");
    // 关键：示例里**没有** baseline_value / previous_value / interval_days
    expect(text).not.toContain("baseline_value");
    expect(text).not.toContain("previous_value");
    expect(text).not.toContain("interval_days");
    expect(text).toContain("WTHD-01");
  });
});
