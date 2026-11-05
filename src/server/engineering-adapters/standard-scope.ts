import 'server-only';
import {readFileSync} from 'node:fs';
import {z} from 'zod';
import {loadEngineeringAdapter,adapterAssetPath} from '@/server/engineering-adapters/registry';
const schema=z.object({axes:z.array(z.object({parameter:z.string(),catalog_key:z.string(),expansions:z.record(z.string(),z.array(z.string())).optional()})),case_method:z.object({parameter:z.string(),labels:z.record(z.string(),z.string())}).optional(),query_labels:z.record(z.string(),z.string()).default({})});
export function readStandardScope(adapterId:string){const {adapter}=loadEngineeringAdapter(adapterId);return adapter.standard_scope?schema.parse(JSON.parse(readFileSync(adapterAssetPath(adapter.standard_scope),'utf8'))):null;}
export function checkStandardScope(adapterId:string,conditions:Record<string,string[]>,parameters:Record<string,unknown>,provided?:ReturnType<typeof readStandardScope>){
 const policy=provided===undefined?readStandardScope(adapterId):provided;if(!policy)return {applicable:true,scope_reason:''};
 for(const axis of policy.axes){const value=parameters[axis.parameter];if(typeof value!=='string'||!value)throw new Error('ENGINEERING_SCOPE_REQUIRED：请先确认工程分类与工法。');const allowed=conditions[axis.catalog_key];const selected=axis.expansions?.[value]??[value];if(allowed?.length&&!allowed.some(v=>selected.includes(v)))return {applicable:false,scope_reason:`工程配置${axis.parameter}=${value}不属于本规范${axis.catalog_key}适用范围`};}
 return {applicable:true,scope_reason:'符合本工程分类范围；具体条文仍需核验适用条件'};
}
export function scopeQueryConditions(adapterId:string,parameters:Record<string,unknown>){const scope=readStandardScope(adapterId);return scope?scope.axes.map(a=>scope.query_labels[String(parameters[a.parameter])]??String(parameters[a.parameter]??'')).filter(Boolean):[];}
