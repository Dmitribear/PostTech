import type { RequestRecord } from '@/entities/hr-request';
import {
  businessDate,
  dateKey,
  dayCount,
  dayWord,
  formatDay,
  leaveConflicts,
  loadRequests,
  parseDay,
  requestNumber,
} from '@/entities/hr-request';
import { usePortal } from '@/entities/session';
import { LeaveBalance } from '@/features/leave-balance';
import type { EmployeeProfile } from '@/shared/api/contracts';
import { localizedDate, t, tx } from '@/shared/lib/i18n';
import '@/shared/styles/requests.css';
import { ErrorState, Icon, LoadingState, PageHeader, StatusBadge } from '@/shared/ui/index';
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';

const weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

function safeDate(value: string | null, fallback: string): string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return fallback;
  const parsed = parseDay(value);
  return Number.isNaN(parsed.getTime()) || dateKey(parsed) !== value ? fallback : value;
}

function monthStart(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1, 12);
}
function monthLabel(date: Date): string {
  return localizedDate(date, { month: 'long', year: 'numeric' }).replace(' г.', '');
}
function shiftMonth(date: Date, delta: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + delta, 1, 12);
}
function calendarDays(date: Date): Date[] {
  const first = monthStart(date);
  const offset = (first.getDay() + 6) % 7;
  const days = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  const cells = Math.ceil((offset + days) / 7) * 7;
  return Array.from(
    { length: cells },
    (_, index) => new Date(first.getFullYear(), first.getMonth(), index - offset + 1, 12),
  );
}

