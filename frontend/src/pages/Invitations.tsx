import { t, tx } from '../lib/i18n';
import { useEffect, useState, type FormEvent } from 'react';
import { usePortal } from '../context';
import { ListPager, useListPage } from '../components/ListPager';
import { Icon, Modal } from '../components/ui';
import { errorMessage, LiveApi } from '../lib/api';
import { formatDate, roleLabels } from '../lib/format';
import type { AppRole, EmployeeProfile, InvitationInput, InvitationRecord, IssuedInvitation } from '../lib/types';
import './invitations.css';

export default function Invitations({ employees, onClose }: { employees: EmployeeProfile[]; onClose: () => void }) {
  const { api, profile } = usePortal();
  const live = api instanceof LiveApi ? api : null;
  const [view, setView] = useState<'create' | 'list'>('create');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<IssuedInvitation | null>(null);
  const [rows, setRows] = useState<InvitationRecord[]>([]);
  const [search, setSearch] = useState('');
  const filtered = rows.filter(row => `${row.email} ${row.department}`.toLocaleLowerCase().includes(search.toLocaleLowerCase().trim()));
  const paging = useListPage(filtered, search, 10);
  const [copied, setCopied] = useState(false);
  const [listVersion, setListVersion] = useState(0);
  const [input, setInput] = useState<InvitationInput>({ email: '', employee_code: '', company: profile.company, job_title: '', department: profile.department, hired_at: new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Qyzylorda' }).format(new Date()), manager_id: null, role: 'worker', vacation_days_remaining: 0, expires_in_hours: 72 });
  const update = <K extends keyof InvitationInput>(key: K, value: InvitationInput[K]) => setInput(previous => ({ ...previous, [key]: value }));
  useEffect(() => {
    if (view !== 'list' || !live) return;
    let active = true; setBusy(true); setError('');
    live.getInvitations().then(data => { if (active) setRows(data); }).catch(err => { if (active) setError(errorMessage(err)); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [view, live, listVersion]);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy) return;
    setBusy(true); setError('');
    try {
      const value = live ? await live.issueInvitation({ ...input, email: input.email.trim(), employee_code: input.employee_code.trim() }) : { id: 'demo', invitation_code: 'JP-DEMO-2026', email: input.email, role: input.role, department: input.department, expires_at: new Date(Date.now() + input.expires_in_hours * 3600000).toISOString() };
      setResult(value); setCopied(false);
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  }
  async function revoke(id: string) {
    if (!live || busy) return; setBusy(true); setError('');
    try { await live.revokeInvitation(id); setListVersion(value => value + 1); }
    catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  }
  async function copyCode() {
    if (!result) return;
    try { await navigator.clipboard.writeText(result.invitation_code); setCopied(true); }
    catch { setError('Не удалось скопировать автоматически. Выделите код и скопируйте его вручную.'); }
  }
  return <Modal title={result ? 'Приглашение готово' : 'Приглашения'} wide onClose={() => { if (!busy) onClose(); }}>
    {tx(!live && <div className="invite-note"><Icon name="info" size={18} /><span>{t("Демоверсия: приглашение не создаёт рабочий аккаунт.")}</span></div>)}
    {result ? <div className="invite-result"><span className="invite-result-icon"><Icon name="mail" size={30} /></span><h3>{result.email}</h3><p>{tx(roleLabels[result.role])} · {tx(result.department)}</p><label className="field"><span className="field-label">{t("Код приглашения")}</span><input className="input invite-code" readOnly value={result.invitation_code} onFocus={event => event.target.select()} /></label><button className="btn btn-primary" onClick={copyCode}>{tx(copied ? 'Код скопирован' : 'Скопировать код')}<Icon name={copied ? 'check' : 'clipboard'} size={17} /></button><div className="invite-note"><Icon name="info" size={18} /><span>{t("Передайте код сотруднику в личном сообщении. Он действует до ")}{tx(formatDate(result.expires_at))}{t(". После закрытия код не показывается повторно.")}</span></div><p className="muted">{t("На странице входа нужно выбрать «Активировать приглашение».")}</p><button className="btn btn-secondary" onClick={() => { setResult(null); setView('list'); }}>{t("К списку приглашений")}</button></div> : <>
      <div className="support-tabs"><button className="support-tab" disabled={busy} aria-pressed={view === 'create'} onClick={() => { setView('create'); setError(''); }}>{t("Новое")}</button><button className="support-tab" disabled={busy} aria-pressed={view === 'list'} onClick={() => { setView('list'); setError(''); }}>{t("Выданные")}</button></div>
      {view === 'create' ? <form className="invite-form" onSubmit={submit}><p className="muted">{t("Укажите рабочие данные. Сотрудник сам задаст пароль и подтвердит почту.")}</p><div className="invite-fields">
        <label className="field"><span className="field-label">{t("Рабочая почта")}</span><input className="input" type="email" required maxLength={320} autoComplete="off" value={input.email} onChange={e => update('email', e.target.value)} /></label>
        <label className="field"><span className="field-label">{t("Табельный номер")}</span><input className="input" required maxLength={80} value={input.employee_code} onChange={e => update('employee_code', e.target.value)} /></label>
        <label className="field"><span className="field-label">{t("Должность")}</span><input className="input" required maxLength={160} value={input.job_title} onChange={e => update('job_title', e.target.value)} /></label>
        <label className="field"><span className="field-label">{t("Подразделение")}</span><input className="input" required maxLength={160} value={input.department} onChange={e => update('department', e.target.value)} /></label>
        <label className="field"><span className="field-label">{t("Роль")}</span><select className="input" value={input.role} onChange={e => update('role', e.target.value as AppRole)}>{tx((['worker', 'manager', 'director', 'hr_admin'] as AppRole[]).map(role => <option key={role} value={role}>{tx(roleLabels[role])}</option>))}</select></label>
        <label className="field"><span className="field-label">{t("Руководитель")}</span><select className="input" value={input.manager_id || ''} onChange={e => update('manager_id', e.target.value || null)}><option value="">{t("Согласование через HR")}</option>{employees.filter(item => item.role !== 'worker').map(item => <option key={item.id} value={item.id}>{item.full_name} · {item.employee_code}</option>)}</select></label>
        <label className="field"><span className="field-label">{t("Компания")}</span><input className="input" required maxLength={120} value={input.company} onChange={e => update('company', e.target.value)} /></label>
        <label className="field"><span className="field-label">{t("Дата приёма")}</span><input className="input" type="date" required value={input.hired_at} onChange={e => update('hired_at', e.target.value)} /></label>
        <label className="field"><span className="field-label">{t("Остаток отпуска, дней")}</span><input className="input" type="number" min={0} max={9999.9} step={0.1} required value={input.vacation_days_remaining} onChange={e => update('vacation_days_remaining', Number(e.target.value))} /></label>
        <label className="field"><span className="field-label">{t("Срок действия")}</span><select className="input" value={input.expires_in_hours} onChange={e => update('expires_in_hours', Number(e.target.value))}><option value={24}>{t("1 день")}</option><option value={72}>{t("3 дня")}</option><option value={168}>{t("7 дней")}</option></select></label>
      </div>{tx(input.role === 'hr_admin' && <div className="invite-note"><Icon name="shield" size={18} /><span>{t("HR-администратор получает доступ к сотрудникам, согласованию, приглашениям и обучению.")}</span></div>)}<div className="ws-form-actions"><button className="btn btn-primary" disabled={busy}>{tx(busy ? 'Создаём…' : 'Создать приглашение')}<Icon name="plus" size={16} /></button></div></form> : <><div className="list-anchor" ref={paging.anchor}><label className="field">{t("Поиск приглашения")}<input className="input" type="search" value={search} onChange={e=>setSearch(e.target.value)} placeholder={t("Почта или подразделение")}/></label></div><div className="invite-list">{tx(busy && <p role="status">{t("Загружаем…")}</p>)}{tx(!busy && !filtered.length && <p className="muted">{t(search?"Приглашения не найдены":"Выданных приглашений пока нет.")}</p>)}{paging.items.map(row => { const state = row.consumed_at ? 'Активировано' : row.revoked_at ? 'Отозвано' : new Date(row.expires_at).getTime() <= Date.now() ? 'Истекло' : 'Ожидает активации'; return <article key={row.id}><div><strong>{row.email}</strong><small>{tx(roleLabels[row.role])} · {tx(row.department)}</small><small>{tx(state)}{t(" · до ")}{tx(formatDate(row.expires_at))}</small></div>{tx(state === 'Ожидает активации' && <button className="btn btn-ghost" disabled={busy} onClick={() => revoke(row.id)}>{t("Отозвать")}</button>)}</article>; })}</div><ListPager {...paging}/></>}
    </>}
    {tx(error && <div className="inline-error" role="alert">{tx(error)}{tx(view === 'list' && <button className="text-link" onClick={() => setListVersion(value => value + 1)}>{t("Повторить")}</button>)}</div>)}
  </Modal>;
}
