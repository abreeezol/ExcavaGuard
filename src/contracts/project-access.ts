import { z } from "zod";

export const projectRoleSchema = z.enum(["admin", "reviewer", "engineer", "viewer"]);
export const accessUserSchema = z.strictObject({
  id: z.uuid(), username: z.string().regex(/^[a-z0-9_.-]{2,80}$/),
  name: z.string().trim().min(1).max(100),
  password_hash: z.string().regex(/^scrypt:[a-f0-9]{32}:[a-f0-9]{128}$/),
  disabled: z.boolean().default(false), is_admin: z.boolean().default(false),
});
export const accessDirectorySchema = z.strictObject({
  version: z.literal(1), session_secret: z.string().regex(/^[a-f0-9]{64}$/),
  users: z.array(accessUserSchema).max(1000),
  projects: z.array(z.strictObject({ id: z.uuid(), name: z.string().trim().min(1).max(100), active: z.boolean() })).max(1000),
  memberships: z.array(z.strictObject({ user_id: z.union([z.uuid(), z.literal("local-operator")]), project_id: z.uuid(), role: projectRoleSchema })).max(10000),
}).superRefine((value, ctx) => {
  const unique = (values: string[]) => new Set(values).size === values.length;
  if (!unique(value.users.map(u => u.id)) || !unique(value.users.map(u => u.username)) ||
      !unique(value.projects.map(p => p.id)) || !unique(value.memberships.map(m => `${m.user_id}:${m.project_id}`)) ||
      value.memberships.some(m => !value.projects.some(p => p.id === m.project_id) ||
        (m.user_id !== "local-operator" && !value.users.some(u => u.id === m.user_id)))) {
    ctx.addIssue({ code: "custom", message: "用户、项目或成员关系重复或引用无效。" });
  }
});
export type AccessDirectory = z.infer<typeof accessDirectorySchema>;
