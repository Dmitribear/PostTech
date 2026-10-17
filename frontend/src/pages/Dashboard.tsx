import { t, tx, getLocale, localizedDate } from '../lib/i18n';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { usePortal } from '../context';
import { fetchAllRequests } from '../lib/api';
import { EmptyState, ErrorState, Icon, LoadingState, PageHeader, StatusBadge } from '../components/ui';
import { notificationHref } from '../lib/format';
import RoleOverview from './RoleOverview';
import { homeCourses, nextCourse } from '../lib/home-learning';
import type { Course, HrRequest, Notification } from '../lib/types';
import './dashboard.css';

const date = (value: string | null, short = false) => value ? localizedDate(new Date(value.includes('T') ? value : `${value}T12:00:00`), { day: 'numeric', month: short ? 'short' : 'long', ...(value.includes('T') ? { timeZone: 'Asia/Qyzylorda' } : {}) }) : '—';
const currency = (value: number | null) => new Intl.NumberFormat((getLocale() === 'kk' ? 'kk-KZ' : 'ru-RU'), { style: 'currency', currency: 'KZT', maximumFractionDigits: 2 }).format(value || 0);
const dayPlural = new Intl.PluralRules((getLocale() === 'kk' ? 'kk-KZ' : 'ru-RU'));
const dayUnit = (days: number) => { const form = dayPlural.select(days); return form === 'one' ? 'день' : form === 'few' || form === 'other' ? 'дня' : 'дней'; };
const localDay = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
const todayKey = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Qyzylorda', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
const actions = [
  { path: '/calendar?select=1', icon: 'calendar', title: 'Оформить отпуск', text: 'Выбрать даты', category: 'Заявки', main: true },
  { path: '/requests/new?type=advance', icon: 'wallet', title: 'Запросить аванс', text: 'Заявка на выплату', category: 'Заявки' },
  { path: '/calendar', icon: 'calendar', title: 'Календарь', text: 'Отпуска и планы', category: 'Планирование' },
  { path: '/jana', icon: 'message', title: 'AI Jana', text: 'Ответы на HR-вопросы', category: 'Поддержка' },
  { path: '/profile', icon: 'user', title: 'Мой профиль', text: 'Рабочие данные', category: 'Профиль' },
  { path: '/academy', icon: 'graduation', title: 'Обучение', text: 'Материалы и тесты', category: 'Обучение' },
];
const quickActions = [
  { path: '/calendar?select=1', icon: 'calendar', title: 'Оформить отпуск', color: 'green' },
  { path: '/requests/new?type=advance', icon: 'wallet', title: 'Запросить аванс', color: 'blue' },
  { path: '/academy', icon: 'graduation', title: 'Обучение', color: 'purple' },
  { path: '/jana', icon: 'message', title: 'AI Jana', color: 'green' },
];

