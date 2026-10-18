import { usePortal } from '@/entities/session';
import { LeaveBalance } from '@/features/leave-balance';
import type { Course, HrRequest, Notification } from '@/shared/api/contracts';
import { notificationHref } from '@/shared/lib/format';
import { homeCourses, nextCourse } from '@/shared/lib/home-learning';
import { watchVisible } from '@/shared/lib/live-refresh';
import { getLocale, localizedDate, t, tx } from '@/shared/lib/i18n';
import '@/shared/styles/dashboard.css';
import { EmptyState, ErrorState, Icon, LoadingState, PageHeader } from '@/shared/ui/index';
import { RequestState } from '@/widgets/hr-workflow';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

const date = (value: string | null, short = false) =>
  value
    ? localizedDate(new Date(value.includes('T') ? value : `${value}T12:00:00`), {
        day: 'numeric',
        month: short ? 'short' : 'long',
        ...(value.includes('T') ? { timeZone: 'Asia/Qyzylorda' } : {}),
      })
    : '—';
const currency = (value: number | null) =>
  new Intl.NumberFormat(getLocale() === 'kk' ? 'kk-KZ' : 'ru-RU', {
    style: 'currency',
    currency: 'KZT',
    maximumFractionDigits: 2,
  }).format(value || 0);
