import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { usePortal } from '../context';
import { ErrorState, Icon, LoadingState, PageHeader, StatusBadge } from '../components/ui';
import { dateKey, dayCount, formatDay, loadRequests, parseDay, requestNumber } from './Requests';
import type { RequestRecord } from './Requests';
import type { EmployeeProfile } from '../lib/types';
import './requests.css';

const weekdays = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС'];

function todayDate(): string {
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Qyzylorda', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
  return `${parts.find(part => part.type === 'year')?.value}-${parts.find(part => part.type === 'month')?.value}-${parts.find(part => part.type === 'day')?.value}`;
}

function safeDate(value: string | null, fallback: string): string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return fallback;
  const parsed = parseDay(value);
  return Number.isNaN(parsed.getTime()) || dateKey(parsed) !== value ? fallback : value;
}

function monthStart(date: Date): Date { return new Date(date.getFullYear(), date.getMonth(), 1, 12); }
function monthLabel(date: Date): string { return date.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' }).replace(' г.', ''); }
function shiftMonth(date: Date, delta: number): Date { return new Date(date.getFullYear(), date.getMonth() + delta, 1, 12); }
function calendarDays(date: Date): Date[] {
  const first = monthStart(date);
  const offset = (first.getDay() + 6) % 7;
  return Array.from({ length: 42 }, (_, index) => new Date(first.getFullYear(), first.getMonth(), index - offset + 1, 12));
}

export default function Calendar() {
  const { api, profile, refreshKey } = usePortal();
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const today = todayDate();
  const initial = safeDate(params.get('date') || params.get('start'), today);
  const [month, setMonth] = useState(monthStart(parseDay(initial)));
  const [selected, setSelected] = useState(initial);
  const [rangeStart, setRangeStart] = useState(safeDate(params.get('start'), ''));
  const [rangeEnd, setRangeEnd] = useState(safeDate(params.get('end'), ''));
  const [records, setRecords] = useState<RequestRecord[]>([]);
  const [team, setTeam] = useState<EmployeeProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reload, setReload] = useState(0);
  const [scope, setScope] = useState<'own' | 'team'>('own');
  const [focusedDay, setFocusedDay] = useState(initial);
  const calendarRoot = useRef<HTMLElement>(null);
  const pendingFocus = useRef(false);
  const isSelecting = params.get('select') === '1';
  const isReviewer = profile.role === 'manager' || profile.role === 'hr_admin';

  useEffect(() => {
    if (!pendingFocus.current) return;
    pendingFocus.current = false;
    calendarRoot.current?.querySelector<HTMLButtonElement>(`button[data-day="${focusedDay}"]:not(:disabled)`)?.focus();
  }, [focusedDay, month]);

  function handleDayKey(event: KeyboardEvent<HTMLButtonElement>, day: string) {
    const current = parseDay(day);
    const offsets: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    let target: Date;
    if (event.key in offsets) target = new Date(current.getFullYear(), current.getMonth(), current.getDate() + offsets[event.key], 12);
    else if (event.key === 'Home') target = new Date(current.getFullYear(), current.getMonth(), current.getDate() - (current.getDay() + 6) % 7, 12);
    else if (event.key === 'End') target = new Date(current.getFullYear(), current.getMonth(), current.getDate() + 6 - (current.getDay() + 6) % 7, 12);
    else if (event.key === 'PageUp' || event.key === 'PageDown') {
      const offset = event.key === 'PageUp' ? -1 : 1;
      const targetMonth = shiftMonth(current, offset);
      const lastDay = new Date(targetMonth.getFullYear(), targetMonth.getMonth() + 1, 0, 12).getDate();
      target = new Date(targetMonth.getFullYear(), targetMonth.getMonth(), Math.min(current.getDate(), lastDay), 12);
    } else return;
    event.preventDefault();
    const targetKey = dateKey(target);
    const lastVisibleMonth = isSelecting ? shiftMonth(month, 1) : month;
    if (monthStart(target) < month || monthStart(target) > lastVisibleMonth) setMonth(monthStart(target));
    pendingFocus.current = true;
    setFocusedDay(targetKey);
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    loadRequests(api, { request_type: 'leave', ...(scope === 'own' ? { employee_id: profile.id } : {}) })
      .then(data => { if (active) setRecords(data); })
      .catch(reason => { if (active) setError(reason); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api, profile.id, scope, refreshKey, reload]);

  useEffect(() => {
    let active = true;
    if (isReviewer) api.getTeam().then(data => { if (active) setTeam(data); }).catch(() => { /* Request identifiers remain available. */ });
    return () => { active = false; };
  }, [api, isReviewer]);

  const activeLeaves = useMemo(() => records.filter(request => (scope !== 'team' || request.employee_id !== profile.id) && request.request_type === 'leave' && request.start_date && request.end_date && (request.status === 'approved' || request.status === 'pending')), [records, scope, profile.id]);
  const people = useMemo(() => new Map([profile, ...team].map(person => [person.id, person])), [profile, team]);
  const selectedEvents = activeLeaves.filter(request => request.start_date! <= selected && request.end_date! >= selected);
  const firstKey = dateKey(month);
  const lastKey = dateKey(new Date(month.getFullYear(), month.getMonth() + 1, 0, 12));
  const monthLeaves = activeLeaves.filter(request => request.start_date! <= lastKey && request.end_date! >= firstKey);
  const upcoming = activeLeaves.filter(request => request.end_date! >= today).sort((a, b) => a.start_date!.localeCompare(b.start_date!)).slice(0, 3);
  const selectedDays = rangeStart && rangeEnd && rangeEnd >= rangeStart ? dayCount(rangeStart, rangeEnd) : 0;

  function countMonthDays(status: string) {
    const uniqueDays = new Set<string>();
    monthLeaves.filter(request => request.status === status).forEach(request => {
      const start = parseDay(request.start_date! < firstKey ? firstKey : request.start_date!);
      const end = request.end_date! > lastKey ? lastKey : request.end_date!;
      for (let cursor = start; dateKey(cursor) <= end; cursor = new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate() + 1, 12)) uniqueDays.add(`${scope === 'team' ? request.employee_id : ''}:${dateKey(cursor)}`);
    });
    return uniqueDays.size;
  }

  function selectRange(day: string) {
    if (!rangeStart || rangeEnd) { setRangeStart(day); setRangeEnd(''); }
    else if (day < rangeStart) { setRangeEnd(rangeStart); setRangeStart(day); }
    else setRangeEnd(day);
  }

  function startPlanning() {
    setRangeStart('');
    setRangeEnd('');
    setScope('own');
    setParams({ select: '1' });
  }

  function proceed() {
    if (!selectedDays) return;
    navigate(`/requests/new?type=leave&start=${rangeStart}&end=${rangeEnd}`, { state: location.state });
  }

  if (isSelecting) return <div className="cal-page"><Link className="req-back" to="/calendar"><Icon name="chevron-left" size={16} /> Календарь <span>/</span> Выбор дат отпуска</Link><PageHeader eyebrow="ПЛАНИРОВАНИЕ ОТПУСКА" title="Выберите период отпуска" description="Укажите дату начала и окончания. Мы посчитаем календарные дни в выбранном периоде." actions={<div className="cal-balance-pill"><Icon name="wallet" size={22} /><span>Текущий баланс<strong>{profile.vacation_days_remaining} дней</strong></span></div>} /><div className="cal-range-layout"><section className="card cal-range-card" ref={calendarRoot}><div className="cal-range-top"><button className="btn btn-ghost cal-icon-button" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Предыдущий месяц"><Icon name="chevron-left" size={20} /></button><h2>{monthLabel(month)} — {monthLabel(shiftMonth(month, 1))}</h2><button className="btn btn-ghost cal-icon-button" onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Следующий месяц"><Icon name="chevron-right" size={20} /></button></div><div className="cal-range-legend"><span><i className="cal-dot cal-dot-selected" />Выбранный период</span><span><i className="cal-dot cal-dot-weekend" />Суббота и воскресенье</span><span><i className="cal-dot cal-dot-today" />Сегодня</span></div><div className="cal-mini-months">{[month, shiftMonth(month, 1)].map(displayMonth => <div key={dateKey(displayMonth)} className="cal-mini-month"><h3>{monthLabel(displayMonth)}</h3><div className="cal-mini-grid">{weekdays.map((day, index) => <span key={day} className={`cal-mini-weekday ${index > 4 ? 'cal-weekend-text' : ''}`}>{day}</span>)}{calendarDays(displayMonth).map(day => {
        const key = dateKey(day);
        const inMonth = day.getMonth() === displayMonth.getMonth();
        const inRange = Boolean(rangeStart && rangeEnd && key >= rangeStart && key <= rangeEnd);
        const endpoint = key === rangeStart || key === rangeEnd;
        const weekend = day.getDay() === 0 || day.getDay() === 6;
        return <button key={key} data-day={key} onFocus={() => setFocusedDay(key)} onKeyDown={event => handleDayKey(event, key)} className={`cal-mini-day ${!inMonth ? 'outside' : ''} ${weekend ? 'weekend' : ''} ${inRange ? 'in-range' : ''} ${endpoint ? 'endpoint' : ''} ${key === today ? 'is-today' : ''}`} disabled={!inMonth} onClick={() => selectRange(key)} aria-label={`${formatDay(key, true)}${endpoint ? ', граница выбранного периода' : ''}`} aria-pressed={endpoint || inRange}><span>{day.getDate()}</span></button>;
      })}</div></div>)}</div><div className="cal-select-instruction"><Icon name="info" size={17} /><span>{!rangeStart ? 'Выберите первый день отпуска.' : !rangeEnd ? 'Теперь выберите последний день. Для одного дня нажмите ту же дату ещё раз.' : `Выбран период: ${formatDay(rangeStart)} — ${formatDay(rangeEnd)}.`}</span></div><div className="cal-range-inputs"><label className="field"><span className="field-label">Дата начала</span><input className="input" type="date" value={rangeStart} onChange={event => { setRangeStart(event.target.value); if (rangeEnd && event.target.value > rangeEnd) setRangeEnd(''); }} /></label><Icon name="arrow-right" size={20} /><label className="field"><span className="field-label">Дата окончания</span><input className="input" type="date" value={rangeEnd} min={rangeStart || undefined} onChange={event => setRangeEnd(event.target.value)} /></label></div></section><aside className="stack"><section className="card cal-range-summary"><h2>Расчёт периода</h2><dl className="req-metadata"><div><dt>Дата начала</dt><dd>{formatDay(rangeStart, true)}</dd></div><div><dt>Дата окончания</dt><dd>{formatDay(rangeEnd, true)}</dd></div></dl><div className="cal-duration"><span>Продолжительность</span><strong>{selectedDays || '—'}<small> календарных дней</small></strong></div><div className="cal-range-notice"><Icon name="info" size={20} /><p>Период включает все календарные дни. Точные условия предоставления отпуска уточняются при согласовании заявки.</p></div></section><div className="req-detail-note"><Icon name="calendar" size={20} /><p>Выбор дат не создаёт заявку. На следующем шаге можно добавить комментарий, проверить данные и отправить их на согласование.</p></div></aside></div><div className="card cal-range-footer"><Link className="btn btn-ghost" to="/calendar"><Icon name="chevron-left" size={17} /> Вернуться в календарь</Link><button className="btn btn-secondary" onClick={() => { setRangeStart(''); setRangeEnd(''); }}>Сбросить выбор</button><div><span>{selectedDays ? `${selectedDays} календарных дней` : 'Период не выбран'}</span><button className="btn btn-primary" disabled={!selectedDays} onClick={proceed}>Продолжить оформление <Icon name="arrow-right" size={17} /></button></div></div></div>;

  return <div className="cal-page"><PageHeader eyebrow="ВАШЕ ВРЕМЯ" title="Календарь" description="Планируйте отпуск и отслеживайте согласованные периоды отсутствия." actions={<button className="btn btn-primary" onClick={startPlanning}><Icon name="plus" size={18} /> Запланировать отпуск</button>} /><div className="card cal-toolbar"><div className="cal-month-controls"><button className="btn btn-ghost cal-icon-button" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Предыдущий месяц"><Icon name="chevron-left" size={20} /></button><span><Icon name="calendar" size={18} /><strong>{monthLabel(month)}</strong></span><button className="btn btn-ghost cal-icon-button" onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Следующий месяц"><Icon name="chevron-right" size={20} /></button></div><button className="btn btn-secondary" onClick={() => { setMonth(monthStart(parseDay(today))); setSelected(today); }}>Сегодня</button>{isReviewer && <div className="req-scope-switch cal-scope"><button className={scope === 'own' ? 'active' : ''} onClick={() => setScope('own')}>Мой календарь</button><button className={scope === 'team' ? 'active' : ''} onClick={() => setScope('team')}>Команда</button></div>}<div className="cal-toolbar-legend"><span><i className="cal-dot cal-dot-approved" />Согласовано</span><span><i className="cal-dot cal-dot-pending" />На согласовании</span></div></div>{error ? <ErrorState error={error} retry={() => setReload(value => value + 1)} /> : loading ? <LoadingState /> : <div className="cal-main-layout"><section className="card cal-month-card" ref={calendarRoot}><div className="cal-month-note"><span><i className="cal-dot cal-dot-approved" />{scope === 'own' ? 'Мои отпуска' : 'Отпуска сотрудников'}</span><span>{monthLeaves.length} заявок в этом месяце</span></div><div className="cal-weekdays">{weekdays.map((day, index) => <span className={index > 4 ? 'cal-weekend-text' : ''} key={day}>{day}</span>)}</div><div className="cal-month-grid" role="group" aria-label={monthLabel(month)}>{calendarDays(month).map(day => {
        const key = dateKey(day);
        const isCurrentMonth = day.getMonth() === month.getMonth();
        const events = activeLeaves.filter(request => request.start_date! <= key && request.end_date! >= key);
        const weekend = day.getDay() === 0 || day.getDay() === 6;
        const approved = events.some(request => request.status === 'approved');
        const pending = events.some(request => request.status === 'pending');
        return <button key={key} data-day={key} onFocus={() => setFocusedDay(key)} onKeyDown={event => handleDayKey(event, key)} className={`cal-day ${!isCurrentMonth ? 'outside' : ''} ${weekend ? 'weekend' : ''} ${approved ? 'has-approved' : pending ? 'has-pending' : ''} ${key === selected ? 'selected' : ''} ${key === today ? 'today' : ''}`} onClick={() => { setSelected(key); if (!isCurrentMonth) setMonth(monthStart(day)); }} aria-label={`${formatDay(key, true)}, ${events.length ? `${events.length} заявок на отпуск` : 'нет заявок на отпуск'}`} aria-pressed={key === selected}><span className="cal-day-top"><span>{day.getDate()}</span>{events.length > 0 && <Icon name="calendar" size={13} />}</span><div className="cal-day-events">{events.slice(0, 2).map(request => <span key={request.id} className={`cal-event cal-event-${request.status}`}><i />{scope === 'team' ? people.get(request.employee_id)?.full_name.split(' ').slice(0, 2).join(' ') || 'Отпуск' : 'Отпуск'}</span>)}{events.length > 2 && <span className="cal-event-more">Ещё {events.length - 2}</span>}</div>{events.length > 0 && scope === 'own' && <span className="cal-day-caption">{approved ? 'Согласовано' : 'На согласовании'}</span>}</button>;
      })}</div><div className="cal-grid-footer"><Icon name="info" size={16} /><span>В календаре показаны заявки на отпуск. Выберите день, чтобы открыть подробности.</span></div></section><aside className="stack cal-sidebar"><section className="card cal-summary"><div className="cal-summary-title"><div><span className="req-eyebrow">СВОДКА МЕСЯЦА</span><h2>{monthLabel(month)}</h2></div><span className="req-type-icon"><Icon name="calendar" size={20} /></span></div><div className="cal-summary-tiles"><div className="cal-summary-approved"><span>Согласованный отпуск</span><strong>{countMonthDays('approved')} <small>дн.</small></strong></div><div className="cal-summary-pending"><span>На согласовании</span><strong>{countMonthDays('pending')} <small>дн.</small></strong></div><div><span>Заявок в месяце</span><strong>{monthLeaves.length}</strong></div><div><span>Мой баланс отпуска</span><strong>{profile.vacation_days_remaining} <small>дн.</small></strong></div></div>{scope === 'team' && <p className="req-field-help">Дни отсутствия суммируются по сотрудникам.</p>}</section><section className="card cal-selected-day"><div className="cal-selected-heading"><Icon name="calendar" size={22} /><h2>{formatDay(selected, true)}</h2></div>{selectedEvents.length ? <div className="cal-selected-events">{selectedEvents.map(request => <div key={request.id} className="cal-selected-event"><StatusBadge status={request.status} /><strong>{scope === 'team' ? people.get(request.employee_id)?.full_name || 'Сотрудник' : 'Трудовой отпуск'}</strong><span>{formatDay(request.start_date)} — {formatDay(request.end_date)}</span>{request.comment && <p>{request.comment}</p>}<Link className="btn btn-secondary" to={`/requests/${request.id}`}>Открыть {requestNumber(request.id)}<Icon name="arrow-right" size={15} /></Link></div>)}</div> : <div className="cal-no-events"><div className="cal-empty-icon"><Icon name="calendar" size={24} /></div><strong>Отпуск не запланирован</strong><p>На эту дату нет заявок на отпуск.</p><button className="btn btn-secondary" onClick={() => { setRangeStart(selected); setRangeEnd(''); setScope('own'); setParams({ select: '1' }); }}>Выбрать этот день <Icon name="arrow-right" size={15} /></button></div>}</section><section className="card cal-upcoming"><span className="req-eyebrow">БЛИЖАЙШИЕ ОТПУСКА</span>{upcoming.length ? upcoming.map(request => <Link key={request.id} to={`/requests/${request.id}`}><span className={`req-type-icon ${request.status === 'pending' ? 'cal-upcoming-pending' : ''}`}><Icon name="calendar" size={18} /></span><span><strong>{scope === 'team' ? people.get(request.employee_id)?.full_name || 'Сотрудник' : request.start_date! <= today ? 'Текущий отпуск' : 'Начало отпуска'}</strong><small>{formatDay(request.start_date)} · {dayCount(request.start_date!, request.end_date!)} дн.</small></span><Icon name="chevron-right" size={16} /></Link>) : <p className="muted">Ближайших отпусков пока нет. Самое время запланировать отдых.</p>}</section></aside></div>}</div>;
}
