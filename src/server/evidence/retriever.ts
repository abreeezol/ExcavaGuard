import "server-only";
import type {
  StandardEvidence,
  StandardEvidenceQuery,
} from "@/contracts/standard-evidence";

export type StandardEvidenceProvider = StandardEvidence["provider"];

export interface StandardEvidenceRetriever {
  readonly provider: StandardEvidenceProvider;
  search(query: StandardEvidenceQuery): Promise<StandardEvidence[]>;
}

export type QueryEmbedder = (query: string) => Promise<readonly number[]>;