const actions = [
  {
    path: '/calendar?select=1',
    icon: 'calendar',
    title: 'Оформить отпуск',
    text: 'Выбрать даты',
    category: 'Заявки',
    main: true,
  },
  {
    path: '/requests/new?type=advance',
    icon: 'wallet',
    title: 'Запросить аванс',
    text: 'Заявка на выплату',
    category: 'Заявки',
  },
  {
    path: '/calendar',
    icon: 'calendar',
    title: 'Календарь',
    text: 'Отпуска и планы',
    category: 'Планирование',
  },
  {
    path: '/jana',
    icon: 'message',
    title: 'AI Jana',
    text: 'Ответы на HR-вопросы',
    category: 'Поддержка',
  },
  {
    path: '/profile',
    icon: 'user',
    title: 'Мой профиль',
    text: 'Рабочие данные',
    category: 'Профиль',
  },
  {
    path: '/academy',
    icon: 'graduation',
    title: 'Обучение',
    text: 'Материалы и тесты',
    category: 'Обучение',
  },
];
export default function Dashboard() {
  const { api, profile, refreshKey } = usePortal();
  const [data, setData] = useState<{
    requests: HrRequest[];
    courses: Course[];
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let loaded = false;
    setError(null);
    return watchVisible(async (signal) => {
      try {
        const [requests, courses] = await Promise.all([
          api.getRequests({ employee_id: profile.id, limit: 3 }),
          api.getMyCourses(),
        ]);
        if (!signal.aborted) {
          setData({ requests, courses: homeCourses(courses) });
          setError(null);
          loaded = true;
        }
      } catch (e) {
        if (!signal.aborted && !loaded) setError(e);
      }
    });
  }, [api, profile.id, refreshKey, retry]);
  const learning = nextCourse(data?.courses || []);
  return (
    <div className="simple-dashboard">
      <header className="desk-heading">
        <h1>{t('Мой кабинет')}</h1>
        <p>
          {localizedDate(new Date(), {
            day: 'numeric',
            month: 'long',
            timeZone: 'Asia/Qyzylorda',
          })}
        </p>
      </header>
      <section className="desk-leave" aria-label={t('Отпуск')}>
        <span className="action-icon">
          <Icon name="calendar" size={27} />
        </span>
        <div className="desk-leave-copy">
          <h2>{t('Отпуск')}</h2>
          <LeaveBalance compact />
        </div>
        <div className="desk-leave-actions">
          <Link to="/calendar?select=1" className="btn btn-primary">
            {t('Оформить отпуск')}
          </Link>
          <Link to="/requests/new?type=advance" className="btn btn-secondary">
            {t('Запросить аванс')}
          </Link>
        </div>
      </section>
      {error ? (
        <ErrorState error={error} retry={() => setRetry((v) => v + 1)} />
      ) : !data ? (
        <LoadingState />
      ) : (
        <div className="desk-grid">
          <section className="card desk-requests">
            <div className="section-heading">
              <h2>{t('Мои заявки')}</h2>
              <Link to="/requests" className="text-link">
                {t('Все заявки')}
                <Icon name="arrow-right" size={15} />
              </Link>
            </div>
            {data.requests.length ? (
              <>
                <div className="desk-request-head" aria-hidden="true">
                  <span>{t('Заявка')}</span>
                  <span>{t('Период / сумма')}</span>
                  <span>{t('Статус')}</span>
                  <span />
                </div>
                <div className="desk-request-list">
                  {data.requests.slice(0, 3).map((r) => (
                    <Link to={`/requests/${r.id}`} key={r.id} className="desk-request">
                      <span className="desk-request-name">
                        <Icon name={r.request_type === 'leave' ? 'calendar' : 'wallet'} size={23} />
                        <strong>{t(r.request_type === 'leave' ? 'Отпуск' : 'Аванс')}</strong>
                      </span>
                      <span className="desk-request-period">
                        {r.request_type === 'leave'
                          ? `${date(r.start_date, true)} — ${date(r.end_date, true)}`
                          : currency(r.amount)}
                      </span>
                      <RequestState request={r} />
                      <Icon name="chevron-right" size={16} />
                    </Link>
                  ))}
                </div>
              </>
            ) : (
              <div className="desk-empty">
                <p>{t('Пока нет заявок')}</p>
                <Link to="/requests/new" className="text-link">
                  {t('Создать заявку')}
                  <Icon name="plus" size={16} />
                </Link>
              </div>
            )}
          </section>
          <div className="desk-side">
            <section className="card desk-learning">
              <div className="section-heading">
                <h2>{t('Обучение')}</h2>
                <Link to="/academy" className="icon-btn" aria-label={t('Все курсы')}>
                  <Icon name="chevron-right" size={18} />
                </Link>
              </div>
              {learning ? (
                <>
                  <div className="desk-course">
                    <Icon name="file-text" size={26} />
                    <div>
                      <Link className="desk-course-title" to={`/academy?course=${learning.id}`}>
                        {tx(learning.title)}
                      </Link>
                      <div className="desk-course-meta">
                        <span>
                          {learning.assignment?.due_on && (
                            <>
                              {t('До')} {date(learning.assignment.due_on, true)} ·{' '}
                            </>
                          )}
                          {learning.duration_minutes} {t('мин')}
                        </span>
                        <span>{learning.assignment!.progress_percent}%</span>
                      </div>
                      <div
                        className="progress-track"
                        role="progressbar"
                        aria-label={t('Прогресс курса')}
                        aria-valuenow={learning.assignment!.progress_percent}
                        aria-valuemin={0}
                        aria-valuemax={100}
                      >
                        <span
                          style={{
                            width: `${learning.assignment!.progress_percent}%`,
                          }}
                        />
                      </div>
                    </div>
                  </div>
                  <Link className="btn btn-secondary" to={`/academy?course=${learning.id}`}>
                    {t(learning.assignment!.progress_percent ? 'Продолжить' : 'Начать курс')}
                  </Link>
                </>
              ) : (
                <div className="desk-empty">
                  <p>
                    {t(
                      data.courses.some((c) => c.assignment?.status === 'completed')
                        ? 'Все назначенные курсы пройдены'
                        : 'Нет назначенных курсов',
                    )}
                  </p>
                  <Link to="/academy" className="text-link">
                    {t('Все курсы')}
                    <Icon name="arrow-right" size={16} />
                  </Link>
                </div>
              )}
            </section>
            <Link to="/jana" className="card desk-help">
              <Icon name="message" size={25} />
              <div>
                <strong>{t('Есть вопрос?')}</strong>
                <p>
                  {t('Спросить Jana')}
                  <Icon name="arrow-right" size={15} />
                </p>
              </div>
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

export function Services() {
  const [query, setQuery] = useState('');
  const shown = actions.filter((a) =>
    `${a.title} ${a.text} ${a.category}`.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <>
      <PageHeader title={t('Сервисы')} description={t('Что нужно сделать?')} />
      <div className="service-toolbar">
        <div className="search-field">
          <Icon name="search" size={18} />
          <input
            className="input"
            aria-label={t('Найти сервис')}
            placeholder={t('Найти сервис…')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <span className="muted">
          {tx(shown.length)}
          {t(' сервисов')}
        </span>
      </div>
      <div className="services-grid">
        {shown.map((action) => (
          <Link key={action.path} className="card service-card" to={action.path}>
            <div className="section-heading">
              <span className="action-icon">
                <Icon name={action.icon} size={24} />
              </span>
              <span className="service-category">{tx(action.category)}</span>
            </div>
            <h2>{tx(action.title)}</h2>
            <p>{action.text}</p>
            <span className="text-link">
              {t('Перейти к сервису')}
              <Icon name="arrow-right" size={17} />
            </span>
          </Link>
        ))}
      </div>
      {tx(
        !shown.length && (
          <EmptyState
            title={t('Сервис не найден')}
            description={t('Попробуйте изменить запрос.')}
          />
        ),
      )}
      <div className="service-tip">
        <Icon name="bot" size={24} />
        <span>
          <strong>{t('Нужна помощь?')}</strong>
          <p>{t('Спросите у Jana.')}</p>
        </span>
        <Link to="/jana" className="btn btn-secondary">
          {t('Спросить Jana')}
          <Icon name="arrow-right" size={16} />
        </Link>
      </div>
    </>
  );
}

export function ActivityPage() {
  const { api, refreshKey } = usePortal();
  const [events, setEvents] = useState<Notification[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [filter, setFilter] = useState('all');
  const [retry, setRetry] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    setError(null);
    api
      .getNotifications({ limit: 50 })
      .then((result) => {
        if (active) {
          setEvents(result);
          setHasMore(result.length === 50);
        }
      })
      .catch((e) => {
        if (active) setError(e);
      });
    return () => {
      active = false;
    };
  }, [api, refreshKey, retry]);
  async function more() {
    setBusy(true);
    try {
      const result = await api.getNotifications({
        offset: events?.length || 0,
        limit: 50,
      });
      setEvents((old) => [...(old || []), ...result]);
      setHasMore(result.length === 50);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  const shown = events?.filter(
    (n) =>
      filter === 'all' ||
      (filter === 'requests'
        ? n.request_id
        : n.notification_type.includes('course') || n.notification_type.includes('training')),
  );
  return (
    <>
      <PageHeader
        title={t('История событий')}
        actions={
          <Link to="/notifications" className="btn btn-secondary">
            <Icon name="bell" size={17} />
            {t('Уведомления')}
          </Link>
        }
      />
      <div className="tabs">
        {tx(
          [
            ['all', 'Все события'],
            ['requests', 'Заявки и отпуска'],
            ['courses', 'Обучение'],
          ].map(([key, label]) => (
            <button
              className={filter === key ? 'active' : ''}
              onClick={() => setFilter(key)}
              key={key}
            >
              {tx(label)}
            </button>
          )),
        )}
      </div>
      {tx(error && <ErrorState error={error} retry={() => setRetry((v) => v + 1)} />)}
      {tx(
        !events && !error ? (
          <LoadingState />
        ) : shown?.length ? (
          <div className="activity-feed">
            {tx(
              shown.map((n) => (
                <article className="card activity-event" key={n.id}>
                  <span className="action-icon">
                    <Icon
                      name={
                        n.notification_type.includes('course') ||
                        n.notification_type.includes('training')
                          ? 'graduation'
                          : 'clipboard'
                      }
                    />
                  </span>
                  <div>
                    <span className="muted">
                      {tx(date(n.created_at))} ·{' '}
                      {tx(
                        new Date(n.created_at).toLocaleTimeString(
                          getLocale() === 'kk' ? 'kk-KZ' : 'ru-RU',
                          {
                            hour: '2-digit',
                            minute: '2-digit',
                            timeZone: 'Asia/Qyzylorda',
                          },
                        ),
                      )}
                    </span>
                    <h2>{tx(n.title)}</h2>
                    <p>{tx(n.body)}</p>
                    <Link className="text-link" to={notificationHref(n)}>
                      {tx(n.request_id ? 'Открыть заявку' : 'Открыть обучение')}
                      <Icon name="arrow-right" size={16} />
                    </Link>
                  </div>
                </article>
              )),
            )}
          </div>
        ) : (
          events && (
            <EmptyState
              title={t('Событий пока нет')}
              description={t('Здесь появится история вашей активности.')}
            />
          )
        ),
      )}
      {tx(
        hasMore && (
          <button className="btn btn-secondary load-more" disabled={busy} onClick={more}>
            {tx(busy ? 'Загружаем…' : 'Показать ещё')}
          </button>
        ),
      )}
    </>
  );
}
