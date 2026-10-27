import type { StandardEvidence } from "@/contracts/standard-evidence";

export type StandardCoverage = {
  strategy: string;
  catalogue_count: number;
  queried_count: number;
  completed: boolean;
  candidate_count: number;
  retained_count: number;
  omitted_count: number;
  notice: string;
  standards: Array<{
    standard_name: string; standard_version: string; effective_status: string;
    status: "pending" | "matched" | "no_relevant_hit" | "skipped_status" | "unavailable";
    candidate_ids: string[]; retained_ids: string[]; reason: string;
  }>;
};

export function standardName(name: string): string {
  return name.replace(/[（(]标准网[^）)]*[）)]/g, "").trim();
}

export function standardCitation(metadata: Pick<StandardEvidence["metadata"], "standard_name" | "standard_version" | "clause">): string {
  return `《${standardName(metadata.standard_name)}》 ${metadata.standard_version} · ${metadata.clause}`;
}

export function evidenceReferences(ids: string[], evidence: StandardEvidence[]): string {
  return [...new Set(ids.map((id) => {
    const item = evidence.find((entry) => entry.id === id);
    return item ? standardCitation(item.metadata) : "规范来源待复核";
  }))].join("；");
}

export function evidenceSourceLocation(source: string): string {
  return source.replace(/#chunk=.*$/, "");
}
