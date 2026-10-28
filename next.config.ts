import type { NextConfig } from "next";
import { fileURLToPath } from "node:url";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  experimental: {
    agentUpgrade: "security",
  },
  // 上传、报告和运行记录必须由运行时存储提供，不随部署产物分发。
  outputFileTracingExcludes: {
    "/*": ["./var/**/*", "./.env", "./.env.*", "./.artifacts/**/*"],
  },
  turbopack: {
    root: fileURLToPath(new URL(".", import.meta.url)),
  },
};

export default nextConfig;
