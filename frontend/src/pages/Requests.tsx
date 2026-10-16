import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { usePortal } from '../context';
import { fetchAllRequests } from '../lib/api';
import { calendarDayLabel } from '../lib/format';
import { Avatar, EmptyState, ErrorState, Icon, LoadingState, PageHeader, StatusBadge } from '../components/ui';
import './requests.css';
import { LeaveCalendarDownload } from '../components/LeaveCalendarDownload';

type Api = ReturnType<typeof usePortal>['api'];
export type RequestRecord = Awaited<ReturnType<Api['getRequest']>>;
type RequestEvent = Awaited<ReturnType<Api['getRequestHistory']>>[number];
type CreatePayload = Parameters<Api['createRequest']>[0];
type Employee = ReturnType<typeof usePortal>['profile'];

export function dateKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function parseDay(value: string): Date {
  return new Date(`${value.slice(0, 10)}T12:00:00`);
}

export function dayCount(start: string, end: string): number {
  const from = Date.parse(`${start}T00:00:00Z`);
  const to = Date.parse(`${end}T00:00:00Z`);
  return Number.isNaN(from) || Number.isNaN(to) || to < from ? 0 : Math.round((to - from) / 86400000) + 1;
}

export function formatDay(value: string | null | undefined, full = false): string {
  if (!value) return '—';
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const date = dateOnly ? parseDay(value) : new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: full ? 'long' : 'short', year: 'numeric', ...(dateOnly ? {} : { timeZone: 'Asia/Qyzylorda' }) });
}

export function requestLabel(request: RequestRecord): string {
  return request.request_type === 'leave' ? 'Заявка на отпуск' : 'Заявка на аванс';
}

export function requestNumber(id: string): string {
  return `REQ-${id.slice(-8).toUpperCase()}`;
}

