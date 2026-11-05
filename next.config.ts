import type { NextConfig } from "next";
import { fileURLToPath } from "node:url";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  experimental: {
    agentUpgrade: "security",
  },
  // 上传、报告和运行记录必须由运行时存储提供，不随部署产物分发。
  outputFileTracingIncludes: {
    "/*": ["./engineering-adapters/**/*", "./source/adapter_runtime/**/*.py",
      "./确定性计算层/pipeline/**/*.py", "./确定性计算层/contracts/*.json",
      "./确定性计算层/standards/default/*.json", "./确定性计算层/tools/validate_daily_report_input.py",
      "./skills/*/scripts/**/*.py", "./rag/standard-status.json", "./src/server/agents/report-model.ts"],
  },
  outputFileTracingExcludes: {
    "/*": ["./var/**/*", "./.env", "./.env.*", "./.artifacts/**/*", "./engineering-adapters/verification-monitoring/**/*", "**/__pycache__/**"],
  },
  turbopack: {
    root: fileURLToPath(new URL(".", import.meta.url)),
  },
};

export default nextConfig;