function LogisticsScene() {
  return <div className="home-brand-scene" aria-label={t("PostTech — движемся вперёд")}>
    <div><strong>{t("Двигаем")}<br />{t("бизнес дальше")}</strong></div>
    <svg viewBox="0 0 500 160" role="presentation" aria-hidden="true">
      <defs><linearGradient id="home-sky" x2="1" y2="1"><stop stopColor="#e8f4ef" /><stop offset="1" stopColor="#dcebf0" /></linearGradient><linearGradient id="home-trailer" x2="0" y2="1"><stop stopColor="#fff" /><stop offset="1" stopColor="#dce8e6" /></linearGradient></defs>
      <path fill="url(#home-sky)" d="M0 0h500v160H0z" />
      <circle cx="394" cy="35" r="24" fill="#fff" opacity=".6" />
      <path d="M90 119 220 39 267 68 337 16 447 87 500 65v95H90Z" fill="#bfd6d9" />
      <path d="m220 39-25 34 28-10 13 7 8-13Zm117-23-32 42 35-15 18 10Z" fill="#f6faf8" />
      <path d="M130 143 265 77 320 99 399 57 500 113v47H130Z" fill="#8fb6ac" />
      <path d="M0 143Q93 119 198 136T500 125v35H0Z" fill="#c6ddc7" />
      <path d="m0 150 500-6v16H0Z" fill="#a2b4b0" />
      <path d="M229 158h46m31 0h47m33 0h46m31 0h37" stroke="#eff7f3" strokeWidth="2" />
      <g transform="translate(278 71)">
        <path d="M34 62h165v10H34z" fill="#2a4843" /><rect x="77" width="130" height="65" rx="3" fill="url(#home-trailer)" stroke="#abc4c2" />
        <path d="M27 22h46v47H12V45l15-23Z" fill="#f4faf7" stroke="#99b4b0" />
        <path d="M31 27h33v21H20v-3Z" fill="#466861" /><path d="M68 28h5v37h-5" fill="#e1ebe5" />
        <path d="M12 55h17v8H12z" fill="#e9c997" /><path d="M10 66h60v5H10z" fill="#22473a" />
        <circle cx="38" cy="72" r="11" fill="#294039" /><circle cx="38" cy="72" r="5" fill="#bfcfcb" />
        <circle cx="166" cy="72" r="11" fill="#294039" /><circle cx="166" cy="72" r="5" fill="#bfcfcb" />
        <circle cx="190" cy="72" r="11" fill="#294039" /><circle cx="190" cy="72" r="5" fill="#bfcfcb" />
        <path d="m93 23 9-5 9 5v10l-9 5-9-5Z" fill="#008c45" /><path d="m94 24 8 5 8-5m-8 5v9" stroke="white" strokeWidth="1.5" fill="none" />
        <text x="117" y="32" fill="#1e4c3b" fontSize="13" fontWeight="700" fontFamily="Arial, sans-serif">JANA POST</text>
      </g>
    </svg>
  </div>;
}

