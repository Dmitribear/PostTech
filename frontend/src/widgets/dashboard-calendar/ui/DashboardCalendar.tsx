import { businessDate, dateKey, parseDay } from '@/entities/hr-request';
import { localizedDate, t } from '@/shared/lib/i18n';
import { Icon } from '@/shared/ui';
import { useState } from 'react';
import { Link } from 'react-router-dom';

export function DashboardCalendar() {
  const today = businessDate();
  const [month, setMonth] = useState(() => {
    const date = parseDay(today);
    return new Date(date.getFullYear(), date.getMonth(), 1, 12);
  });
  const offset = (month.getDay() + 6) % 7;
  const count = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const cells = Math.ceil((offset + count) / 7) * 7;
  const title = localizedDate(month, { month: 'long', year: 'numeric' }).replace(' г.', '');

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
          return (
            <Link
              key={key}
              to={`/calendar?date=${key}`}
              className={`desk-calendar-day${outside ? ' outside' : ''}${index % 7 > 4 ? ' weekend' : ''}`}
              aria-current={key === today ? 'date' : undefined}
              aria-label={localizedDate(day, { day: 'numeric', month: 'long', year: 'numeric' })}
            >
              <span>{day.getDate()}</span>
            </Link>
          );
        })}
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
    </section>
  );
}
