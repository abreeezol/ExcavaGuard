import { z } from "zod";

export const projectStandardMetadataSchema = z.strictObject({
  standard_name: z.string().trim().min(2).max(200),
  standard_version: z.string().trim().min(3).max(100)
    .transform(value => value.toUpperCase().replace(/\s+/g, "").replace(/[—－–]/g, "-")),
  region: z.string().trim().min(1).max(100),
  applicability: z.string().trim().min(2).max(400),
  confirmed: z.literal(true),
});
export const projectStandardDocumentSchema = projectStandardMetadataSchema.extend({
  original_name: z.string(), extension: z.enum([".pdf", ".txt", ".md"]),
  document_id: z.uuid(), project_id: z.uuid(), sha256: z.string().regex(/^[a-f0-9]{64}$/),
  active: z.boolean(), created_at: z.iso.datetime(), chunk_count: z.number().int().positive(),
  page_count: z.number().int().positive(), unindexed_pages: z.array(z.number().int().positive()),
});
export type ProjectStandardDocument = z.infer<typeof projectStandardDocumentSchema>;
