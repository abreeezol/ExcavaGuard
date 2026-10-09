import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ExcavaGuard · 监测日报工作台",
  description: "面向基坑监测工程师的日报草稿工作台。规则主判，证据可追溯，工程师复核。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
