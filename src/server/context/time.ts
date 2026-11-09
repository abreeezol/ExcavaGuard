export function instant(value:string|undefined,offset='+08:00'):number|null {
 if(!value)return null;
 const normalized=value.trim().replace(' ','T');
 const full=/^\d{4}-\d{2}-\d{2}$/.test(normalized)?normalized+'T00:00:00':normalized;
 const time=Date.parse(/[zZ]$|[+-]\d\d:\d\d$/.test(full)?full:full+offset);
 return Number.isFinite(time)?time:null;
}
export function localDay(value:string|undefined,timeZone='Asia/Shanghai',offset='+08:00') {
 const time=instant(value,offset);if(time===null)return '';
 return new Intl.DateTimeFormat('en-CA',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(time));
}
export function intervalEnd(value:string|undefined,offset='+08:00'):number|null {
 const time=instant(value,offset);return time===null?null:time+(/^\d{4}-\d{2}-\d{2}$/.test(value??'')?86400000-1:0);
}
