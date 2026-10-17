import { useSyncExternalStore } from 'react';
import translations from './kk.json';

export type Locale='ru'|'kk';
let locale:Locale='ru';
try { locale=localStorage.getItem('posttech.locale')==='kk'?'kk':'ru'; } catch { /* private mode */ }
if (typeof document !== 'undefined') document.documentElement.lang=locale;
const listeners=new Set<()=>void>();
const dictionary:Record<string,string>=translations;
const templates=Object.entries(dictionary).filter(([key])=>/\{\d+\}/.test(key)).map(([key,value])=>({
 pattern:new RegExp('^'+key.split(/\{\d+\}/).map(part=>part.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('(.*?)')+'$'),value,
}));
export function getLocale(){return locale;}
export function setLocale(value:Locale){locale=value;try{localStorage.setItem('posttech.locale',value);}catch{}if(typeof document!=='undefined')document.documentElement.lang=value;listeners.forEach(fn=>fn());}
export function useLocale(){return useSyncExternalStore(fn=>{listeners.add(fn);return()=>{listeners.delete(fn);};},getLocale,()=> 'ru' as Locale);}
/** Exact UI catalogue matching. User-authored prose is never machine translated. */
export function t(value:string):string {
 if(locale==='ru')return value;
 const key=value.trim().replace(/\s+/g,' ');const translated=dictionary[key];
 if(translated)return value.replace(value.trim(),translated);
 for(const template of templates){const match=key.match(template.pattern);if(match)return value.replace(value.trim(),template.value.replace(/\{(\d+)\}/g,(_,i)=>match[Number(i)+1]));}
 return value;
}
export function tx<T>(value:T):T {return (typeof value==='string'?t(value):Array.isArray(value)?value.map(v=>typeof v==='string'?t(v):v):value) as T;}
export function LanguageSwitch(){const current=useLocale();return <select className="language-switch" aria-label="Language / Тіл" value={current} onChange={e=>setLocale(e.target.value as Locale)}><option value="ru">RU</option><option value="kk">KZ</option></select>;}

/** Embedded browsers may omit Kazakh ICU month names; never show M01/M10. */
export function localizedDate(date:Date, options:Intl.DateTimeFormatOptions={}):string {
 if(locale==='ru')return new Intl.DateTimeFormat('ru-RU',options).format(date);
 const months=['қаңтар','ақпан','наурыз','сәуір','мамыр','маусым','шілде','тамыз','қыркүйек','қазан','қараша','желтоқсан'];
 const parts=new Intl.DateTimeFormat('en-GB',{...options,...(options.month?{month:'numeric'}:{})}).formatToParts(date);
 const get=(type:string)=>parts.find(p=>p.type===type)?.value;
 const result=[];
 if(get('weekday'))result.push(({Monday:'дүйсенбі',Tuesday:'сейсенбі',Wednesday:'сәрсенбі',Thursday:'бейсенбі',Friday:'жұма',Saturday:'сенбі',Sunday:'жексенбі',Mon:'дс',Tue:'сс',Wed:'ср',Thu:'бс',Fri:'жм',Sat:'сб',Sun:'жс'} as Record<string,string>)[get('weekday')!]||get('weekday'));
 if(options.day&&get('day'))result.push(get('day'));
 if(options.month&&get('month'))result.push(['numeric','2-digit'].includes(options.month)?get('month'):months[Number(get('month'))-1]);
 if(options.year&&get('year'))result.push(get('year'));
 if(get('hour'))result.push([get('hour'),get('minute'),get('second')].filter(Boolean).join(':'));
 return result.join(' ');
}