export function money(value: number): string {
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value)} ₸`;
}

export async function loadRequests(api: Api, filters: Parameters<Api['getRequests']>[0] = {}): Promise<RequestRecord[]> {
  return fetchAllRequests(api, filters);
}

function pendingRequestKeys(storageKey: string): Map<string, string> {
  try {
    const entries: unknown = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
    if (!Array.isArray(entries)) return new Map();
    return new Map(entries.filter((entry): entry is [string, string] => Array.isArray(entry) && entry.length === 2 && typeof entry[0] === 'string' && typeof entry[1] === 'string' && /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(entry[1])));
  } catch { return new Map(); }
}

function storePendingRequestKeys(storageKey: string, keys: Map<string, string>) {
  try {
    if (keys.size) sessionStorage.setItem(storageKey, JSON.stringify([...keys]));
    else sessionStorage.removeItem(storageKey);
  } catch { /* In-memory retry protection remains available when browser storage is disabled. */ }
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Qyzylorda' });
}

export default function Requests() {
  const location = useLocation();
  const tail = location.pathname.replace(/\/$/, '').split('/').pop();
  if (tail === 'new') return <RequestForm />;
  if (tail && tail !== 'requests') return <RequestDetails id={tail} key={tail} />;
  return <RequestList />;
}

function RequestList() {
  const { api, profile, refreshKey } = usePortal();
  const [params, setParams] = useSearchParams();
  const [records, setRecords] = useState<RequestRecord[]>([]);
  const [team, setTeam] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reload, setReload] = useState(0);
  const [search, setSearch] = useState(params.get('q') || '');
  const [kind, setKind] = useState('all');
  const [page, setPage] = useState(1);
  const isReviewer = profile.role === 'manager' || profile.role === 'hr_admin';
  const scope = params.get('scope') === 'team' && isReviewer ? 'team' : 'own';
  const statusParam = params.get('status') || 'all';
  const status = ['pending', 'approved', 'rejected', 'cancelled'].includes(statusParam) ? statusParam : 'all';

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    loadRequests(api, scope === 'own' ? { employee_id: profile.id } : {})
      .then(data => { if (active) setRecords(data); })
      .catch(reason => { if (active) setError(reason); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api, profile.id, scope, refreshKey, reload]);

  useEffect(() => {
    let active = true;
    if (isReviewer) api.getTeam().then(data => { if (active) setTeam(data); }).catch(() => { /* Employee identifiers remain available. */ });
    return () => { active = false; };
  }, [api, isReviewer]);

  useEffect(() => { setPage(1); }, [scope, status, kind, search]);
  useEffect(() => { setSearch(params.get('q') || ''); }, [params.get('q')]);
  const people = useMemo(() => new Map([profile, ...team].map(person => [person.id, person])), [profile, team]);
  const scoped = useMemo(() => scope === 'team' ? records.filter(request => request.employee_id !== profile.id) : records, [records, scope, profile.id]);
  const filtered = useMemo(() => scoped.filter(request => {
    const query = search.trim().toLocaleLowerCase('ru-RU');
    const matchesQuery = !query || `${requestNumber(request.id)} ${request.id} ${requestLabel(request)} ${request.comment} ${people.get(request.employee_id)?.full_name || ''}`.toLocaleLowerCase('ru-RU').includes(query);
    return matchesQuery && (status === 'all' || request.status === status) && (kind === 'all' || request.request_type === kind);
  }), [scoped, search, status, kind, people]);
  const pages = Math.max(1, Math.ceil(filtered.length / 10));
  const currentPage = Math.min(page, pages);
  const visible = filtered.slice((currentPage - 1) * 10, currentPage * 10);

  function changeFilter(key: string, value: string) {
    setParams(previous => {
      const next = new URLSearchParams(previous);
      if (value === 'all' || (key === 'scope' && value === 'own')) next.delete(key);
      else next.set(key, value);
      return next;
    });
  }

  function changeSearch(value: string) {
    setSearch(value);
    setParams(previous => {
      const next = new URLSearchParams(previous);
      if (value) next.set('q', value);
      else next.delete('q');
      return next;
    }, { replace: true });
  }

  return <div className="req-page">
    <PageHeader eyebrow="КАДРОВЫЙ СЕРВИС" title={scope === 'team' ? 'Заявки сотрудников' : 'Мои заявки'} description="Все обращения, решения и история согласования в одном месте." actions={<Link className="btn btn-primary" to="/requests/new"><Icon name="plus" size={18} /> Создать заявку</Link>} />
    {isReviewer && <div className="req-scope-switch" aria-label="Область заявок"><button className={scope === 'own' ? 'active' : ''} onClick={() => changeFilter('scope', 'own')}>Мои заявки</button><button className={scope === 'team' ? 'active' : ''} onClick={() => changeFilter('scope', 'team')}><Icon name="users" size={16} />{profile.role === 'manager' ? 'Моя команда' : 'Все сотрудники'}</button></div>}
    <div className="req-stat-grid">
      {[{ label: 'Всего заявок', value: 'all', icon: 'file' }, { label: 'На согласовании', value: 'pending', icon: 'clock' }, { label: 'Согласовано', value: 'approved', icon: 'check' }, { label: 'Отклонено', value: 'rejected', icon: 'x' }].map(item => <button key={item.value} className={`card req-stat req-stat-${item.value} ${status === item.value ? 'selected' : ''}`} onClick={() => changeFilter('status', item.value)} aria-pressed={status === item.value}><span className="req-stat-label">{item.label}<Icon name={item.icon} size={19} /></span><strong>{loading ? '—' : scoped.filter(request => item.value === 'all' || request.status === item.value).length}</strong><span>{item.value === 'pending' ? 'Ожидают решения' : item.value === 'approved' ? 'Положительное решение' : item.value === 'rejected' ? 'Требуют вашего внимания' : scope === 'team' ? 'Обращения сотрудников' : 'Ваши обращения'}</span></button>)}
    </div>
    <section className="card req-list-card">
      <div className="req-list-heading"><h2>История заявок</h2><span className="muted">{loading ? 'Загрузка…' : `${filtered.length} заявок`}</span></div>
      <div className="req-filters"><label className="req-search"><Icon name="search" size={18} /><input value={search} onChange={event => changeSearch(event.target.value)} placeholder="Поиск по номеру, типу или комментарию" aria-label="Поиск заявок" />{search && <button onClick={() => changeSearch('')} aria-label="Очистить поиск"><Icon name="x" size={15} /></button>}</label><select className="input req-filter-select" aria-label="Тип заявки" value={kind} onChange={event => setKind(event.target.value)}><option value="all">Все типы</option><option value="leave">Отпуск</option><option value="advance">Аванс</option></select><select className="input req-filter-select" aria-label="Статус заявки" value={status} onChange={event => changeFilter('status', event.target.value)}><option value="all">Все статусы</option><option value="pending">На согласовании</option><option value="approved">Согласовано</option><option value="rejected">Отклонено</option><option value="cancelled">Отменено</option></select></div>
      {loading ? <LoadingState /> : error ? <ErrorState error={error} retry={() => setReload(value => value + 1)} /> : visible.length === 0 ? <EmptyState title={scoped.length ? 'Заявки не найдены' : scope === 'team' ? 'Заявок сотрудников пока нет' : 'Здесь появятся ваши заявки'} description={scoped.length ? 'Попробуйте изменить фильтры или поисковый запрос.' : 'Оформите отпуск или запросите аванс — статус обращения можно отслеживать здесь.'} action={!scoped.length && scope === 'own' ? <Link className="btn btn-primary" to="/requests/new">Создать первую заявку <Icon name="arrow-right" size={16} /></Link> : undefined} /> : <>
        <div className="req-table-scroll"><table className="req-table"><thead><tr><th>Заявка</th>{scope === 'team' && <th>Сотрудник</th>}<th>Период / сумма</th><th>Дата создания</th><th>Статус</th><th><span className="req-sr-only">Открыть</span></th></tr></thead><tbody>{visible.map(request => <tr key={request.id}><td><Link to={`/requests/${request.id}`} className="req-table-title"><span className={`req-type-icon ${request.request_type === 'advance' ? 'req-type-money' : ''}`}><Icon name={request.request_type === 'leave' ? 'calendar' : 'wallet'} size={18} /></span><span><strong>{requestLabel(request)}</strong><small>{requestNumber(request.id)}</small></span></Link></td>{scope === 'team' && <td><div className="req-employee-small"><Avatar name={people.get(request.employee_id)?.full_name || '?'} size={28} /><span>{people.get(request.employee_id)?.full_name || `Сотрудник ${request.employee_id.slice(0, 8)}`}</span></div></td>}<td>{request.request_type === 'leave' ? <><span>{formatDay(request.start_date)} —</span><br /><span>{formatDay(request.end_date)}</span></> : <strong>{money(request.amount || 0)}</strong>}</td><td className="muted">{formatDay(request.created_at)}</td><td><StatusBadge status={request.status} /></td><td><Link className="req-open-link" to={`/requests/${request.id}`} aria-label={`Открыть ${requestNumber(request.id)}`}><Icon name="chevron-right" size={18} /></Link></td></tr>)}</tbody></table></div>
        <div className="req-list-footer"><span>Показано {(currentPage - 1) * 10 + 1}–{Math.min(currentPage * 10, filtered.length)} из {filtered.length}</span><div><button className="btn btn-secondary" disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)} aria-label="Предыдущая страница"><Icon name="chevron-left" size={16} /></button><span>{currentPage} / {pages}</span><button className="btn btn-secondary" disabled={currentPage >= pages} onClick={() => setPage(currentPage + 1)} aria-label="Следующая страница"><Icon name="chevron-right" size={16} /></button></div></div>
      </>}
    </section>
    <div className="req-info-strip"><Icon name="info" size={18} /><span>Статус обновится после решения руководителя или HR. История всех изменений доступна в карточке заявки.</span><Link to="/calendar">Открыть календарь <Icon name="arrow-right" size={15} /></Link></div>
  </div>;
}

function RequestForm() {
  const { api, profile, refresh, notify } = usePortal();
  const [params] = useSearchParams();
  const location = useLocation();
  const carriedDraft = location.state?.requestDraft;
  const navigate = useNavigate();
  const [type, setType] = useState<'leave' | 'advance'>(params.get('type') === 'advance' ? 'advance' : 'leave');
  const [start, setStart] = useState(validDateParam(params.get('start')) || validDateParam(carriedDraft?.start));
  const [end, setEnd] = useState(validDateParam(params.get('end')) || validDateParam(carriedDraft?.end));
  const [amount, setAmount] = useState(typeof carriedDraft?.amount === 'string' ? carriedDraft.amount : '');
  const [comment, setComment] = useState(typeof carriedDraft?.comment === 'string' ? carriedDraft.comment.slice(0, 2000) : '');
  const [step, setStep] = useState(1);
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [validation, setValidation] = useState('');
  const [created, setCreated] = useState<RequestRecord | null>(null);
  const [draftAvailable, setDraftAvailable] = useState(() => {
    try { return Boolean(sessionStorage.getItem(`posttech-request-draft:${api.mode}:${profile.id}`)); } catch { return false; }
  });
  const idempotencyKeys = useRef(new Map<string, string>());
  const inFlight = useRef(false);
  const days = start && end && end >= start ? dayCount(start, end) : 0;
  const payload: CreatePayload = type === 'leave' ? { request_type: 'leave', start_date: start, end_date: end, comment: comment.trim() } : { request_type: 'advance', amount: Number(amount.replace(',', '.')), comment: comment.trim() };

  function proceed(event: React.FormEvent) {
    event.preventDefault();
    setValidation('');
    if (type === 'leave' && (!start || !end || end < start)) { setValidation('Укажите период отпуска. Дата окончания должна быть не раньше даты начала.'); return; }
    const number = Number(amount.replace(',', '.'));
    if (type === 'advance' && (!Number.isFinite(number) || number <= 0 || number > 1000000 || Math.abs(number * 100 - Math.round(number * 100)) > 0.000001)) { setValidation('Укажите сумму от 0,01 до 1 000 000 ₸, не более двух знаков после запятой.'); return; }
    setError(null);
    setStep(2);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function saveDraft() {
    try {
      sessionStorage.setItem(`posttech-request-draft:${api.mode}:${profile.id}`, JSON.stringify({ type, start, end, amount, comment }));
      setDraftAvailable(false);
      notify('Черновик сохранён в текущей вкладке браузера');
    } catch { setValidation('Не удалось сохранить черновик в браузере. Вы можете продолжить оформление заявки.'); }
  }

  function restoreDraft() {
    try {
      const draft = JSON.parse(sessionStorage.getItem(`posttech-request-draft:${api.mode}:${profile.id}`) || '{}');
      setType(draft.type === 'advance' ? 'advance' : 'leave');
      setStart(validDateParam(draft.start));
      setEnd(validDateParam(draft.end));
      setAmount(typeof draft.amount === 'string' ? draft.amount : '');
      setComment(typeof draft.comment === 'string' ? draft.comment.slice(0, 2000) : '');
      setDraftAvailable(false);
      notify('Черновик восстановлен');
    } catch { setDraftAvailable(false); setValidation('Сохранённый черновик не удалось открыть. Заполните заявку заново.'); }
  }

  async function submit() {
    if (!confirmed || inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    setError(null);
    const fingerprint = JSON.stringify(payload);
    const pendingStorageKey = `posttech-request-pending:${api.mode}:${profile.id}`;
    const memoryKey = `${api.mode}:${profile.id}:${fingerprint}`;
    const persistedKeys = pendingRequestKeys(pendingStorageKey);
    let key = idempotencyKeys.current.get(memoryKey) || persistedKeys.get(fingerprint);
    if (!key) key = crypto.randomUUID();
    idempotencyKeys.current.set(memoryKey, key);
    persistedKeys.set(fingerprint, key);
    // Save before sending: an uncertain network result can be retried after a reload.
    storePendingRequestKeys(pendingStorageKey, persistedKeys);
    try {
      sessionStorage.setItem(`posttech-request-draft:${api.mode}:${profile.id}`, JSON.stringify({ type, start, end, amount, comment }));
    } catch { /* Submitting remains available when browser storage is disabled. */ }
    try {
      const request = await api.createRequest(payload, key);
      setCreated(request);
      idempotencyKeys.current.delete(memoryKey);
      persistedKeys.delete(fingerprint);
      storePendingRequestKeys(pendingStorageKey, persistedKeys);
      try { sessionStorage.removeItem(`posttech-request-draft:${api.mode}:${profile.id}`); } catch { /* Request is already saved on the server. */ }
      refresh();
      notify('Заявка отправлена на согласование');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (reason) { setError(reason); }
    finally { inFlight.current = false; setSubmitting(false); }
  }

  if (created) return <div className="req-success-wrap"><Link className="req-back" to="/requests"><Icon name="chevron-left" size={16} /> К моим заявкам</Link><section className="card req-success"><div className="req-success-icon"><Icon name="check" size={38} /></div><StatusBadge status={created.status} /><h1>Заявка {type === 'leave' ? 'на отпуск' : 'на аванс'} успешно отправлена!</h1><p className="muted">Номер заявки: <strong>{requestNumber(created.id)}</strong>.<br />Вы можете следить за решением в личном кабинете.</p><div className="req-success-summary"><span className="req-eyebrow">ПАРАМЕТРЫ ЗАЯВКИ</span><div className="req-summary-grid"><div><span>Тип обращения</span><strong>{type === 'leave' ? 'Отпуск' : 'Аванс'}</strong></div><div><span>{type === 'leave' ? 'Период отпуска' : 'Сумма аванса'}</span><strong>{type === 'leave' ? `${formatDay(created.start_date)} — ${formatDay(created.end_date)}` : money(created.amount || 0)}</strong></div><div><span>{type === 'leave' ? 'Продолжительность' : 'Дата создания'}</span><strong>{type === 'leave' ? `${days} календ. дн.` : formatDay(created.created_at)}</strong></div></div></div><div className="req-success-next"><Icon name="clock" size={22} /><div><strong>Что произойдёт дальше</strong><p>Руководитель или HR рассмотрит заявку. Решение и комментарий появятся в истории согласования, а уведомление — в разделе «Уведомления».</p></div></div><div className="req-success-actions"><Link className="btn btn-primary" to={`/requests/${created.id}`}>Открыть детали заявки <Icon name="arrow-right" size={17} /></Link><Link className="btn btn-secondary" to="/calendar"><Icon name="calendar" size={16} /> Перейти в календарь</Link><Link className="btn btn-ghost" to="/">На главную</Link></div></section></div>;

  return <div className="req-page"><Link className="req-back" to="/requests"><Icon name="chevron-left" size={16} /> Заявки <span>/</span> {step === 1 ? 'Новое обращение' : 'Проверка данных'}</Link><PageHeader eyebrow={step === 1 ? 'НОВАЯ ЗАЯВКА' : 'ГОТОВО К ОТПРАВКЕ'} title={step === 2 ? 'Проверьте данные перед отправкой' : type === 'leave' ? 'Оформление трудового отпуска' : 'Заявка на выплату аванса'} description={step === 1 ? 'Укажите параметры обращения. Перед отправкой вы сможете проверить данные.' : 'Шаг 2 из 2: заявка будет передана руководителю или HR на согласование.'} actions={<div className="req-steps"><span className={step === 1 ? 'active' : 'done'}><b>{step > 1 ? <Icon name="check" size={13} /> : 1}</b> Параметры</span><Icon name="arrow-right" size={16} /><span className={step === 2 ? 'active' : ''}><b>2</b> Подтверждение</span></div>} />
    <div className="req-form-layout"><div className="stack">
      <div className="req-person"><Avatar name={profile.full_name} size={44} /><div><strong>{profile.full_name}</strong><span>{profile.job_title} · Табельный номер: {profile.employee_code}</span></div><span className="req-department">{profile.department}</span></div>
      {step === 1 ? <form id="request-form" className="stack" onSubmit={proceed}>
        {draftAvailable && <div className="req-draft-note"><Icon name="file" size={18} /><span>У вас есть сохранённый черновик</span><button type="button" className="btn btn-secondary" onClick={restoreDraft}>Восстановить</button></div>}
        <section className="card req-form-card"><h2><Icon name="file" size={19} /> Тип обращения</h2><div className="req-kind-selector"><button type="button" className={type === 'leave' ? 'active' : ''} onClick={() => { setType('leave'); setValidation(''); }} aria-pressed={type === 'leave'}><Icon name="calendar" size={20} /><span><strong>Трудовой отпуск</strong><small>Запланируйте время для отдыха</small></span>{type === 'leave' && <Icon name="check" size={16} />}</button><button type="button" className={type === 'advance' ? 'active' : ''} onClick={() => { setType('advance'); setValidation(''); }} aria-pressed={type === 'advance'}><Icon name="wallet" size={20} /><span><strong>Выплата аванса</strong><small>Укажите необходимую сумму</small></span>{type === 'advance' && <Icon name="check" size={16} />}</button></div></section>
        <section className="card req-form-card"><div className="req-card-heading"><h2><Icon name={type === 'leave' ? 'calendar' : 'wallet'} size={19} />{type === 'leave' ? 'Период отпуска' : 'Сумма аванса'}</h2>{type === 'leave' && <Link className="btn btn-ghost req-small-btn" state={{ requestDraft: { type, start, end, amount, comment } }} to={`/calendar?select=1${start ? `&start=${start}` : ''}${end ? `&end=${end}` : ''}`}>Выбрать в календаре <Icon name="arrow-right" size={15} /></Link>}</div>{type === 'leave' ? <><div className="req-date-fields"><label className="field"><span className="field-label">Дата начала</span><input className="input" type="date" required value={start} onChange={event => { setStart(event.target.value); if (end && event.target.value > end) setEnd(''); }} /></label><span className="req-date-arrow"><Icon name="arrow-right" size={18} /></span><label className="field"><span className="field-label">Дата окончания</span><input className="input" type="date" required min={start || undefined} value={end} onChange={event => setEnd(event.target.value)} /></label></div><div className="req-date-caption"><Icon name="clock" size={16} /><span>{days ? <><strong>{days}</strong> {calendarDayLabel(days)} в выбранном периоде</> : 'Выберите даты начала и окончания отпуска'}</span></div></> : <><label className="field"><span className="field-label">Сумма, ₸</span><input className="input req-amount-input" type="number" inputMode="decimal" min="0.01" max="1000000" step="0.01" required value={amount} onChange={event => setAmount(event.target.value)} placeholder="Например, 50 000" /></label><p className="req-field-help">Допустимая сумма — от 0,01 до 1 000 000 ₸.</p></>}</section>
        <section className="card req-form-card"><div className="req-card-heading"><h2><Icon name="message" size={19} /> Комментарий к заявке</h2><span className="muted">Необязательно</span></div><label className="field"><span className="req-sr-only">Комментарий к заявке</span><textarea className="input req-comment" value={comment} maxLength={2000} onChange={event => setComment(event.target.value)} placeholder={type === 'leave' ? 'Укажите дополнительную информацию для руководителя…' : 'Расскажите, с чем связан запрос на аванс…'} /></label><div className="req-character-count">{comment.length} / 2000</div></section>
        {validation && <p className="req-validation" role="alert"><Icon name="info" size={17} />{validation}</p>}
        <div className="req-form-actions"><Link className="btn btn-ghost" to="/requests">Отмена</Link><div><button type="button" className="btn btn-secondary" onClick={saveDraft}><Icon name="file" size={16} /> Сохранить черновик</button><button type="submit" className="btn btn-primary">Перейти к подтверждению <Icon name="arrow-right" size={17} /></button></div></div>
      </form> : <>
        <section className="card req-form-card"><h2><Icon name="file" size={20} /> Сводка заявки</h2><div className="req-summary-grid req-confirm-summary"><div><span>ТИП ОБРАЩЕНИЯ</span><strong>{type === 'leave' ? 'Трудовой отпуск' : 'Выплата аванса'}</strong></div><div><span>{type === 'leave' ? 'ПЕРИОД И ПРОДОЛЖИТЕЛЬНОСТЬ' : 'СУММА К ЗАПРОСУ'}</span><strong>{type === 'leave' ? `${formatDay(start)} — ${formatDay(end)}` : money(Number(amount.replace(',', '.')))}</strong>{type === 'leave' && <small>{days} {calendarDayLabel(days)}</small>}</div><div><span>СОТРУДНИК</span><strong>{profile.full_name}</strong><small>{profile.job_title}</small></div><div><span>ПОДРАЗДЕЛЕНИЕ</span><strong>{profile.department}</strong><small>{profile.company}</small></div></div>{comment.trim() && <div className="req-confirm-comment"><span>КОММЕНТАРИЙ</span><p>{comment.trim()}</p></div>}</section>
        <section className="card req-form-card"><h2><Icon name="clock" size={19} /> Маршрут согласования</h2><ol className="req-route"><li><span className="req-route-icon">1</span><div><strong>Подача заявки сотрудником</strong><p>{profile.full_name} · Проверка и отправка обращения</p></div><span className="badge badge-approved">Сейчас</span></li><li><span className="req-route-icon">2</span><div><strong>Рассмотрение руководителем или HR</strong><p>Решение и комментарий сохранятся в истории заявки</p></div></li><li><span className="req-route-icon">3</span><div><strong>Уведомление о решении</strong><p>Результат появится в вашем личном кабинете</p></div></li></ol></section>
        <section className="card req-form-card"><label className="req-confirm-check"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} disabled={submitting} /><span><strong>Подтверждаю корректность указанных данных</strong><small>После отправки заявка будет доступна для рассмотрения руководителю или HR.</small></span></label>{Boolean(error) && <ErrorState error={error} />}<div className="req-confirm-actions"><button className="btn btn-secondary" disabled={submitting} onClick={() => { setStep(1); setConfirmed(false); setError(null); }}><Icon name="chevron-left" size={16} /> Вернуться к редактированию</button><button className="btn btn-primary" disabled={!confirmed || submitting} onClick={submit}>{submitting ? 'Отправляем заявку…' : 'Подтвердить и отправить'}<Icon name="check" size={17} /></button></div></section>
      </>}
    </div><aside className="stack req-form-aside">
      <section className="card req-balance-card"><h2><Icon name="wallet" size={20} /> Баланс отпусков</h2><div className="req-balance-main"><span>ДОСТУПНЫЙ БАЛАНС</span><div><strong>{profile.vacation_days_remaining}</strong> <span>дней</span></div></div>{type === 'leave' && <div className="req-balance-period"><span>Выбранный период</span><strong>{days || '—'} <small>календ. дн.</small></strong></div>}<p className="req-field-help">Актуальное значение из кадрового профиля. Отправка заявки сама по себе не изменяет баланс.</p></section>
      <section className="card req-form-card req-help-card"><h2><Icon name="info" size={19} /> Памятка сотрудника</h2><div><strong>Проверьте параметры</strong><p>{type === 'leave' ? 'Убедитесь, что даты соответствуют вашим планам. Продолжительность показана в календарных днях.' : 'Убедитесь, что сумма указана в тенге и соответствует вашему запросу.'}</p></div><div><strong>Добавьте комментарий</strong><p>Дополнительная информация поможет руководителю принять решение.</p></div><div><strong>Следите за статусом</strong><p>История согласования и решение будут доступны в разделе «Мои заявки».</p></div></section>
      <button className="req-aside-link" onClick={() => navigate('/jana')}><span className="req-type-icon"><Icon name="sparkles" size={20} /></span><span><strong>Нужна помощь?</strong><small>Спросите AI Jana о кадровых вопросах</small></span><Icon name="chevron-right" size={18} /></button>
    </aside></div>
  </div>;
}

function validDateParam(value: unknown): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return '';
  const parsed = parseDay(value);
  return Number.isNaN(parsed.getTime()) || dateKey(parsed) !== value ? '' : value;
}

function RequestDetails({ id }: { id: string }) {
  const { api, profile, refresh, refreshKey, notify } = usePortal();
  const [record, setRecord] = useState<RequestRecord | null>(null);
  const [history, setHistory] = useState<RequestEvent[]>([]);
  const [people, setPeople] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [historyError, setHistoryError] = useState<unknown>(null);
  const [reviewError, setReviewError] = useState<unknown>(null);
  const [reload, setReload] = useState(0);
  const [reviewComment, setReviewComment] = useState('');
  const [decision, setDecision] = useState<'approved' | 'rejected' | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const reviewInFlight = useRef(false);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setHistoryError(null);
    api.getRequest(id).then(data => { if (active) setRecord(data); }).catch(reason => { if (active) setError(reason); }).finally(() => { if (active) setLoading(false); });
    api.getRequestHistory(id).then(data => { if (active) setHistory(data); }).catch(reason => { if (active) setHistoryError(reason); });
    return () => { active = false; };
  }, [api, id, reload, refreshKey]);
  useEffect(() => {
    let active = true;
    if (profile.role === 'manager' || profile.role === 'hr_admin') api.getTeam().then(data => { if (active) setPeople(data); }).catch(() => { /* Show identifier if employee details are unavailable. */ });
    return () => { active = false; };
  }, [api, profile.role]);
  const employee = record?.employee_id === profile.id ? profile : people.find(person => person.id === record?.employee_id);
  const canReview = Boolean(record && record.employee_id !== profile.id && record.status === 'pending' && (profile.role === 'manager' || profile.role === 'hr_admin'));
  async function review() {
    if (!decision || !record || reviewInFlight.current) return;
    reviewInFlight.current = true;
    setReviewing(true);
    setReviewError(null);
    try {
      const updated = await api.reviewRequest(record.id, { status: decision, reviewer_comment: reviewComment.trim() || null });
      setRecord(updated);
      setDecision(null);
      refresh();
      notify(updated.status === 'approved' ? 'Заявка согласована' : 'Заявка отклонена');
    } catch (reason) { setReviewError(reason); }
    finally { setReviewing(false); reviewInFlight.current = false; }
  }
  if (loading) return <LoadingState />;
  if (error || !record) return <div className="stack"><Link className="req-back" to="/requests"><Icon name="chevron-left" size={16} /> Назад ко всем заявкам</Link><ErrorState error={error || 'Заявка не найдена'} retry={() => setReload(value => value + 1)} /></div>;
  return <div className="req-page"><Link className="req-back" to="/requests"><Icon name="chevron-left" size={16} /> Назад ко всем заявкам <span>/</span> {requestNumber(record.id)}</Link><PageHeader title={`${requestLabel(record)}`} description={`№ ${requestNumber(record.id)} · Создана ${formatTime(record.created_at)}`} actions={<StatusBadge status={record.status} />} /><div className="req-form-layout"><div className="stack"><section className="card req-form-card"><h2><Icon name="file" size={19} /> Параметры обращения</h2><div className="req-detail-summary"><div><span className="req-type-icon"><Icon name="user" size={20} /></span><div><span>Инициатор заявки</span><strong>{employee?.full_name || `Сотрудник ${record.employee_id.slice(0, 8)}`}</strong>{employee && <small>{employee.job_title}</small>}</div></div><div><span className="req-type-icon"><Icon name={record.request_type === 'leave' ? 'calendar' : 'wallet'} size={20} /></span><div><span>{record.request_type === 'leave' ? 'Период отсутствия' : 'Сумма аванса'}</span><strong>{record.request_type === 'leave' ? `${formatDay(record.start_date)} — ${formatDay(record.end_date)}` : money(record.amount || 0)}</strong>{record.start_date && record.end_date && <small className="req-green">{dayCount(record.start_date, record.end_date)} {calendarDayLabel(dayCount(record.start_date, record.end_date))}</small>}</div></div>{employee && <div><span className="req-type-icon"><Icon name="building" size={20} /></span><div><span>Подразделение</span><strong>{employee.department}</strong><small>{employee.company}</small></div></div>}<div><span className="req-type-icon"><Icon name="clock" size={20} /></span><div><span>Последнее обновление</span><strong>{formatTime(record.updated_at)}</strong><small>{record.reviewed_at ? 'Решение принято' : record.status === 'pending' ? 'Ожидает рассмотрения' : 'Статус обновлён'}</small></div></div></div></section>
      {record.request_type === 'leave' && record.status === 'approved' && <LeaveCalendarDownload requestId={record.id} />}
      <section className="card req-form-card"><div className="req-card-heading"><h2><Icon name="clock" size={19} /> История согласования</h2><span className="muted">Хронология заявки</span></div>{historyError ? <ErrorState error={historyError} retry={() => setReload(value => value + 1)} /> : history.length ? <ol className="req-history">{history.map(event => <li key={event.id}><span className={`req-history-dot req-history-${event.event_type}`}><Icon name={event.event_type === 'rejected' ? 'x' : 'check'} size={15} /></span><div><div className="req-history-title"><strong>{event.event_type === 'created' ? 'Заявка подана сотрудником' : event.event_type === 'approved' ? 'Заявка согласована' : 'Заявка отклонена'}</strong><time dateTime={event.created_at}>{formatTime(event.created_at)}</time></div><p>{event.event_type === 'created' ? employee?.full_name || 'Сотрудник' : people.find(person => person.id === event.actor_id)?.full_name || (event.actor_id === profile.id ? profile.full_name : 'Руководитель / HR')}</p>{event.comment && <p className="req-history-comment">{event.comment}</p>}</div></li>)}{record.status === 'pending' && <li><span className="req-history-dot req-history-pending"><Icon name="clock" size={15} /></span><div><strong>Ожидает рассмотрения</strong><p>Руководитель или HR проверит заявку и примет решение.</p></div></li>}</ol> : <p className="muted">История изменений пока отсутствует.</p>}</section>
      <section className="card req-form-card"><h2><Icon name="message" size={19} /> Комментарии к заявке</h2><div className="req-comment-block"><strong>Комментарий сотрудника</strong><p>{record.comment || 'Комментарий не добавлен.'}</p></div>{record.reviewer_comment && <div className="req-comment-block req-reviewer-comment"><strong>Комментарий согласующего</strong><p>{record.reviewer_comment}</p></div>}</section>
      {canReview && <section className="card req-form-card req-review-card"><h2><Icon name="check" size={19} /> Рассмотрение заявки</h2><label className="field"><span className="field-label">Комментарий к решению</span><textarea className="input req-comment" maxLength={2000} value={reviewComment} disabled={reviewing} onChange={event => { setReviewComment(event.target.value); setDecision(null); }} placeholder="Укажите причину или оставьте пояснение для сотрудника…" /></label>{Boolean(reviewError) && <ErrorState error={reviewError} retry={() => setReload(value => value + 1)} />}{decision ? <div className="req-decision-confirm"><p>Подтвердите решение: <strong>{decision === 'approved' ? 'согласовать' : 'отклонить'} заявку</strong>. Решение будет сохранено в истории и отправлено сотруднику.</p><div><button className="btn btn-secondary" disabled={reviewing} onClick={() => setDecision(null)}>Вернуться</button><button className={`btn ${decision === 'approved' ? 'btn-primary' : 'req-btn-danger'}`} disabled={reviewing} onClick={review}>{reviewing ? 'Сохраняем…' : 'Подтвердить решение'}</button></div></div> : <div className="req-review-actions"><button className="btn req-btn-danger-outline" onClick={() => setDecision('rejected')}><Icon name="x" size={17} /> Отклонить</button><button className="btn btn-primary" onClick={() => setDecision('approved')}><Icon name="check" size={17} /> Согласовать заявку</button></div>}</section>}
    </div><aside className="stack"><section className="card req-form-card"><h2>Карточка заявки</h2><dl className="req-metadata"><div><dt>Номер</dt><dd>{requestNumber(record.id)}</dd></div><div><dt>Тип</dt><dd>{record.request_type === 'leave' ? 'Отпуск' : 'Аванс'}</dd></div><div><dt>Создана</dt><dd>{formatDay(record.created_at)}</dd></div><div><dt>Статус</dt><dd><StatusBadge status={record.status} /></dd></div>{record.reviewed_at && <div><dt>Рассмотрена</dt><dd>{formatDay(record.reviewed_at)}</dd></div>}</dl>{record.request_type === 'leave' && <Link className="btn btn-secondary req-full-width" to={`/calendar?date=${record.start_date || ''}`}><Icon name="calendar" size={16} /> Открыть в календаре</Link>}</section><div className="req-detail-note"><Icon name="info" size={20} /><p>{record.status === 'pending' ? 'Заявка на рассмотрении. Когда решение будет принято, вы увидите обновление статуса и комментарий согласующего.' : 'Решение по заявке сохранено. Если у вас есть вопросы, обратитесь к своему руководителю или в HR.'}</p></div></aside></div></div>;
}
