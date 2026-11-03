import { z } from "zod";

export const actorSchema = z.strictObject({
  id: z.union([z.uuid(), z.literal("local-operator")]),
  name: z.string().trim().min(1).max(100),
});

export type Actor = z.infer<typeof actorSchema>;