export default function Calendar() {
  const { api, profile, refreshKey } = usePortal();
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const today = businessDate();
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
  const [compact, setCompact] = useState(() => window.matchMedia('(max-width: 900px)').matches);
  useEffect(() => {
    const query = window.matchMedia('(max-width: 900px)');
    const update = () => setCompact(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  const [focusedDay, setFocusedDay] = useState(initial);
  const calendarRoot = useRef<HTMLElement>(null);
  const pendingFocus = useRef(false);
  const [availableDays, setAvailableDays] = useState<number | null>(null);
  const isSelecting = params.get('select') === '1';
  const isReviewer = ['manager', 'director'].includes(profile.role) || profile.role === 'hr_admin';

  useEffect(() => {
    if (!pendingFocus.current) return;
    pendingFocus.current = false;
    calendarRoot.current
      ?.querySelector<HTMLButtonElement>(`button[data-day="${focusedDay}"]:not(:disabled)`)
      ?.focus();
  }, [focusedDay, month]);

  function handleDayKey(event: KeyboardEvent<HTMLButtonElement>, day: string) {
    const current = parseDay(day);
    const offsets: Record<string, number> = {
      ArrowLeft: -1,
      ArrowRight: 1,
      ArrowUp: -7,
      ArrowDown: 7,
    };
    let target: Date;
    if (event.key in offsets)
      target = new Date(
        current.getFullYear(),
        current.getMonth(),
        current.getDate() + offsets[event.key],
        12,
      );
    else if (event.key === 'Home')
      target = new Date(
        current.getFullYear(),
        current.getMonth(),
        current.getDate() - ((current.getDay() + 6) % 7),
        12,
      );
    else if (event.key === 'End')
      target = new Date(
        current.getFullYear(),
        current.getMonth(),
        current.getDate() + 6 - ((current.getDay() + 6) % 7),
        12,
      );
    else if (event.key === 'PageUp' || event.key === 'PageDown') {
      const offset = event.key === 'PageUp' ? -1 : 1;
      const targetMonth = shiftMonth(current, offset);
      const lastDay = new Date(
        targetMonth.getFullYear(),
        targetMonth.getMonth() + 1,
        0,
        12,
      ).getDate();
      target = new Date(
        targetMonth.getFullYear(),
        targetMonth.getMonth(),
        Math.min(current.getDate(), lastDay),
        12,
      );
    } else return;
    event.preventDefault();
    if (isSelecting && dateKey(target) < today) target = parseDay(today);
    const targetKey = dateKey(target);
    const lastVisibleMonth = isSelecting && !compact ? shiftMonth(month, 1) : month;
    if (monthStart(target) < month || monthStart(target) > lastVisibleMonth)
      setMonth(monthStart(target));
    pendingFocus.current = true;
    setFocusedDay(targetKey);
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    loadRequests(api, {
      request_type: 'leave',
      ...(isSelecting || scope === 'own' ? { scope: 'mine' } : { scope: 'all' }),
    })
      .then((data) => {
        if (active) setRecords(data);
      })
      .catch((reason) => {
        if (active) setError(reason);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, profile.id, scope, isSelecting, refreshKey, reload]);

  useEffect(() => {
    let active = true;
    if (isReviewer)
      api
        .getTeam()
        .then((data) => {
          if (active) setTeam(data);
        })
        .catch(() => {
          /* Request identifiers remain available. */
        });
    return () => {
      active = false;
    };
  }, [api, isReviewer]);

  const activeLeaves = useMemo(
    () =>
      records.filter(
        (request) =>
          (scope !== 'team' || request.employee_id !== profile.id) &&
          request.request_type === 'leave' &&
          request.start_date &&
          request.end_date &&
          (request.status === 'approved' || request.status === 'pending'),
      ),
    [records, scope, profile.id],
  );
  const people = useMemo(
    () => new Map([profile, ...team].map((person) => [person.id, person])),
    [profile, team],
  );
  const selectedEvents = activeLeaves.filter(
    (request) => request.start_date! <= selected && request.end_date! >= selected,
  );
  const firstKey = dateKey(month);
  const lastKey = dateKey(new Date(month.getFullYear(), month.getMonth() + 1, 0, 12));
  const monthLeaves = activeLeaves.filter(
    (request) => request.start_date! <= lastKey && request.end_date! >= firstKey,
  );
  const upcoming = activeLeaves
    .filter((request) => request.end_date! >= today)
    .sort((a, b) => a.start_date!.localeCompare(b.start_date!))
    .slice(0, 3);
  const selectedDays =
    rangeStart && rangeEnd && rangeEnd >= rangeStart ? dayCount(rangeStart, rangeEnd) : 0;
  const rangeConflicts = leaveConflicts(records, profile.id, rangeStart, rangeEnd);
  const pastRange = Boolean(rangeStart && rangeStart < today);
  const canContinue =
    availableDays !== null &&
    selectedDays <= availableDays &&
    Boolean(selectedDays && !pastRange && !rangeConflicts.length && !loading && !error);

  function countMonthDays(status: string) {
    const uniqueDays = new Set<string>();
    monthLeaves
      .filter((request) => request.status === status)
      .forEach((request) => {
        const start = parseDay(request.start_date! < firstKey ? firstKey : request.start_date!);
        const end = request.end_date! > lastKey ? lastKey : request.end_date!;
        for (
          let cursor = start;
          dateKey(cursor) <= end;
          cursor = new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate() + 1, 12)
        )
          uniqueDays.add(`${scope === 'team' ? request.employee_id : ''}:${dateKey(cursor)}`);
      });
    return uniqueDays.size;
  }

  function selectRange(day: string) {
    if (day < today) return;
    if (!rangeStart || rangeEnd) {
      setRangeStart(day);
      setRangeEnd('');
    } else if (day < rangeStart) {
      setRangeEnd(rangeStart);
      setRangeStart(day);
    } else setRangeEnd(day);
  }

  function startPlanning() {
    setRangeStart('');
    setRangeEnd('');
    setScope('own');
    if (month < monthStart(parseDay(today))) setMonth(monthStart(parseDay(today)));
    setParams({ select: '1' });
  }

  function proceed() {
    if (!canContinue) return;
    navigate(`/requests/new?type=leave&start=${rangeStart}&end=${rangeEnd}&review=1`, {
      state: location.state,
    });
  }

  if (isSelecting)
    return (
      <div className="cal-page cal-select-page">
        <Link className="req-back" to="/calendar">
          <Icon name="chevron-left" size={16} />
          {t(' Календарь')}
        </Link>
        <PageHeader title={t('Выбор дат')} />
        <div className="cal-range-layout">
          <section className="card cal-range-card" ref={calendarRoot}>
            <div className="cal-range-top">
              <button
                className="btn btn-ghost cal-icon-button"
                onClick={() => setMonth(shiftMonth(month, -1))}
                aria-label={t('Предыдущий месяц')}
              >
                <Icon name="chevron-left" size={20} />
              </button>
              <h2>
                {tx(monthLabel(month))}
                {tx(!compact && <> — {tx(monthLabel(shiftMonth(month, 1)))}</>)}
              </h2>
              <button
                className="btn btn-ghost cal-icon-button"
                onClick={() => setMonth(shiftMonth(month, 1))}
                aria-label={t('Следующий месяц')}
              >
                <Icon name="chevron-right" size={20} />
              </button>
            </div>
            <div className="cal-mini-months">
              {tx(
                (compact ? [month] : [month, shiftMonth(month, 1)]).map((displayMonth) => (
                  <div key={dateKey(displayMonth)} className="cal-mini-month">
                    <h3>{tx(monthLabel(displayMonth))}</h3>
                    <div className="cal-mini-grid">
                      {tx(
                        weekdays.map((day, index) => (
                          <span
                            key={day}
                            className={`cal-mini-weekday ${index > 4 ? 'cal-weekend-text' : ''}`}
                          >
                            {tx(day)}
                          </span>
                        )),
                      )}
                      {tx(
                        calendarDays(displayMonth).map((day) => {
                          const key = dateKey(day);
                          const inMonth = day.getMonth() === displayMonth.getMonth();
                          const inRange = Boolean(
                            rangeStart && rangeEnd && key >= rangeStart && key <= rangeEnd,
                          );
                          const endpoint = key === rangeStart || key === rangeEnd;
                          const weekend = day.getDay() === 0 || day.getDay() === 6;
                          const occupied = leaveConflicts(records, profile.id, key, key).length > 0;
                          return (
                            <button
                              key={key}
                              data-day={key}
                              onFocus={() => setFocusedDay(key)}
                              onKeyDown={(event) => handleDayKey(event, key)}
                              className={`cal-mini-day ${!inMonth ? 'outside' : ''} ${weekend ? 'weekend' : ''} ${inRange ? 'in-range' : ''} ${endpoint ? 'endpoint' : ''} ${key === today ? 'is-today' : ''} ${occupied ? 'is-occupied' : ''}`}
                              disabled={!inMonth || key < today}
                              onClick={() => selectRange(key)}
                              aria-label={`${formatDay(key, true)}${endpoint ? ', граница выбранного периода' : ''}${occupied ? ', ' + t('Уже есть заявка') : ''}`}
                              aria-pressed={endpoint || inRange}
                            >
                              <span>{tx(day.getDate())}</span>
                            </button>
                          );
                        }),
                      )}
                    </div>
                  </div>
                )),
              )}
            </div>
            {tx(
              !selectedDays && (
                <p className="cal-select-instruction" role="status">
                  {tx(
                    !rangeStart
                      ? 'Выберите первый день'
                      : 'Теперь последний. Для одного дня нажмите повторно.',
                  )}
                </p>
              ),
            )}
            <p className="cal-occupied-legend">
              <i />
              {t('Уже есть заявка')}
            </p>
            <details className="cal-manual-dates">
              <summary>
                {t('Ввести даты вручную')}
                <Icon name="chevron-down" size={15} />
              </summary>
              <div className="cal-range-inputs">
                <label className="field">
                  <span className="field-label">{t('Дата начала')}</span>
                  <input
                    className="input"
                    type="date"
                    value={rangeStart}
                    min={today}
                    onChange={(event) => {
                      setRangeStart(event.target.value);
                      if (rangeEnd && event.target.value > rangeEnd) setRangeEnd('');
                    }}
                  />
                </label>
                <Icon name="arrow-right" size={20} />
                <label className="field">
                  <span className="field-label">{t('Дата окончания')}</span>
                  <input
                    className="input"
                    type="date"
                    value={rangeEnd}
                    min={rangeStart > today ? rangeStart : today}
                    onChange={(event) => setRangeEnd(event.target.value)}
                  />
                </label>
              </div>
            </details>
          </section>
          <aside className="stack">
            <section
              className={`card cal-range-summary ${rangeConflicts.length ? 'has-conflict' : ''}`}
            >
              <div className="cal-selected-period" aria-live="polite">
                <div>
                  <span>{t('Выбрано дат')}</span>
                  <strong>
                    {tx(selectedDays || '—')} {tx(dayWord(selectedDays))}
                  </strong>
                </div>
                <span>
                  {tx(
                    selectedDays
                      ? `${formatDay(rangeStart)} — ${formatDay(rangeEnd)}`
                      : 'Период не выбран',
                  )}
                </span>
              </div>
              <LeaveBalance days={selectedDays} onAvailable={setAvailableDays} />
              {tx(
                loading ? (
                  <p className="req-field-help" role="status">
                    {t('Проверяем действующие заявки…')}
                  </p>
                ) : error ? (
                  <ErrorState error={error} retry={() => setReload((value) => value + 1)} />
                ) : pastRange ? (
                  <p className="req-validation cal-range-validation" role="alert">
                    {t('Отпуск может начаться сегодня или позже.')}
                  </p>
                ) : rangeConflicts.length ? (
                  <LeaveConflictNotice
                    records={rangeConflicts}
                    onChangeDates={() => {
                      setRangeStart('');
                      setRangeEnd('');
                      calendarRoot.current?.scrollIntoView({
                        block: 'start',
                        behavior: 'smooth',
                      });
                      calendarRoot.current
                        ?.querySelector<HTMLButtonElement>('button[data-day]:not(:disabled)')
                        ?.focus({ preventScroll: true });
                    }}
                  />
                ) : null,
              )}
            </section>
          </aside>
        </div>
        <div className="card cal-range-footer req-mobile-actions">
          {rangeConflicts.length > 0 && (
            <div className="cal-conflict-shortcut">
              <Icon name="info" size={16} />
              <a
                href="#leave-conflict"
                onClick={(event) => {
                  event.preventDefault();
                  document.getElementById('leave-conflict')?.focus();
                }}
              >
                {t('Уже есть заявка')}
                <Icon name="chevron-right" size={15} />
              </a>
            </div>
          )}
          <Link className="btn btn-ghost" to="/calendar">
            <Icon name="chevron-left" size={17} />
            {t(' Назад')}
          </Link>
          <button
            className="btn btn-secondary"
            onClick={() => {
              setRangeStart('');
              setRangeEnd('');
            }}
          >
            {t('Сбросить')}
          </button>
          <div>
            <button className="btn btn-primary" disabled={!canContinue} onClick={proceed}>
              {t('Продолжить')}
            </button>
          </div>
        </div>
      </div>
    );

  return (
    <div className="cal-page">
      <PageHeader
        title={t('Календарь')}
        actions={
          <button className="btn btn-primary" onClick={startPlanning}>
            <Icon name="plus" size={18} />
            {t(' Оформить отпуск')}
          </button>
        }
      />
      <div className="card cal-toolbar">
        <div className="cal-month-controls">
          <button
            className="btn btn-ghost cal-icon-button"
            onClick={() => setMonth(shiftMonth(month, -1))}
            aria-label={t('Предыдущий месяц')}
          >
            <Icon name="chevron-left" size={20} />
          </button>
          <span>
            <Icon name="calendar" size={18} />
            <strong>{tx(monthLabel(month))}</strong>
          </span>
          <button
            className="btn btn-ghost cal-icon-button"
            onClick={() => setMonth(shiftMonth(month, 1))}
            aria-label={t('Следующий месяц')}
          >
            <Icon name="chevron-right" size={20} />
          </button>
        </div>
        <button
          className="btn btn-secondary"
          onClick={() => {
            setMonth(monthStart(parseDay(today)));
            setSelected(today);
          }}
        >
          {t('Сегодня')}
        </button>
        {tx(
          isReviewer && (
            <div className="req-scope-switch cal-scope">
              <button className={scope === 'own' ? 'active' : ''} onClick={() => setScope('own')}>
                {t('Мой календарь')}
              </button>
              <button className={scope === 'team' ? 'active' : ''} onClick={() => setScope('team')}>
                {t('Команда')}
              </button>
            </div>
          ),
        )}
        <div className="cal-toolbar-legend">
          <span>
            <i className="cal-dot cal-dot-approved" />
            {t('Согласовано')}
          </span>
          <span>
            <i className="cal-dot cal-dot-pending" />
            {t('На согласовании')}
          </span>
        </div>
      </div>
      {error ? (
        <ErrorState error={error} retry={() => setReload((value) => value + 1)} />
      ) : loading ? (
        <LoadingState />
      ) : (
        <div className="cal-main-layout">
          <section className="card cal-month-card" ref={calendarRoot}>
            <div className="cal-month-note">
              <span>
                <i className="cal-dot cal-dot-approved" />
                {tx(scope === 'own' ? 'Мои отпуска' : 'Отпуска сотрудников')}
              </span>
              <span>
                {tx(monthLeaves.length)}
                {t(' заявок в этом месяце')}
              </span>
            </div>
            <div className="cal-weekdays">
              {tx(
                weekdays.map((day, index) => (
                  <span className={index > 4 ? 'cal-weekend-text' : ''} key={day}>
                    {tx(day)}
                  </span>
                )),
              )}
            </div>
            <div className="cal-month-grid" role="group" aria-label={monthLabel(month)}>
              {calendarDays(month).map((day) => {
                const key = dateKey(day);
                const isCurrentMonth = day.getMonth() === month.getMonth();
                const events = activeLeaves.filter(
                  (request) => request.start_date! <= key && request.end_date! >= key,
                );
                const weekend = day.getDay() === 0 || day.getDay() === 6;
                const approved = events.some((request) => request.status === 'approved');
                const pending = events.some((request) => request.status === 'pending');
                return (
                  <button
                    key={key}
                    data-day={key}
                    onFocus={() => setFocusedDay(key)}
                    onKeyDown={(event) => handleDayKey(event, key)}
                    className={`cal-day ${!isCurrentMonth ? 'outside' : ''} ${weekend ? 'weekend' : ''} ${approved ? 'has-approved' : pending ? 'has-pending' : ''} ${key === selected ? 'selected' : ''} ${key === today ? 'today' : ''}`}
                    onClick={() => {
                      setSelected(key);
                      if (!isCurrentMonth) setMonth(monthStart(day));
                    }}
                    aria-label={`${formatDay(key, true)}, ${events.length ? `${events.length} заявок на отпуск` : 'нет заявок на отпуск'}`}
                    aria-pressed={key === selected}
                  >
                    <span className="cal-day-top">
                      <span>{tx(day.getDate())}</span>
                      {tx(events.length > 0 && <Icon name="calendar" size={13} />)}
                    </span>
                    <div className="cal-day-events">
                      {events.slice(0, 2).map((request) => (
                        <span key={request.id} className={`cal-event cal-event-${request.status}`}>
                          <i />
                          {scope === 'team'
                            ? people
                                .get(request.employee_id)
                                ?.full_name.split(' ')
                                .slice(0, 2)
                                .join(' ') || 'Отпуск'
                            : 'Отпуск'}
                        </span>
                      ))}
                      {tx(
                        events.length > 2 && (
                          <span className="cal-event-more">
                            {t('Ещё ')}
                            {tx(events.length - 2)}
                          </span>
                        ),
                      )}
                    </div>
                    {tx(
                      events.length > 0 && scope === 'own' && (
                        <span className="cal-day-caption">
                          {tx(approved ? 'Согласовано' : 'На согласовании')}
                        </span>
                      ),
                    )}
                  </button>
                );
              })}
            </div>
          </section>
          <aside className="stack cal-sidebar">
            <section className="card cal-summary">
              <div className="cal-summary-title">
                <div>
                  <span className="req-eyebrow">{t('СВОДКА МЕСЯЦА')}</span>
                  <h2>{tx(monthLabel(month))}</h2>
                </div>
                <span className="req-type-icon">
                  <Icon name="calendar" size={20} />
                </span>
              </div>
              <div className="cal-summary-tiles">
                <div className="cal-summary-approved">
                  <span>{t('Согласованный отпуск')}</span>
                  <strong>
                    {tx(countMonthDays('approved'))} <small>{t('дн.')}</small>
                  </strong>
                </div>
                <div className="cal-summary-pending">
                  <span>{t('На согласовании')}</span>
                  <strong>
                    {tx(countMonthDays('pending'))} <small>{t('дн.')}</small>
                  </strong>
                </div>
                <div>
                  <span>{t('Заявок в месяце')}</span>
                  <strong>{tx(monthLeaves.length)}</strong>
                </div>
                <div>
                  <span>{t('Мой баланс отпуска')}</span>
                  <strong>
                    {tx(profile.vacation_days_remaining)} <small>{t('дн.')}</small>
                  </strong>
                </div>
              </div>
              {tx(
                scope === 'team' && (
                  <p className="req-field-help">
                    {t('Дни отсутствия суммируются по сотрудникам.')}
                  </p>
                ),
              )}
            </section>
            <section className="card cal-selected-day">
              <div className="cal-selected-heading">
                <Icon name="calendar" size={22} />
                <h2>{tx(formatDay(selected, true))}</h2>
              </div>
              {selectedEvents.length ? (
                <div className="cal-selected-events">
                  {selectedEvents.map((request) => (
                    <div key={request.id} className="cal-selected-event">
                      <StatusBadge status={request.status} />
                      <strong>
                        {scope === 'team'
                          ? people.get(request.employee_id)?.full_name || 'Сотрудник'
                          : 'Трудовой отпуск'}
                      </strong>
                      <span>
                        {tx(formatDay(request.start_date))} — {tx(formatDay(request.end_date))}
                      </span>
                      {request.comment && <p>{request.comment}</p>}
                      <Link className="btn btn-secondary" to={`/requests/${request.id}`}>
                        {t('Открыть ')}
                        {tx(requestNumber(request.id))}
                        <Icon name="arrow-right" size={15} />
                      </Link>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="cal-no-events">
                  <div className="cal-empty-icon">
                    <Icon name="calendar" size={24} />
                  </div>
                  <strong>{t('Отпуск не запланирован')}</strong>
                  <button
                    className="btn btn-secondary"
                    disabled={selected < today}
                    onClick={() => {
                      setRangeStart(selected);
                      setRangeEnd('');
                      setScope('own');
                      setParams({ select: '1' });
                    }}
                  >
                    {t('Начать отпуск с этой даты ')}
                    <Icon name="arrow-right" size={15} />
                  </button>
                </div>
              )}
            </section>
            <section className="card cal-upcoming">
              <span className="req-eyebrow">{t('БЛИЖАЙШИЕ ОТПУСКА')}</span>
              {upcoming.length ? (
                upcoming.map((request) => (
                  <Link key={request.id} to={`/requests/${request.id}`}>
                    <span
                      className={`req-type-icon ${request.status === 'pending' ? 'cal-upcoming-pending' : ''}`}
                    >
                      <Icon name="calendar" size={18} />
                    </span>
                    <span>
                      <strong>
                        {scope === 'team'
                          ? people.get(request.employee_id)?.full_name || 'Сотрудник'
                          : request.start_date! <= today
                            ? 'Текущий отпуск'
                            : 'Начало отпуска'}
                      </strong>
                      <small>
                        {tx(formatDay(request.start_date))} ·{' '}
                        {tx(dayCount(request.start_date!, request.end_date!))}
                        {t(' дн.')}
                      </small>
                    </span>
                    <Icon name="chevron-right" size={16} />
                  </Link>
                ))
              ) : (
                <p className="muted">{t('Ближайших отпусков пока нет.')}</p>
              )}
            </section>
          </aside>
        </div>
      )}
    </div>
  );
}

import { LeaveConflictNotice } from '@/features/leave-conflict';
