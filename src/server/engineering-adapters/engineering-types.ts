import 'server-only';
/** Public business types map to one runtime each; subtypes are parameters, never selectable runtimes. */
export const engineeringTypes=[{id:'foundation_pit',name:'基坑工程',runtime:'foundation-pit'},{id:'tunnel',name:'隧道工程',runtime:'tunnel-monitoring'}] as const;
export function canonicalProjectAdapterId(id='foundation-pit'){return id==='tunnel-shield'?'tunnel-monitoring':id;}
export function runtimeForEngineeringType(type:string){const entry=engineeringTypes.find(t=>t.id===type);if(!entry)throw new Error('ENGINEERING_TYPE_UNSUPPORTED');return entry.runtime;}
export function publicEngineeringType(runtime:string){const id=canonicalProjectAdapterId(runtime);const entry=engineeringTypes.find(t=>t.runtime===id);return entry?{id:entry.id,name:entry.name}:{id:'other',name:'工程'};}
/** Preserve proven old settings. Do not infer the missing tunnel system or geological conditions. */
export function projectBinding(binding?:{adapter_id:string;parameters?:Record<string,unknown>}){
 const id=canonicalProjectAdapterId(binding?.adapter_id);let parameters=binding?.parameters;
 if(binding?.adapter_id==='tunnel-shield'){
  const old=parameters??{};const controls=Object.fromEntries(['ground_settlement','building_settlement'].map(k=>[k,{source:old.control_source??'',confirmed:old.control_values_confirmed===true,...(old.cumulative_limit_mm!=null?{cumulative_limit_mm:old.cumulative_limit_mm}:{}),...(old.rate_limit_mm_per_day!=null?{rate_limit_mm_per_day:old.rate_limit_mm_per_day}:{}),...(old.value_semantics?{value_semantics:old.value_semantics}:{})}]));
  parameters={...old,construction_method:'shield',project_stage:'construction',metric_controls:controls};
 }
 return {id,parameters};
}