function PalmIllustration() {
  return <svg width="49" height="49" viewBox="0 0 50 50" fill="none" aria-hidden="true"><path d="M13 42h28M26 40c-2-8-1-17 4-24M29 17c-6-4-12-1-15 5 6-2 10-1 14 0M30 16c-1-7-7-10-12-8 6 1 8 5 9 9M30 17c5-7 11-6 15-2-6-1-10 2-13 6M31 19c7 0 11 5 11 11-4-5-7-7-12-7M19 42c1-5 3-8 7-9M35 41c-1-4-3-6-6-7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function MiniCalendar({ requests }: { requests: HrRequest[] }) {
  const today = todayKey();
  const [month, setMonth] = useState(() => new Date(`${today.slice(0, 7)}-01T12:00:00`));
  const firstOffset = (month.getDay() + 6) % 7;
  const daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const cellCount = Math.ceil((firstOffset + daysInMonth) / 7) * 7;
  const leave = requests.filter(r => r.request_type === 'leave' && r.status === 'approved' && r.start_date && r.end_date);
  const hasLeave = (key: string) => leave.some(r => r.start_date! <= key && r.end_date! >= key);
  return <section className="home-panel home-calendar" aria-label={t("Календарь отпусков")}>
    <div className="home-card-heading"><h2>{tx(localizedDate(month, { month: 'long', year: 'numeric' }).replace(' г.', ''))}</h2><div className="home-calendar-controls"><button className="icon-btn" aria-label={t("Предыдущий месяц")} onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1, 12))}><Icon name="chevron-left" size={16} /></button><button className="icon-btn" aria-label={t("Следующий месяц")} onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1, 12))}><Icon name="chevron-right" size={16} /></button></div></div>
    <div className="home-calendar-week" aria-hidden="true">{tx(['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map(d => <span key={d}>{tx(d)}</span>))}</div>
    <div className="home-calendar-days">{tx(Array.from({ length: cellCount }, (_, i) => {
      const day = new Date(month.getFullYear(), month.getMonth(), i - firstOffset + 1, 12);
      const key = localDay(day);
      const outside = day.getMonth() !== month.getMonth();
      const approved = hasLeave(key);
      const label = `${date(key)}, ${approved ? 'согласованный отпуск, ' : ''}${key === today ? 'сегодня' : 'открыть календарь'}`;
      return <Link key={key} to={`/calendar?date=${key}`} className={`home-calendar-day${outside ? ' outside' : ''}${approved ? ' on-leave' : ''}${key === today ? ' today' : ''}`} aria-label={label} aria-current={key === today ? 'date' : undefined}><span>{tx(day.getDate())}</span></Link>;
    }))}</div>
    <div className="home-calendar-footer"><span><i />{t("Мой отпуск")}</span><button onClick={() => setMonth(new Date(`${today.slice(0, 7)}-01T12:00:00`))}>{t("Сегодня")}</button><Link to="/calendar" aria-label={t("Открыть полный календарь")}><Icon name="arrow-right" size={16} /></Link></div>
  </section>;
}

export default function Dashboard() {
  const { api, profile, refreshKey } = usePortal();
  const [data, setData] = useState<{ requests: HrRequest[]; courses: Course[]; notifications: Notification[] } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setError(null);
    Promise.all([fetchAllRequests(api, { employee_id: profile.id }), api.getMyCourses(), api.getNotifications({ limit: 3 })])
      .then(([requests, courses, notifications]) => { if (active) setData({ requests, courses: homeCourses(courses), notifications }); })
      .catch(e => { if (active) setError(e); });
    return () => { active = false; };
  }, [api, profile.id, refreshKey, retry]);
  const firstName = profile.full_name.split('·').at(-1)!.trim().split(' ')[0];
  const pending = data?.requests.filter(r => r.status === 'pending') || [];
  const learning = nextCourse(data?.courses || []);
  const nextLeave = data?.requests.filter(r => r.request_type === 'leave' && r.status === 'approved' && r.end_date && r.end_date >= todayKey()).sort((a, b) => a.start_date!.localeCompare(b.start_date!))[0];
  return <div className="pt-dashboard">
    <header className="home-heading"><div><h1>{t("Добрый день, ")}{tx(firstName)}!</h1><p>{t("Хорошего рабочего дня.")}</p></div><LogisticsScene /></header>
    {tx(error ? <ErrorState error={error} retry={() => setRetry(v => v + 1)} /> : !data ? <LoadingState /> : <>
      <nav className="home-quick-actions" aria-label={t("Быстрые действия")}><Link className="home-quick-action green home-mobile-calendar" to="/calendar"><span className="home-action-icon"><Icon name="calendar" size={25} /></span><strong>{t("Календарь")}</strong><Icon name="chevron-right" size={18} /></Link>{tx(quickActions.map(action => <Link className={`home-quick-action ${action.color}${action.path === '/calendar?select=1' ? ' home-desktop-leave' : ''}`} key={action.path} to={action.path === '/academy' && learning ? `/academy?course=${learning.id}` : action.path}><span className="home-action-icon"><Icon name={action.icon} size={25} /></span><strong>{tx(action.path === '/academy' && learning ? (learning.assignment?.status === 'in_progress' ? 'Продолжить курс' : 'Начать курс') : action.title)}</strong><Icon name="chevron-right" size={18} /></Link>))}</nav>
      <div className="home-overview">
        <section className="home-panel home-balance"><div className="home-card-heading"><h2>{t("Доступно дней отпуска")}</h2></div><span className="home-palm"><PalmIllustration /></span><div className="home-balance-value">{tx(profile.vacation_days_remaining.toLocaleString((getLocale() === 'kk' ? 'kk-KZ' : 'ru-RU')))}<span>{tx(dayUnit(profile.vacation_days_remaining))}</span></div>{tx(nextLeave && <p><Icon name="calendar-check" size={15} /><span>{t("Ваш отпуск: ")}{tx(date(nextLeave.start_date, true))} — {tx(date(nextLeave.end_date, true))}</span></p>)}<Link to="/calendar?select=1" className="btn btn-secondary">{t("Оформить отпуск")}</Link></section>
        <section className="home-panel home-events"><div className="home-card-heading"><h2>{t("Последние события")}</h2><Link className="text-link" to="/notifications">{t("Все")}<Icon name="arrow-right" size={15} /></Link></div>{tx(data.notifications.length ? <div className="home-event-list">{tx(data.notifications.map(n => <Link className="home-event" to={notificationHref(n)} key={n.id}><span className={`home-event-icon ${n.course_id || n.notification_type.includes('course') || n.notification_type.includes('training') ? 'purple' : n.notification_type.includes('approved') ? 'green' : 'amber'}`}><Icon name={n.course_id || n.notification_type.includes('course') || n.notification_type.includes('training') ? 'graduation' : 'clipboard'} size={18} /></span><span className="home-event-title">{tx(n.title)}</span><time dateTime={n.created_at}>{tx(date(n.created_at, true))}</time>{tx(!n.read_at && <span className="home-event-dot" aria-label={t("Не прочитано")} />)}</Link>))}</div> : <div className="home-events-empty"><Icon name="bell" size={25} /><p>{t("Всё спокойно")}</p><span>{t("Новые события появятся здесь")}</span></div>)}</section>
        <MiniCalendar requests={data.requests} />
      </div>
      <RoleOverview />
      <div className="home-lower-grid"><section className="home-panel home-requests"><div className="home-card-heading"><h2>{t("Мои заявки")}{tx(pending.length > 0 && <span className="home-count" title={t("На согласовании")}>{tx(pending.length)}</span>)}</h2><Link className="text-link" to="/requests">{t("Все заявки")}<Icon name="arrow-right" size={15} /></Link></div>{tx(data.requests.length ? <div className="home-request-list">{tx(data.requests.slice(0, 3).map(r => <Link className="home-request" to={`/requests/${r.id}`} key={r.id}><span className={`home-request-icon ${r.request_type === 'leave' ? 'green' : 'blue'}`}><Icon name={r.request_type === 'leave' ? 'calendar' : 'wallet'} size={21} /></span><span className="home-request-title"><strong>{tx(r.request_type === 'leave' ? 'Ежегодный отпуск' : 'Аванс')}</strong><small>{tx(r.request_type === 'leave' ? `${date(r.start_date, true)} — ${date(r.end_date, true)}` : currency(r.amount))}</small></span><StatusBadge status={r.status} /><Icon name="chevron-right" size={17} /></Link>))}</div> : <div className="home-request-empty"><span className="home-request-icon blue"><Icon name="file-text" size={23} /></span><div><strong>{t("Пока нет заявок")}</strong><p>{t("Отпуск или аванс — в пару шагов")}</p></div><Link to="/requests/new" className="text-link">{t("Создать")}<Icon name="plus" size={16} /></Link></div>)}</section>
      <section className="home-panel home-learning"><div className="home-card-heading"><h2>{t("Моё обучение")}</h2><span className="home-learning-icon"><Icon name="graduation" size={21} /></span></div>{tx(learning ? <><Link to={`/academy?course=${learning.id}`} className="home-learning-title">{tx(learning.title)}</Link><div className="home-learning-meta"><span>{tx(learning.duration_minutes)}{t(" мин")}</span><span>{tx(learning.assignment!.progress_percent)}{t("% пройдено")}</span></div><div className="home-learning-progress" role="progressbar" aria-label={`Прогресс курса ${learning.title}`} aria-valuenow={learning.assignment!.progress_percent} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${learning.assignment!.progress_percent}%` }} /></div><Link className="text-link" to={`/academy?course=${learning.id}`}>{tx(learning.assignment!.progress_percent ? 'Продолжить' : 'Начать курс')}<Icon name="arrow-right" size={16} /></Link></> : <><strong className="home-learning-title">{tx(data.courses.some(c => c.assignment?.status === 'completed') ? 'Все назначенные курсы пройдены' : 'Новые знания — новые возможности')}</strong><p className="home-learning-empty">{tx(data.courses.some(c => c.assignment?.status === 'completed') ? 'Отличная работа. Так держать!' : 'Ваши курсы и результаты — в Академии')}</p><Link className="text-link" to="/academy">{t("Открыть обучение")}<Icon name="arrow-right" size={16} /></Link></>)}</section></div>
    </>)}
  </div>;
}

export function Services() {
  const [query, setQuery] = useState('');
  const shown = actions.filter(a => `${a.title} ${a.text} ${a.category}`.toLowerCase().includes(query.toLowerCase()));
  return <><PageHeader title={t("Сервисы")} description={t("Что нужно сделать?")} /><div className="service-toolbar"><div className="search-field"><Icon name="search" size={18} /><input className="input" aria-label={t("Найти сервис")} placeholder={t("Найти сервис…")} value={query} onChange={e => setQuery(e.target.value)} /></div><span className="muted">{tx(shown.length)}{t(" сервисов")}</span></div><div className="services-grid">{shown.map(action => <Link key={action.path} className="card service-card" to={action.path}><div className="section-heading"><span className="action-icon"><Icon name={action.icon} size={24} /></span><span className="service-category">{tx(action.category)}</span></div><h2>{tx(action.title)}</h2><p>{action.text}</p><span className="text-link">{t("Перейти к сервису")}<Icon name="arrow-right" size={17} /></span></Link>)}</div>{tx(!shown.length && <EmptyState title={t("Сервис не найден")} description={t("Попробуйте изменить запрос.")} />)}<div className="service-tip"><Icon name="bot" size={24} /><span><strong>{t("Нужна помощь?")}</strong><p>{t("Спросите у Jana.")}</p></span><Link to="/jana" className="btn btn-secondary">{t("Спросить Jana")}<Icon name="arrow-right" size={16} /></Link></div></>;
}

export function ActivityPage() {
  const { api, refreshKey } = usePortal();
  const [events, setEvents] = useState<Notification[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [filter, setFilter] = useState('all');
  const [retry, setRetry] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { let active = true; setError(null); api.getNotifications({ limit: 50 }).then(result => { if (active) { setEvents(result); setHasMore(result.length === 50); } }).catch(e => { if (active) setError(e); }); return () => { active = false; }; }, [api, refreshKey, retry]);
  async function more() { setBusy(true); try { const result = await api.getNotifications({ offset: events?.length || 0, limit: 50 }); setEvents(old => [...old || [], ...result]); setHasMore(result.length === 50); } catch (e) { setError(e); } finally { setBusy(false); } }
  const shown = events?.filter(n => filter === 'all' || (filter === 'requests' ? n.request_id : (n.notification_type.includes('course') || n.notification_type.includes('training'))));
  return <><PageHeader title={t("История событий")} actions={<Link to="/notifications" className="btn btn-secondary"><Icon name="bell" size={17} />{t("Уведомления")}</Link>} /><div className="tabs">{tx([['all', 'Все события'], ['requests', 'Заявки и отпуска'], ['courses', 'Обучение']].map(([key, label]) => <button className={filter === key ? 'active' : ''} onClick={() => setFilter(key)} key={key}>{tx(label)}</button>))}</div>{tx(error && <ErrorState error={error} retry={() => setRetry(v => v + 1)} />)}{tx(!events && !error ? <LoadingState /> : shown?.length ? <div className="activity-feed">{tx(shown.map(n => <article className="card activity-event" key={n.id}><span className="action-icon"><Icon name={(n.notification_type.includes('course') || n.notification_type.includes('training')) ? 'graduation' : 'clipboard'} /></span><div><span className="muted">{tx(date(n.created_at))} · {tx(new Date(n.created_at).toLocaleTimeString((getLocale() === 'kk' ? 'kk-KZ' : 'ru-RU'), { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Qyzylorda' }))}</span><h2>{tx(n.title)}</h2><p>{tx(n.body)}</p><Link className="text-link" to={notificationHref(n)}>{tx(n.request_id ? 'Открыть заявку' : 'Открыть обучение')}<Icon name="arrow-right" size={16} /></Link></div></article>))}</div> : events && <EmptyState title={t("Событий пока нет")} description={t("Здесь появится история вашей активности.")} />)}{tx(hasMore && <button className="btn btn-secondary load-more" disabled={busy} onClick={more}>{tx(busy ? 'Загружаем…' : 'Показать ещё')}</button>)}</>;
}
