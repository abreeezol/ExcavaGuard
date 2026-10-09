import { z } from "zod";

const nonEmptyText = z.string().trim().min(1);
const labelText = nonEmptyText.max(500);

export const standardEvidenceFiltersSchema = z.strictObject({
  standard_versions: z.array(labelText).min(1).max(20).optional(),
  monitoring_item: labelText.optional(),
  excavation_safety_level: labelText.optional(),
  region: labelText.optional(),
  effective_status: z.enum(["active", "inactive", "unknown"]).default("active"),
});

export const standardEvidenceQuerySchema = z.strictObject({
  query: nonEmptyText.max(1_000),
  filters: standardEvidenceFiltersSchema.default({ effective_status: "active" }),
  top_k: z.number().int().min(1).max(10).default(3),
});

export const standardEvidenceMetadataSchema = z.strictObject({
  standard_name: labelText,
  standard_version: labelText,
  clause: labelText,
  source_location: labelText,
  applicability: z.array(labelText).min(1).max(20),
  effective_status: z.enum(["active", "inactive", "unknown"]),
  monitoring_item: labelText.optional(),
  excavation_safety_level: labelText.optional(),
  region: labelText.optional(),
});

export const standardEvidenceCandidateSchema = z.strictObject({
  id: nonEmptyText.max(200),
  text: nonEmptyText.max(20_000),
  metadata: standardEvidenceMetadataSchema,
  score: z.float64(),
  matched_terms: z.array(labelText).max(50),
});

export const standardEvidenceSchema = standardEvidenceCandidateSchema.extend({
  provider: z.enum(["pinecone", "local"]),
});

export type StandardEvidenceQuery = z.input<typeof standardEvidenceQuerySchema>;
export type ParsedStandardEvidenceQuery = z.output<typeof standardEvidenceQuerySchema>;
export type StandardEvidenceCandidate = z.output<typeof standardEvidenceCandidateSchema>;
export type StandardEvidence = z.output<typeof standardEvidenceSchema>;
