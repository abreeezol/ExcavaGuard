import type { Metadata } from "next";
import { WorkbenchClient } from "./workbench-session";

export const metadata: Metadata = {
  title: "工程监测日报助手 · ExcavaGuard",
  description:
    "上传监测数据与用户规范，运行确定性计算与风险识别，查看逐测点判定、生效规范来源与待复核项。",
};

export default function WorkbenchPage() {
  return <WorkbenchClient />;
}
