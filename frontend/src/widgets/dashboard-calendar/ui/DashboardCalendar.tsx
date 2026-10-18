import { businessDate, dateKey, parseDay, formatDay, RequestState } from '@/entities/hr-request';
import type { Course, HrRequest } from '@/shared/api/contracts';
import { localizedDate, t, tx } from '@/shared/lib/i18n';
import { Icon, Modal, StatusBadge } from '@/shared/ui';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { eventsForDay } from '@/shared/lib/calendar-events';

export function DashboardCalendar({
  requests,
  courses,
}: {
  requests: HrRequest[];
  courses: Course[];
}) {
  const today = businessDate();
  const [selected, setSelected] = useState<string | null>(null);
  const [month, setMonth] = useState(() => {
    const date = parseDay(today);
    return new Date(date.getFullYear(), date.getMonth(), 1, 12);
  });
  const offset = (month.getDay() + 6) % 7;
  const count = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const cells = Math.ceil((offset + count) / 7) * 7;
  const title = localizedDate(month, { month: 'long', year: 'numeric' }).replace(' г.', '');
  const selectedEvents = selected ? eventsForDay(selected, requests, courses) : null;

  function move(delta: number) {
    setMonth((current) => new Date(current.getFullYear(), current.getMonth() + delta, 1, 12));
  }

  return (
    <section className="card desk-calendar" aria-label={t('Календарь на главной')}>
      <div className="desk-calendar-heading">
        <Link to={`/calendar?date=${dateKey(month)}`} className="desk-calendar-title">
          {title}
        </Link>
        <div className="desk-calendar-controls">
          <button className="icon-btn" aria-label={t('Предыдущий месяц')} onClick={() => move(-1)}>
            <Icon name="chevron-left" size={18} />
          </button>
          <button className="icon-btn" aria-label={t('Следующий месяц')} onClick={() => move(1)}>
            <Icon name="chevron-right" size={18} />
          </button>
        </div>
      </div>
      <div className="desk-calendar-weekdays" aria-hidden="true">
        {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((day) => (
          <span key={day}>{t(day)}</span>
        ))}
      </div>
      <div className="desk-calendar-days">
        {Array.from({ length: cells }, (_, index) => {
          const day = new Date(month.getFullYear(), month.getMonth(), index - offset + 1, 12);
          const key = dateKey(day);
          const outside = day.getMonth() !== month.getMonth();
          const events = eventsForDay(key, requests, courses);
          const approved = events.leaves.some((leave) => leave.status === 'approved');
          const pending = events.leaves.some((leave) => leave.status === 'pending');
          const hasCourses = events.courses.length > 0;
          const description = [
            approved && t('Отпуск'),
            pending && t('Ждёт решения'),
            hasCourses && `${t('Сроки курсов')}: ${events.courses.length}`,
          ]
            .filter(Boolean)
            .join(', ');
          return (
            <button
              type="button"
              key={key}
              data-day={key}
              onClick={() => setSelected(key)}
              className={`desk-calendar-day${outside ? ' outside' : ''}${index % 7 > 4 ? ' weekend' : ''}${approved ? ' has-leave' : pending ? ' has-pending' : ''}${hasCourses ? ' has-course' : ''}`}
              aria-current={key === today ? 'date' : undefined}
              aria-haspopup="dialog"
              aria-expanded={selected === key}
              aria-label={`${localizedDate(day, { day: 'numeric', month: 'long', year: 'numeric' })}${description ? `, ${description}` : ''}`}
            >
              <span className="desk-calendar-number">{day.getDate()}</span>
              <span className="desk-calendar-markers" aria-hidden="true">
                {approved && <i className="calendar-dot leave" />}
                {pending && <i className="calendar-dot pending" />}
                {hasCourses && <i className="calendar-dot course" />}
              </span>
            </button>
          );
        })}
      </div>
      <div className="desk-calendar-legend">
        <span>
          <i className="calendar-dot leave" aria-hidden="true" />
          {t('Отпуск')}
        </span>
        <span>
          <i className="calendar-dot pending" aria-hidden="true" />
          {t('Ждёт решения')}
        </span>
        <span>
          <i className="calendar-dot course" aria-hidden="true" />
          {t('Срок курса')}
        </span>
      </div>
      <button
        className="desk-calendar-today text-link"
        onClick={() => {
          const day = parseDay(today);
          setMonth(new Date(day.getFullYear(), day.getMonth(), 1, 12));
        }}
      >
        {t('Сегодня')}
      </button>
      {selected && selectedEvents && (
        <Modal title={formatDay(selected, true)} onClose={() => setSelected(null)}>
          <div className="desk-day-events" aria-live="polite" aria-atomic="true">
            {selectedEvents.leaves.map((leave) => (
              <article className="desk-day-event" key={leave.id}>
                <Icon name="calendar" size={20} />
                <div>
                  <h3>{t('Отпуск')}</h3>
                  <p>
                    {formatDay(leave.start_date)} — {formatDay(leave.end_date)}
                  </p>
                  <RequestState request={leave} />
                  <Link to={`/requests/${leave.id}`} className="text-link">
                    {t('Открыть заявку')}
                    <Icon name="arrow-right" size={15} />
                  </Link>
                </div>
              </article>
            ))}
            {selectedEvents.courses.map((course) => (
              <article className="desk-day-event" key={course.id}>
                <Icon name="graduation" size={20} />
                <div>
                  <h3>{tx(course.title)}</h3>
                  <p className={selected < today ? 'desk-day-overdue' : undefined}>
                    {t(selected < today ? 'Срок истёк' : 'Срок курса')}: {formatDay(selected)}
                  </p>
                  <StatusBadge status={course.assignment!.status} />
                  <Link
                    to={`/academy?course=${encodeURIComponent(course.id)}`}
                    className="text-link"
                  >
                    {t('Открыть курс')}
                    <Icon name="arrow-right" size={15} />
                  </Link>
                </div>
              </article>
            ))}
            {!selectedEvents.leaves.length && !selectedEvents.courses.length && (
              <p className="muted">{t('На этот день ничего не запланировано')}</p>
            )}
          </div>
          <div className="desk-day-actions">
            <Link to={`/calendar?date=${selected}`} className="btn btn-secondary">
              {t('Открыть календарь')}
            </Link>
            {selected >= today && !selectedEvents.leaves.length && (
              <Link to={`/calendar?select=1&start=${selected}`} className="text-link">
                {t('Оформить отпуск с этой даты')}
              </Link>
            )}
          </div>
        </Modal>
      )}
    </section>
  );
}
