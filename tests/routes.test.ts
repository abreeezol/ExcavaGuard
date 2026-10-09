import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "@/app/api/health/route";
import { POST } from "@/app/api/runs/route";
import { apiErrorSchema } from "@/contracts/api";

const validInput = {
  project_id: "11111111-1111-4111-8111-111111111111",
  monitoring_file_id: "22222222-2222-4222-8222-222222222222",
  report_date: "2026-10-09",
};

function request(body: unknown) {
  return new Request("http://localhost/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify(body),
  });
}

afterEach(() => vi.unstubAllEnvs());

describe("初始化接口边界", () => {
  it("存活检查不暴露密钥，也不表示外部依赖健康", async () => {
    vi.stubEnv("LLM_API_KEY", "test-only-secret-canary");
    const response = GET();
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual({
      status: "ok",
      service: "ExcavaGuard",
      stage: "scaffold",
    });
  });

  it("合法输入明确返回未实现，不伪造运行成功", async () => {
    const response = await POST(request(validInput));
    expect(response.status).toBe(501);
    expect(response.headers.get("cache-control")).toBe("no-store");
    const body = apiErrorSchema.parse(await response.json());
    expect(body.error.code).toBe("FEATURE_NOT_IMPLEMENTED");
    expect(body).not.toHaveProperty("run_id");
    expect(body).not.toHaveProperty("report");
  });

  it.each([
    ["空对象", {}],
    ["空正文值", null],
    ["数组", []],
    ["缺失项目", { ...validInput, project_id: undefined }],
    ["空文件标识", { ...validInput, monitoring_file_id: "" }],
    ["非法 UUID", { ...validInput, project_id: "not-a-project" }],
    ["无效日期", { ...validInput, report_date: "2026-02-29" }],
    ["日期含时间", { ...validInput, report_date: "2026-10-09T00:00:00Z" }],
    ["额外工程字段", { ...validInput, threshold: "unconfirmed" }],
  ])("拒绝%s", async (_, input) => {
    const response = await POST(request(input));
    expect(response.status).toBe(400);
    const body = apiErrorSchema.parse(await response.json());
    expect(body.error.code).toBe("INVALID_REQUEST");
  });

  it("接受合法闰日的格式，但仍拒绝创建任务", async () => {
    expect((await POST(request({ ...validInput, report_date: "2028-02-29" }))).status).toBe(501);
  });

  it("非法 JSON 返回可读错误", async () => {
    const response = await POST(new Request("http://localhost/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{",
    }));
    expect(response.status).toBe(400);
    expect(apiErrorSchema.parse(await response.json()).error.code).toBe("INVALID_JSON");
  });

  it("拒绝非 JSON 请求", async () => {
    const response = await POST(new Request("http://localhost/api/runs", {
      method: "POST",
      body: "invalid",
    }));
    expect(response.status).toBe(415);
    expect(apiErrorSchema.parse(await response.json()).error.code).toBe("UNSUPPORTED_MEDIA_TYPE");
  });
});
