import { loadEngineeringAdapter, adapterAssetPath } from '@/server/engineering-adapters/registry';
import { readFileSync,readdirSync,mkdirSync,copyFileSync,writeFileSync,renameSync,rmSync,existsSync } from 'node:fs';
import {resolve,relative,dirname} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
const hash=p=>createHash('sha256').update(readFileSync(p)).digest('hex');
if(process.argv[2]==='--verify'){
 const folder=resolve(process.argv[3]);const release=JSON.parse(readFileSync(resolve(folder,'release.json'),'utf8'));
 if(release.bundle_sha256&&createHash('sha256').update(JSON.stringify(Object.entries(release.files).sort())).digest('hex')!==release.bundle_sha256)throw new Error('RELEASE_MANIFEST_MISMATCH');
 for(const [path,digest]of Object.entries(release.files)){const target=resolve(folder,path);if(relative(folder,target).startsWith('..')||hash(target)!==digest)throw new Error('RELEASE_HASH_MISMATCH '+path);}
 console.log(JSON.stringify({verified:true,adapter_id:release.snapshot.id,files:Object.keys(release.files).length}));
}else{
 const id=process.argv[2]??'foundation-pit';const {adapter,snapshot}=loadEngineeringAdapter(id);let target;
 const temporary=resolve('var/adapter-releases','.tmp-'+randomUUID());mkdirSync(temporary,{recursive:true});const files={};
 function copy(path){const source=adapterAssetPath(path);const out=resolve(temporary,path);mkdirSync(dirname(out),{recursive:true});copyFileSync(source,out);files[path]=hash(source);}
 function walk(path){for(const e of readdirSync(resolve(path),{withFileTypes:true})){if(['__pycache__','_archive','examples','tests'].includes(e.name))continue;const p=path+'/'+e.name;if(e.isDirectory())walk(p);else if(/\.(py|ts|json|mjs|md)$/.test(e.name))copy(p);}}
 try{
  for(const p of new Set([...Object.values(adapter.assets),...Object.values(adapter.handlers),...(adapter.additional_assets??[]),adapter.policy,adapter.context_schema,`engineering-adapters/${id}/manifest.json`,`engineering-adapters/${id}/evaluation.json`,`engineering-adapters/${id}/evaluation-results.json`,...(adapter.knowledge_manifest?[adapter.knowledge_manifest]:[]),...(adapter.standard_scope?[adapter.standard_scope]:[])]))copy(p);
  for(const p of [`engineering-adapters/${id}/runtime`,'确定性计算层/pipeline','确定性计算层/contracts','skills','source/adapter_runtime','src/server','src/contracts'])walk(p);
  for(const p of ['package.json','package-lock.json','deploy/requirements.txt'])copy(p);
  if(adapter.retrieval.local_index)copy(adapter.retrieval.local_index);
  const bundleHash=createHash('sha256').update(JSON.stringify(Object.entries(files).sort())).digest('hex');
  target=resolve('var/adapter-releases',id,adapter.version+'-'+bundleHash);
  if(existsSync(resolve(target,'release.json'))){rmSync(temporary,{recursive:true,force:true});console.log(JSON.stringify({existing:true,path:target,bundle_sha256:bundleHash}));process.exit(0);}
  const version={bundle_sha256:bundleHash,snapshot,node_version:process.version,created_at:new Date().toISOString(),files,knowledge_status:adapter.knowledge_manifest?'local_manifest_archived':'external_full_content_not_pinned',notice:'不含密钥或用户资料；重放需安装锁定依赖。外部模型或远端全量知识库不随此包冻结。'};
  writeFileSync(resolve(temporary,'release.json'),JSON.stringify(version,null,2)+'\n',{mode:0o600});mkdirSync(dirname(target),{recursive:true});renameSync(temporary,target);console.log(JSON.stringify({released:true,path:target,files:Object.keys(files).length}));
 }catch(e){rmSync(temporary,{recursive:true,force:true});throw e;}
}
