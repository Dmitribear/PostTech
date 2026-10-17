import { t, tx } from '../lib/i18n';
import { useEffect, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { usePortal } from '../context';
import { EmptyState, ErrorState, Icon, LoadingState, Modal, PageHeader } from '../components/ui';
import { errorMessage } from '../lib/api';
import { formatDate } from '../lib/format';
import type { EmployeeProfile } from '../lib/types';
import './workspace.css';

export interface Ticket { id:string; employee_id:string; question:string; context:string; status:'open'|'resolved'; answer:string|null; created_at:string; answered_at:string|null; }
interface Delegation { id:string; manager_id:string; deputy_id:string; starts_on:string; ends_on:string; reason:string; revoked_at:string|null; }
export function businessToday() { return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Almaty',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()); }

export function Escalation({question,context,onClose}:{question:string;context:string;onClose:()=>void}) {
  const {api,refresh}=usePortal();
  const [text,setText]=useState(question); const [details,setDetails]=useState(context.slice(0,6000));
  const [consent,setConsent]=useState(false); const [busy,setBusy]=useState(false); const [error,setError]=useState('');
  const [id]=useState(()=>crypto.randomUUID()); const [sent,setSent]=useState<Ticket|null>(null);
  async function submit(e:FormEvent) {e.preventDefault();if(busy)return;setBusy(true);setError('');try {
    setSent(await api.workspace<Ticket>('/tickets','POST',{id,question:text,context:details,consent}));refresh();
  } catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
  return <Modal title={sent?'Обращение отправлено':'Передать вопрос в HR'} onClose={()=>{if(!busy)onClose();}}>
    {tx(sent?<div className="ws-stack"><p>{t("HR получит только текст, который вы подтвердили. Ответ появится здесь и в уведомлениях.")}</p><Link className="btn btn-primary" to={`/support?ticket=${sent.id}`}>{t("Открыть обращение")}</Link></div>:<form className="ws-stack" onSubmit={submit}>
      <label className="field">{t("Ваш вопрос")}<textarea className="input" value={text} onChange={e=>setText(e.target.value)} required minLength={3} maxLength={2000} rows={3} disabled={busy}/></label>
      <label className="field">{t("Контекст для HR")}<textarea className="input" value={details} onChange={e=>setDetails(e.target.value)} maxLength={6000} rows={5} disabled={busy}/></label>
      <p className="muted">{t("Проверьте текст перед отправкой. Вся переписка не передаётся.")}</p>
      <label className="ws-check"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} disabled={busy}/>{t("Разрешаю передать этот вопрос и контекст сотрудникам HR")}</label>
      {tx(Boolean(error)&&<ErrorState error={error}/>)}<button className="btn btn-primary" disabled={!consent||busy||text.trim().length<3}>{tx(busy?'Отправляем…':'Отправить в HR')}</button>
    </form>)}
  </Modal>;
}

export default function Support() {
 const {api,profile,refreshKey,refresh}=usePortal();const [params,setParams]=useSearchParams();
 const [rows,setRows]=useState<Ticket[]>([]);const [selected,setSelected]=useState<Ticket|null>(null);
 const [loading,setLoading]=useState(true);const [error,setError]=useState<unknown>(null);
 const [answer,setAnswer]=useState('');const [busy,setBusy]=useState(false);const [create,setCreate]=useState(false);
 const [people,setPeople]=useState<EmployeeProfile[]>([]);
 useEffect(()=>{if(profile.role!=='hr_admin')return;let active=true;api.getTeam().then(p=>{if(active)setPeople(p);}).catch(()=>{});return()=>{active=false;};},[api,profile.role]);
 const personName=(id:string)=>id===profile.id?profile.full_name:people.find(p=>p.id===id)?.full_name||id.slice(0,8);
 const [filter,setFilter]=useState('all'); const [offset,setOffset]=useState(0);const [search,setSearch]=useState('');const [hasNext,setHasNext]=useState(false);
 useEffect(()=>{let active=true;setLoading(true);setError(null);const query=new URLSearchParams({limit:'13',offset:String(offset),search:search.trim()});if(filter!=='all')query.set('status',filter);const timer=setTimeout(()=>{api.workspace<Ticket[]>(`/tickets?${query}`).then(r=>{if(active){setRows(r.slice(0,12));setHasNext(r.length>12);}}).catch(e=>{if(active)setError(e);}).finally(()=>{if(active)setLoading(false);});},250);return()=>{active=false;clearTimeout(timer);};},[api,refreshKey,offset,filter,search]);
 useEffect(()=>{const id=params.get('ticket');setSelected(null);setAnswer('');if(!id)return;let active=true;api.workspace<Ticket>(`/tickets/${encodeURIComponent(id)}`).then(r=>{if(active)setSelected(r);}).catch(e=>{if(active)setError(e);});return()=>{active=false;};},[api,params,refreshKey]);
 async function respond(e:FormEvent){e.preventDefault();if(!selected||busy)return;setBusy(true);setError(null);try{await api.workspace(`/tickets/${selected.id}/answer`,'POST',{answer});refresh();}catch(e){setError(e);}finally{setBusy(false);}}
 return <div className="support-page"><PageHeader title={t("Обращения в HR")} actions={<button className="btn btn-primary" type="button" onClick={()=>setCreate(true)}><Icon name="message" size={17}/>{t("Задать вопрос")}</button>}/>
 <div className="support-tabs">{tx([['all','Все'],['open','Ожидают ответа'],['resolved','С ответом']].map(([v,l])=><button key={v} className="support-tab" aria-pressed={filter===v} onClick={()=>{setFilter(v);setOffset(0);}}>{tx(l)}</button>))}</div>
 <label className="field">{t("Поиск обращения")}<input className="input" type="search" maxLength={120} value={search} onChange={e=>{setSearch(e.target.value);setOffset(0);}} placeholder={t("Текст вопроса")}/></label>
 {tx(Boolean(error)&&<ErrorState error={error} retry={()=>{setError(null);refresh();}}/>)}
 {loading?<LoadingState/>:rows.length?<div className="ws-stack">{rows.map(r=><button key={r.id} className="card ws-row ws-ticket" onClick={()=>setParams({ticket:r.id})}><div><strong>{r.question}</strong><small>{personName(r.employee_id)} · {tx(formatDate(r.created_at))} · {tx(r.id.slice(0,8))}</small></div><span className={`badge badge-${r.status==='open'?'pending':'completed'}`}>{tx(r.status==='open'?'Ожидает ответа':'HR ответил')}</span></button>)}</div>:<EmptyState title={t(search||filter!=='all'?"Обращения не найдены":"Обращений пока нет")} description={t(search||filter!=='all'?"Измените поиск или статус.":"Здесь сохраняются ваши вопросы и ответы HR.")}/>}
 {(offset>0||hasNext)&&<nav className="list-pager" aria-label={t("Страницы списка")}><button className="btn btn-secondary" disabled={loading||offset===0} onClick={()=>setOffset(Math.max(0,offset-12))}>{t("Назад")}</button><span aria-live="polite">{t("Страница")} {offset/12+1}</span><button className="btn btn-secondary" disabled={loading||!hasNext} onClick={()=>setOffset(offset+12)}>{t("Далее")}</button></nav>}
 {selected&&<Modal title={t("Обращение в HR")} onClose={()=>{if(!busy)setParams({});}}><div className="ws-stack"><small>{personName(selected.employee_id)} · {tx(formatDate(selected.created_at))} · {tx(selected.id.slice(0,8))}</small><h3 className="ws-document">{selected.question}</h3>{selected.context&&<details className="ws-context"><summary>{t("Контекст обращения")}</summary><div className="ws-document">{selected.context}</div></details>}{selected.answer?<div className="ws-answer"><strong>{t("Ответ HR · ")}{tx(formatDate(selected.answered_at))}</strong><p className="ws-document">{selected.answer}</p></div>:profile.role==='hr_admin'&&selected.employee_id!==profile.id?<form className="ws-stack" onSubmit={respond}><label className="field">{t("Ответ сотруднику")}<textarea className="input" required minLength={3} maxLength={6000} rows={5} value={answer} onChange={e=>setAnswer(e.target.value)} disabled={busy}/></label><p className="muted">{t("Ответ сохранится в истории. Сотрудник получит уведомление.")}</p><button className="btn btn-primary" disabled={busy||answer.trim().length<3}>{tx(busy?'Отправляем…':'Ответить и закрыть')}</button></form>:<p>{t("Ожидаем ответа HR")}</p>}{tx(Boolean(error)&&<ErrorState error={error}/>)}</div></Modal>}
 {tx(create&&<Escalation question="" context="" onClose={()=>setCreate(false)}/>)}
 </div>;
}

export function Delegations() {
 const {api,profile,refreshKey,refresh}=usePortal();const [rows,setRows]=useState<Delegation[]>([]);const [people,setPeople]=useState<EmployeeProfile[]>([]);
 const [error,setError]=useState<unknown>(null);const [loading,setLoading]=useState(true);const [open,setOpen]=useState(false);const [busy,setBusy]=useState(false);
 const [manager,setManager]=useState('');const [deputy,setDeputy]=useState('');const [start,setStart]=useState(businessToday);const [end,setEnd]=useState(businessToday);const [reason,setReason]=useState('');const [key,setKey]=useState(()=>crypto.randomUUID());
 const [revoke,setRevoke]=useState<string|null>(null);
 useEffect(()=>{let active=true;setLoading(true);Promise.all([api.workspace<Delegation[]>('/delegations'),api.getTeam()]).then(([r,p])=>{if(active){setRows(r);setPeople(p);}}).catch(e=>{if(active)setError(e);}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[api,refreshKey]);
 if(profile.role!=='hr_admin')return <EmptyState title={t("Раздел доступен HR")}/>;
 const managers=people.filter(p=>p.role==='manager'||p.role==='director');
 const name=(id:string)=>[...people,profile].find(p=>p.id===id)?.full_name||id.slice(0,8);
 async function save(e:FormEvent){e.preventDefault();if(busy)return;setBusy(true);setError(null);try{await api.workspace('/delegations','POST',{id:key,manager_id:manager,deputy_id:deputy,starts_on:start,ends_on:end,reason});setOpen(false);setKey(crypto.randomUUID());refresh();}catch(e){setError(e);}finally{setBusy(false);}}
 async function cancel(){if(!revoke||busy)return;setBusy(true);try{await api.workspace(`/delegations/${revoke}`,'DELETE');setRevoke(null);refresh();}catch(e){setError(e);}finally{setBusy(false);}}
 return <div className="support-page"><PageHeader title={t("Замещение")} description={t("Временное право согласовывать заявки")} actions={<button className="btn btn-primary" onClick={()=>{setError(null);setOpen(true);}}>{t("Назначить заместителя")}</button>}/>
 {tx(Boolean(error)&&<ErrorState error={error} retry={refresh}/>)}{loading?<LoadingState/>:!rows.length?<EmptyState title={t("Замещения не назначены")}/>:<div className="ws-stack">{rows.map(d=><article className="card ws-row" key={d.id}><div><strong>{tx(name(d.manager_id))} → {tx(name(d.deputy_id))}</strong><small>{tx(formatDate(d.starts_on))} — {tx(formatDate(d.ends_on))} · {tx(d.revoked_at?'Отозвано':d.ends_on<businessToday()?'Истекло':d.starts_on>businessToday()?'Запланировано':'Действует')}</small>{d.reason&&<p>{d.reason}</p>}</div>{tx(!d.revoked_at&&d.ends_on>=businessToday()&&<button className="btn btn-secondary" onClick={()=>setRevoke(d.id)}>{t("Отозвать")}</button>)}</article>)}</div>}
 {open&&<Modal title={t("Назначить заместителя")} onClose={()=>{if(!busy)setOpen(false);}}><form className="ws-stack" onSubmit={save}>
 <label className="field">{t("Кого замещаем")}<select aria-label={t("Кого замещаем")} className="input" required value={manager} onChange={e=>{setManager(e.target.value);if(e.target.value===deputy)setDeputy('');}} disabled={busy}><option value="">{t("Выберите руководителя")}</option>{managers.map(p=><option key={p.id} value={p.id}>{p.full_name} · {p.employee_code}</option>)}</select></label>
 <label className="field">{t("Заместитель")}<select aria-label={t("Заместитель")} className="input" required value={deputy} onChange={e=>setDeputy(e.target.value)} disabled={busy}><option value="">{t("Выберите заместителя")}</option>{managers.filter(p=>p.id!==manager).map(p=><option key={p.id} value={p.id}>{p.full_name} · {p.employee_code}</option>)}</select></label>
 <div className="ws-columns"><label className="field">{t("С")}<input type="date" className="input" min={businessToday()} required value={start} onChange={e=>{setStart(e.target.value);if(end<e.target.value)setEnd(e.target.value);}} disabled={busy}/></label><label className="field">{t("По включительно")}<input type="date" className="input" min={start} required value={end} onChange={e=>setEnd(e.target.value)} disabled={busy}/></label></div>
 <label className="field">{t("Причина")}<textarea className="input" value={reason} onChange={e=>setReason(e.target.value)} maxLength={1000} disabled={busy}/></label><p className="muted">{t("Замещение доступно руководителям и директорам на первом этапе. Окончательное решение остаётся за HR. Свои заявки заместитель не согласует. Основной руководитель сохраняет доступ.")}</p>
 {tx(Boolean(error)&&<ErrorState error={error}/>)}<button className="btn btn-primary" disabled={busy}>{t("Назначить")}</button></form></Modal>}
 {tx(revoke&&<Modal title={t("Отозвать замещение?")} onClose={()=>{if(!busy)setRevoke(null);}}><p>{t("Новые решения заместителя станут недоступны. Принятые решения сохранятся.")}</p>{tx(Boolean(error)&&<ErrorState error={error}/>)}<button className="btn btn-primary" disabled={busy} onClick={cancel}>{t("Подтвердить отзыв")}</button></Modal>)}
 </div>;
}
