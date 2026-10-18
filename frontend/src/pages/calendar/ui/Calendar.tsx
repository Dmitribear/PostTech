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
  RequestState,
} from '@/entities/hr-request';
import { usePortal } from '@/entities/session';
import { CalendarExport } from '@/features/export-calendar';
import { watchVisible } from '@/shared/lib/live-refresh';
import { LeaveBalance } from '@/features/leave-balance';
import type { Course, EmployeeProfile } from '@/shared/api/contracts';
import { eventsForDay, scheduledLeaves, scheduledCourses } from '@/shared/lib/calendar-events';
import { homeCourses } from '@/shared/lib/home-learning';
import { localizedDate, t, tx } from '@/shared/lib/i18n';
import '@/shared/styles/requests.css';
import { ErrorState, Icon, LoadingState, PageHeader, StatusBadge } from '@/shared/ui/index';
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';

const weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
type CalendarCourse = Course & { eventId?: string; employee?: { id: string; full_name: string } };
const courseLink = (course: CalendarCourse) =>
  `/academy?course=${encodeURIComponent(course.id)}${course.employee ? `&tab=team&employee=${encodeURIComponent(course.employee.id)}` : ''}`;

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
  const [courses, setCourses] = useState<CalendarCourse[]>([]);
  const [team, setTeam] = useState<EmployeeProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reload, setReload] = useState(0);
  const [scope, setScope] = useState<'own' | 'team'>(() =>
    params.get('scope') === 'team' && profile.role !== 'worker' ? 'team' : 'own',
  );
  const [compact, setCompact] = useState(() => window.matchMedia('(max-width: 900px)').matches);
  useEffect(() => {
    const query = window.matchMedia('(max-width: 900px)');
    const update = () => setCompact(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  const [focusedDay, setFocusedDay] = useState(initial);
  const calendarRoot = useRef<HTMLElement>(null);
  const selectedDayRoot = useRef<HTMLElement>(null);
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
    let loaded = false;
    setLoading(true);
    setError(null);
    return watchVisible(async (signal) => {
      try {
        const [data, assignments] = await Promise.all([
          loadRequests(api, {
            request_type: 'leave',
            ...(isSelecting || scope === 'own'
              ? { scope: 'mine', employee_id: profile.id }
              : { scope: 'all' }),
          }),
          isSelecting
            ? Promise.resolve([])
            : scope === 'own'
              ? api.getMyCourses()
              : api.getTeamCourses(),
        ]);
        if (!signal.aborted) {
          setRecords(data);
          setCourses(
            scope === 'own'
              ? homeCourses(assignments)
              : assignments.flatMap((a) =>
                  a.course && 'employee' in a && a.employee_id !== profile.id
                    ? [
                        {
                          ...a.course,
                          assignment: a,
                          eventId: a.id,
                          employee: a.employee as CalendarCourse['employee'],
                        },
                      ]
                    : [],
                ),
          );
          setError(null);
          loaded = true;
        }
      } catch (reason) {
        if (!signal.aborted && !loaded) setError(reason);
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    });
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
      scheduledLeaves(records).filter(
        (request) => scope !== 'team' || request.employee_id !== profile.id,
      ),
    [records, scope, profile.id],
  );
  const people = useMemo(
    () => new Map([profile, ...team].map((person) => [person.id, person])),
    [profile, team],
  );
  const visibleCourses = courses;
  const { leaves: selectedEvents, courses: selectedCourses } = eventsForDay(
    selected,
    activeLeaves,
    visibleCourses,
  );
  const firstKey = dateKey(month);
  const lastKey = dateKey(new Date(month.getFullYear(), month.getMonth() + 1, 0, 12));
  const monthLeaves = activeLeaves.filter(
    (request) => request.start_date! <= lastKey && request.end_date! >= firstKey,
  );
  const monthCourses = scheduledCourses(visibleCourses).filter(
    (course) => course.assignment!.due_on! >= firstKey && course.assignment!.due_on! <= lastKey,
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

  function chooseDay(day: Date, showDetails = compact) {
    setSelected(dateKey(day));
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.set('date', dateKey(day));
        return next;
      },
      { replace: true },
    );
    if (day.getMonth() !== month.getMonth() || day.getFullYear() !== month.getFullYear())
      setMonth(monthStart(day));
    if (showDetails)
      requestAnimationFrame(() =>
        selectedDayRoot.current?.scrollIntoView({
          block: 'start',
          behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
            ? 'instant'
            : 'smooth',
        }),
      );
  }

  function changeScope(value: 'own' | 'team') {
    setScope(value);
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.set('scope', value);
        next.set('date', selected);
        return next;
      },
      { replace: true },
    );
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
          <>
            <CalendarExport
              start={dateKey(monthStart(month))}
              end={dateKey(new Date(month.getFullYear(), month.getMonth() + 1, 0, 12))}
              scope={scope === 'own' ? 'mine' : 'team'}
              month={monthLabel(month)}
            />
            <button className="btn btn-primary" onClick={startPlanning}>
              <Icon name="plus" size={18} />
              {t(' Оформить отпуск')}
            </button>
          </>
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
              <button
                className={scope === 'own' ? 'active' : ''}
                onClick={() => changeScope('own')}
              >
                {t('Мой календарь')}
              </button>
              <button
                className={scope === 'team' ? 'active' : ''}
                onClick={() => changeScope('team')}
              >
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
            {t('Ждёт решения')}
          </span>
          {
            <span>
              <i className="cal-dot cal-dot-course" />
              {t('Срок курса')}
            </span>
          }
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
                {tx(scope === 'own' ? 'Мои планы' : 'Планы команды')}
              </span>
              <span>
                {t('Отпуск')}: {monthLeaves.length}
                {
                  <>
                    {' '}
                    · {t('Сроки курсов')}: {monthCourses.length}
                  </>
                }
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
                const events = eventsForDay(key, activeLeaves, visibleCourses);
                const weekend = day.getDay() === 0 || day.getDay() === 6;
                const approved = events.leaves.some((request) => request.status === 'approved');
                const pending = events.leaves.some((request) => request.status === 'pending');
                const total = events.leaves.length + events.courses.length;
                const preview = [
                  ...events.leaves.slice(0, events.courses.length ? 1 : 2).map((request) => ({
                    id: `leave-${request.id}`,
                    kind: request.status,
                    title:
                      scope === 'team'
                        ? people.get(request.employee_id)?.full_name || t('Отпуск')
                        : t('Отпуск'),
                    href: `/requests/${request.id}`,
                    label: `${t('Открыть заявку')}: ${formatDay(request.start_date)} — ${formatDay(request.end_date)}`,
                  })),
                  ...events.courses.slice(0, events.leaves.length ? 1 : 2).map((course) => ({
                    id: `course-${course.eventId || course.id}`,
                    kind: 'course',
                    title: course.employee
                      ? `${course.employee.full_name} · ${tx(course.title)}`
                      : tx(course.title),
                    href: courseLink(course),
                    label: `${t('Открыть курс')}: ${course.employee?.full_name || ''} ${tx(course.title)}`,
                  })),
                ];
                return (
                  <div
                    key={key}
                    data-day={key}
                    className={`cal-day ${!isCurrentMonth ? 'outside' : ''} ${weekend ? 'weekend' : ''} ${approved ? 'has-approved' : pending ? 'has-pending' : ''} ${events.courses.length ? 'has-course' : ''} ${key === selected ? 'selected' : ''} ${key === today ? 'today' : ''}`}
                  >
                    <button
                      type="button"
                      className="cal-day-select"
                      data-day={key}
                      onFocus={() => setFocusedDay(key)}
                      onKeyDown={(event) => handleDayKey(event, key)}
                      onClick={() => chooseDay(day)}
                      aria-label={`${formatDay(key, true)}, ${t('Отпуск')}: ${events.leaves.length}, ${t('Сроки курсов')}: ${events.courses.length}`}
                      aria-pressed={key === selected}
                    />
                    <span className="cal-day-top" aria-hidden="true">
                      <span>{day.getDate()}</span>
                      {total > 0 && (
                        <Icon name={events.leaves.length ? 'calendar' : 'graduation'} size={13} />
                      )}
                    </span>
                    <div className="cal-day-events">
                      {preview.map((event) =>
                        compact ? (
                          <span
                            key={event.id}
                            className={`cal-event cal-event-${event.kind}`}
                            aria-hidden="true"
                          />
                        ) : (
                          <Link
                            key={event.id}
                            className={`cal-event cal-event-${event.kind}`}
                            to={event.href}
                            aria-label={event.label}
                            title={event.title}
                          >
                            <i aria-hidden="true" />
                            {event.title}
                          </Link>
                        ),
                      )}
                      {total > preview.length &&
                        (compact ? (
                          <span className="cal-event-more" aria-hidden="true">
                            +{total - preview.length}
                          </span>
                        ) : (
                          <button
                            className="cal-event-more cal-more-button"
                            type="button"
                            onClick={() => chooseDay(day, true)}
                          >
                            {t('Ещё ')}
                            {total - preview.length}
                          </button>
                        ))}
                    </div>
                    {events.leaves.length > 0 && scope === 'own' && (
                      <span className="cal-day-caption" aria-hidden="true">
                        {t(approved ? 'Согласовано' : 'Ждёт решения')}
                      </span>
                    )}
                  </div>
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
                  <span>{t('Ждёт решения')}</span>
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
                  <LeaveBalance compact />
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
            <section
              className="card cal-selected-day"
              ref={selectedDayRoot}
              aria-label={t('События дня')}
            >
              <div className="cal-selected-heading">
                <Icon name="calendar" size={22} />
                <h2>{tx(formatDay(selected, true))}</h2>
              </div>
              {selectedEvents.length || selectedCourses.length ? (
                <div className="cal-selected-events" aria-live="polite">
                  {selectedEvents.map((request) => (
                    <div key={request.id} className="cal-selected-event">
                      <RequestState request={request} />
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
                  {selectedCourses.map((course) => (
                    <div
                      key={course.eventId || course.id}
                      className="cal-selected-event cal-selected-course"
                    >
                      {course.employee && <strong>{course.employee.full_name}</strong>}
                      <StatusBadge status={course.assignment!.status} />
                      <strong>{tx(course.title)}</strong>
                      {course.employee && (
                        <span>
                          {course.assignment!.progress_percent}% ·{' '}
                          {course.provider || t('Обучение')}
                        </span>
                      )}
                      <span className={selected < today ? 'cal-overdue' : undefined}>
                        {t(selected < today ? 'Срок истёк' : 'Срок курса')}: {formatDay(selected)}
                      </span>
                      <Link className="btn btn-secondary" to={courseLink(course)}>
                        {t('Открыть курс')}
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
                  <strong>{t('На этот день ничего не запланировано')}</strong>
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
