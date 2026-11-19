import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

export function checkTunnelIndex(root = process.cwd()) {
  const adapter = JSON.parse(readFileSync(resolve(root, 'engineering-adapters/tunnel-monitoring/manifest.json'), 'utf8'));
  const manifest = JSON.parse(readFileSync(resolve(root, adapter.knowledge_manifest), 'utf8'));
  const path = resolve(root, adapter.retrieval.local_index);
  let bytes;
  try { bytes = readFileSync(path); }
  catch { throw new Error('TUNNEL_INDEX_MISSING: restore the versioned tunnel knowledge index with git checkout, then run npm run tunnel:check.'); }
  if (!bytes.subarray(0, 16).equals(Buffer.from('SQLite format 3\0'))) throw new Error('TUNNEL_INDEX_INVALID');
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  if (sha256 !== manifest.index_sha256) throw new Error('TUNNEL_INDEX_HASH_MISMATCH');
  return { passed: true, source_count: manifest.source_count, record_count: manifest.record_count, sha256 };
}
console.info(JSON.stringify(checkTunnelIndex(process.argv[2])));
