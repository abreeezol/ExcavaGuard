import{readFileSync,writeFileSync,mkdirSync}from'node:fs';
import{createHash}from'node:crypto';
import{resolve}from'node:path';
import{callSkillScript}from'@/server/skills/python-bridge';
const base='engineering-adapters/tunnel-monitoring';const manifest=JSON.parse(readFileSync(base+'/knowledge-manifest.json','utf8'));const hash=data=>createHash('sha256').update(data).digest('hex');
if(hash(readFileSync(base+'/knowledge/knowledge.sqlite3'))!==manifest.index_sha256)throw new Error('INDEX_HASH_MISMATCH');
const sources=JSON.parse(readFileSync('tools/knowledge/tunnel-sources.json','utf8'));const results=[];
for(const s of manifest.sources){
 if(hash(readFileSync(resolve('..',sources.source_directory,s.relative_path)))!==s.source_sha256)throw new Error('SOURCE_HASH_MISMATCH '+s.code);
 // Audit-only raw retrieval: inactive/unknown sources are not supplied to report generation.
 const result=await callSkillScript('adapter-knowledge','query.py',{adapter_id:'tunnel-monitoring',enforce_scope:false,query:{query:'监测 测量 隧道 施工 质量 安全 工程',filters:{standard_versions:[s.code],effective_status:s.effective_status},top_k:2}},{adapterId:'tunnel-monitoring'});
 const hits=result.result;if(!Array.isArray(hits)||!hits.length)throw new Error('SOURCE_NOT_RETRIEVABLE '+s.code);
 results.push({standard_name:s.name,standard_version:s.code,effective_status:s.effective_status,page_count:s.page_count,record_count:s.record_count,source_hash_valid:true,sample_locations:hits.map(h=>h.metadata.clause),report_use:s.effective_status==='active'?'candidate_subject_to_project_scope':'blocked_pending_review_or_historical_only'});
 console.log(JSON.stringify(results.at(-1)));
}
const out='var/rag/tunnel-monitoring-verification.json';mkdirSync('var/rag',{recursive:true});writeFileSync(out,JSON.stringify({source_count:results.length,index_sha256:manifest.index_sha256,results,notice:'逐本候选召回验证，不是条文全覆盖率或工程师专业验收。'},null,2)+'\n');console.log('ALL_SOURCES_VERIFIED',results.length,out);
