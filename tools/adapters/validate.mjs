// Run with tools/test/node-typescript-loader.mjs; validates local assets only.
import { loadEngineeringAdapter, validateEngineeringAdapter } from '@/server/engineering-adapters/registry';
import { readStandardCatalog } from '@/server/evidence/standard-catalog';
import { readFileSync } from 'node:fs';
import { adapterAssetPath } from '@/server/engineering-adapters/registry';
const {adapter,snapshot}=loadEngineeringAdapter(process.argv[2] ?? 'foundation-pit');
validateEngineeringAdapter(adapter, process.cwd(), true);
const rules=JSON.parse(readFileSync(adapterAssetPath(adapter.assets.rules),'utf8'));
const standards=readStandardCatalog(adapter.id);
console.log(JSON.stringify({
  status:'assets_validated', adapter:snapshot,
  metric_count:Object.keys(rules.metrics).length,
  standard_count:standards.length,
  core_fields:adapter.core_fields,
  acceptance_suites:adapter.acceptance_suites,
  notice:'结构与资产检查成功，不代表外部RAG/模型服务已验收或专业判据已获工程确认。',
},null,2));
