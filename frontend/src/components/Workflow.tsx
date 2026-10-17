import { useEffect, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { usePortal } from '../context';
import { ErrorState, LoadingState, StatusBadge } from './ui';
import { formatDate } from '../lib/format';
import { t } from '../lib/i18n';
import type { HrRequest, WorkspaceSummary } from '../lib/types';
import '../pages/hr-workflows.css';

export type Fulfillment = { status: 'awaiting_hr'|'processing'|'completed'; document_reference?: string; note: string; completed_at?: string; can_send: boolean; deliveries: {destination:string;status:string;attempts:number}[]; events: {id:string;action:string;detail:string;created_at:string}[] };
const stages = {awaiting_hr:'Ожидает оформления HR',processing:'HR оформляет документ',completed:'Документ оформлен'};
const deliveryNames: Record<string,string> = {queued:'В очереди',sending:'Передаётся',retry:'Повторная отправка',delivered:'Принято системой',dead:'Нужна проверка HR',cancelled:'Оформлено вручную'};

export function RequestState({request}:{request:HrRequest}) {
  if(request.status!=='approved')return <StatusBadge status={request.status}/>;
  return <span className="hf-label">{t(request.fulfillment?.status==='completed'?'Оформлено':request.fulfillment?.status==='processing'?'Оформляет HR':request.fulfillment?'Ожидает HR':'Согласовано')}</span>;
}

export function RequestFulfillment({request}: {request: HrRequest}) {
  const {api,profile,refresh,notify} = usePortal();
  const [item,setItem] = useState<Fulfillment|null>(null), [error,setError] = useState<unknown>(null);
  const [retry,setRetry] = useState(0), [busy,setBusy] = useState(false), [reference,setReference] = useState(''), [note,setNote] = useState('');
  useEffect(()=>{if(api.mode==='demo')return; let active=true; setError(null); api.workspace<Fulfillment>(`/fulfillment/${request.id}`).then(v=>{if(!v?.status||!Array.isArray(v.deliveries)||!Array.isArray(v.events))throw Error('Этап оформления недоступен. Обновите страницу.');if(active)setItem(v);}).catch(e=>{if(active)setError(e);});return()=>{active=false;};},[api,request.id,retry]);
  if(api.mode==='demo')return null;
  const canAct=profile.role==='hr_admin'&&profile.id!==request.employee_id;
  const canComplete=!!item && (item.deliveries.every(d=>['delivered','cancelled'].includes(d.status)) || item.deliveries.every(d=>d.status==='queued'&&d.attempts===0));
  async function act(action:'start'|'complete') {if(busy)return;setBusy(true);setError(null);try {await api.workspace(`/fulfillment/${request.id}`,'POST',{action,reference,note});setRetry(v=>v+1);refresh();notify(action==='start'?'Передано на оформление':'Документ оформлен');}catch(e){setError(e);}finally{setBusy(false);}}
  return <section className="card hf-card" aria-label="Оформление заявки"><h2>{t(item?stages[item.status]:'Оформление HR')}</h2>
    {Boolean(error)&&<ErrorState error={error} retry={()=>setRetry(v=>v+1)}/>}
    {!item&&!error?<LoadingState/>:item&&<><ol className="hf-stages"><li className="done">{t('Согласовано')}</li><li className={item.status!=='awaiting_hr'?'done':''}>{t('Оформление HR')}</li><li className={item.status==='completed'?'done':''}>{t('Документ готов')}</li></ol>
      {item.status==='completed'?<p><strong>{item.document_reference}</strong> · {formatDate(item.completed_at)}{item.note&&<span className="hf-note">{item.note}</span>}</p>:<p className="muted">{t('Решение принято. Следующий шаг — оформление документа специалистом HR.')}</p>}
      {item.deliveries.length>0&&<details><summary>{t('Передача в учётные системы')}</summary>{item.deliveries.map(d=><p key={d.destination}>{d.destination==='1c'?'1С':'Documentolog'}: {t(deliveryNames[d.status]||d.status)}</p>)}<p className="muted">{t('Приём события системой ещё не означает выпуск документа.')}</p>{canAct&&<Link to="/operations?tab=integrations" className="text-link">{t('Открыть очередь')}</Link>}</details>}
      {canAct&&item.status!=='completed'&&<div className="hf-stack">
        {item.status==='awaiting_hr'&&item.can_send&&<button className="btn btn-secondary" disabled={busy} onClick={()=>void act('start')}>{t('Передать в 1С и Documentolog')}</button>}
        {canComplete?<form className="hf-stack" onSubmit={(e:FormEvent)=>{e.preventDefault();void act('complete');}}><label className="field">{t('Номер оформленного документа')}<input className="input" required minLength={3} maxLength={200} value={reference} onChange={e=>setReference(e.target.value)} placeholder="Приказ № 123"/></label><details><summary>{t('Комментарий к документу')}</summary><textarea className="input" aria-label="Комментарий к документу" maxLength={2000} value={note} onChange={e=>setNote(e.target.value)}/></details><button className="btn btn-primary" disabled={busy||reference.trim().length<3}>{t(busy?'Сохраняем…':'Подтвердить оформление')}</button></form>:<p role="status">{t('Сначала завершите передачу в очередь интеграций. Затем укажите номер документа.')}</p>}
      </div>}
      {profile.role==='hr_admin'&&profile.id===request.employee_id&&item.status!=='completed'&&<p className="muted">{t('Вашу заявку оформит другой сотрудник HR.')}</p>}
      {item.events.length>0&&<details><summary>{t('История оформления')}</summary><ul>{item.events.map(e=><li key={e.id}>{formatDate(e.created_at)} · {t(e.action==='start'?'HR начал оформление':e.action==='complete'?'Документ оформлен':'Передано в HR')}{e.detail&&` · ${e.detail}`}</li>)}</ul></details>}
    </>}
  </section>;
}

export type MyTrack = {id:string; completed_at:string|null; learning_tracks:{title:string}; steps:{position:number;course_id:string;days_to_complete:number;courses:{title:string};assignment:{status:string;progress_percent:number;due_on:string|null}|null}[]};
export function MyTracks({employeeId}: {employeeId?:string}) {
  const {api,refreshKey}=usePortal();const [rows,setRows]=useState<MyTrack[]>([]),[error,setError]=useState<unknown>(null),[retry,setRetry]=useState(0);
  useEffect(()=>{if(api.mode==='demo')return;let active=true;api.workspace<MyTrack[]>(`/my-tracks${employeeId?'?employee_id='+employeeId:''}`).then(v=>{if(active){setRows(v);setError(null);}}).catch(e=>{if(active)setError(e);});return()=>{active=false;};},[api,employeeId,refreshKey,retry]);
  if(api.mode==='demo')return null;
  return <div className="hf-stack">{Boolean(error)&&<ErrorState error={error} retry={()=>setRetry(v=>v+1)}/>} {rows.map(row=>{const done=row.steps.filter(s=>s.assignment?.status==='completed').length;const next=row.steps.find(s=>s.assignment?.status!=='completed');return <section className="card hf-card" key={row.id}><div className="hf-row"><h2>{row.learning_tracks.title}</h2><span>{done} / {row.steps.length}</span></div>{next?<p>{t('Следующий шаг')}: <strong>{next.courses.title}</strong>{next.assignment?.due_on&&` · ${t('до')} ${formatDate(next.assignment.due_on)}`}</p>:<p>{t('План адаптации завершён')}</p>}{next?.assignment&&!employeeId&&<Link className="btn btn-secondary" to={`/academy?course=${next.course_id}`}>{t('Продолжить адаптацию')}</Link>}<details><summary>{t('Все шаги')}</summary><ol className="hf-track-steps">{row.steps.map(s=><li key={s.position}><span>{s.courses.title}</span><small>{t(s.assignment?.status==='completed'?'Пройден':s===next?'Текущий шаг':'Далее по плану')} · {s.days_to_complete} {t('дн. после открытия')}</small></li>)}</ol></details></section>;})}</div>;
}

export function OperationalReport({report}:{report:WorkspaceSummary}) {
  const items=(rows:{label:string;href:string}[])=> <ul>{rows.map((item,index)=><li key={index}><Link to={item.href}>{item.label}</Link></li>)}</ul>;
  return <div className="hf-report"><small>{t('Данные на')} {formatDate(report.as_of,{hour:'2-digit',minute:'2-digit'})}</small>{report.sections.map(section=><section key={section.title}><Link to={section.href}><strong>{t(section.title)}</strong><b>{section.count}</b></Link>{section.items.length>0&&items(section.items.slice(0,2))}{section.items.length>2&&<details><summary>{t('Ещё')} {section.items.length-2}</summary>{items(section.items.slice(2))}{section.count>section.items.length&&<Link className="text-link" to={section.href}>{t('Показать все')}</Link>}</details>}</section>)}</div>;
}
