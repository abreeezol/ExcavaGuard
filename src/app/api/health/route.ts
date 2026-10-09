export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// 仅作进程存活检查，不探测外部服务、不暴露配置。
export function GET() {
  return Response.json(
    { status: "ok", service: "ExcavaGuard", stage: "scaffold" },
    { headers: { "Cache-Control": "no-store" } },
  );
}
