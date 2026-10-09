import { z } from "zod";

// 仅定义接口入口，工程事实和完整运行状态需按各 Skill 契约继续细化。
export const createRunRequestSchema = z.strictObject({
  project_id: z.uuid(),
  monitoring_file_id: z.uuid(),
  report_date: z.iso.date(),
});

export type CreateRunRequest = z.infer<typeof createRunRequestSchema>;
