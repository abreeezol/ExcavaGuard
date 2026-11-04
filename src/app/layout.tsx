import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ExcavaGuard · 工程监测日报助手",
  description: "汇集监测数据与规范，辅助工程师整理和复核可追溯的监测报告草稿。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
