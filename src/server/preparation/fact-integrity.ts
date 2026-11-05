import 'server-only';
import { createHash } from 'node:crypto';
import { preparationSummarySchema } from '@/contracts/pre-agent-preparation';
import { AppError } from '@/server/api/errors';

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(
    Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, nested]) => [key, canonical(nested)]),
  );
  return value;
}
export const canonicalDigest = (value: unknown) => createHash('sha256').update(JSON.stringify(canonical(value))).digest('hex');

type Payload = { project?: Record<string, unknown> };
export function handoffDigest(payload: Payload): string {
  const metadata = payload.project?.pre_agent_preparation as Record<string, unknown>;
  return canonicalDigest({ ...payload, project: { ...payload.project, pre_agent_preparation: { ...metadata, fact_digest: null } } });
}

/** Compatibility for historical runs; new prepared payloads must retain their full seal. */
export function verifyPreparedFacts(payload: unknown): void {
  const p = payload as Payload | null;
  if (!p?.project?.pre_agent_preparation) return;
  const metadata = preparationSummarySchema.parse(p.project.pre_agent_preparation);
  if (handoffDigest(p) !== metadata.fact_digest) throw new AppError(409, 'ARTIFACT_CHANGED', '交接事实已变化，不能使用失配的计算结果生成报告。');
}

/** Auxiliary evidence is already part of prepared facts; a parallel argument cannot replace it. */
export function prepareAgentPayload(payload: unknown, supportingContext?: unknown): unknown {
  verifyPreparedFacts(payload);
  const p = payload as Payload | null;
  const embedded = p?.project?.supporting_context;
  if (supportingContext !== undefined && embedded !== undefined && canonicalDigest(embedded) !== canonicalDigest(supportingContext)) {
    throw new AppError(409, 'ARTIFACT_CHANGED', '辅助资料与冻结事实不一致，请重新计算，不能替换报告依据。');
  }
  if (supportingContext !== undefined && embedded === undefined && p?.project?.pre_agent_preparation) {
    throw new AppError(409, 'ARTIFACT_CHANGED', '冻结后不能追加辅助资料，请重新计算。');
  }
  const merged = supportingContext !== undefined && embedded === undefined
    ? { ...p, project: { ...p?.project, supporting_context: supportingContext } } : payload;
  return structuredClone(merged);
}

export function verifyEngineSnapshot(snapshot: { ref: { content_hash: string }; payload: unknown }): void {
  verifyPreparedFacts(snapshot.payload);
  if (canonicalDigest(snapshot.payload) !== snapshot.ref.content_hash) {
    throw new AppError(409, 'ARTIFACT_CHANGED', '运行事实与保存的指纹不一致，停止编报，请重新计算。');
  }
}
