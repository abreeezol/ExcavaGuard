import { z } from "zod";
const DAY=86400000;
export function recommendReportWindows(dates:string[]) {
 const days=[...new Set(dates.filter(d=>z.iso.date().safeParse(d).success))].sort();
 if(!days.length)return [];
 const available=new Set(days);const first=days[0];const last=days.at(-1)!;
 const candidates:Array<{id:string;type:'daily'|'weekly'|'monthly'|'custom';start_date:string;end_date:string;label:string;observed_days:number;calendar_days:number;missing_days:string[]}> = [];
 function add(type:'daily'|'weekly'|'monthly'|'custom',start:string,end:string,label:string){
  const total=Math.round((Date.parse(end)-Date.parse(start))/DAY)+1;const missing:string[]=[];
  for(let t=Date.parse(start);t<=Date.parse(end);t+=DAY){const d=new Date(t).toISOString().slice(0,10);if(!available.has(d))missing.push(d);}
  candidates.push({id:`${type}:${start}:${end}`,type,start_date:start,end_date:end,label,observed_days:total-missing.length,calendar_days:total,missing_days:missing});
 }
 for(const day of days.slice(-31).reverse())add('daily',day,day,`日报 ${day}`);
 for(const end of days.slice(-4).reverse()){const start=new Date(Date.parse(end)-6*DAY).toISOString().slice(0,10);if(start>=first)add('weekly',start,end,`周报 ${start} 至 ${end}`);}
 for(const month of [...new Set(days.map(d=>d.slice(0,7)))].slice(-12).reverse()){
  const start=month+'-01';const end=new Date(Date.UTC(Number(month.slice(0,4)),Number(month.slice(5)),0)).toISOString().slice(0,10);
  if(start>=first&&end<=last)add('monthly',start,end,`自然月报 ${month}`);
  else add('custom',first>start?first:start,last<end?last:end,`阶段月报 ${month}（非完整自然月）`);
 }
 return candidates;
}
