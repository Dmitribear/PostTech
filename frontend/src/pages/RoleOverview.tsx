import { t, tx } from '../lib/i18n';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { usePortal } from '../context';
import { Icon, ErrorState } from '../components/ui';
import { fetchAllRequests } from '../lib/api';
import { formatDate } from '../lib/format';
import type { HrRequest } from '../lib/types';

export default function RoleOverview() {
  const { api, profile, refreshKey } = usePortal();
  const [counts, setCounts] = useState<{ pending: number; learning: number; team: number } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  const [pending, setPending] = useState<HrRequest[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  useEffect(() => {
    if (profile.role === 'worker') return;
    let active = true; setError(null);
    Promise.all([fetchAllRequests(api, { scope: 'review', status: 'pending' }), api.getTeamCourses(), api.getTeam()])
      .then(([requests, learning, team]) => { if (active) {
        const reviewable = requests.filter(request => request.employee_id !== profile.id && request.status === 'pending' && request.can_review !== false);
        setCounts({ pending: reviewable.length, learning: learning.filter(a => a.status !== 'completed').length, team: team.length });
        setPending(reviewable.slice(0, 3));
        setNames(Object.fromEntries(team.map(person => [person.id, person.full_name])));
      } })
      .catch(e => { if (active) setError(e); });
    return () => { active = false; };
  }, [api, profile.role, refreshKey, retry]);
  if (profile.role === 'worker') return null;
  return <section className="home-role-queue" aria-label={t("Рабочая очередь")}>
    <div className="home-card-heading"><h2>{tx(profile.role === 'hr_admin' ? 'Работа HR' : 'Моя команда')}</h2><span>{tx(profile.role === 'hr_admin' ? 'Сотрудники компании' : 'Прямые подчинённые')}</span></div>
    {tx(error ? <ErrorState error={error} retry={() => setRetry(v => v + 1)} /> : <div className="home-role-links">
      <Link to="/requests?scope=review&status=pending"><span className="home-role-icon amber"><Icon name="check-circle" /></span><span><strong>{tx(counts?.pending ?? '…')}</strong><small>{t("На согласовании")}</small></span><Icon name="chevron-right" size={17} /></Link>
      <Link to="/academy?tab=team"><span className="home-role-icon purple"><Icon name="graduation" /></span><span><strong>{tx(counts?.learning ?? '…')}</strong><small>{t("Курсов в работе")}</small></span><Icon name="chevron-right" size={17} /></Link>
      <Link to="/team"><span className="home-role-icon blue"><Icon name="users" /></span><span><strong>{tx(counts?.team ?? '…')}</strong><small>{t("Сотрудников")}</small></span><Icon name="chevron-right" size={17} /></Link>
    </div>)}
    {!error && pending.length > 0 && <div className="home-review-shortcuts" aria-label={t('Заявки на согласование')}>
      {pending.map(request => <Link key={request.id} to={`/requests/${request.id}`}>
        <span className="home-role-icon amber"><Icon name={request.request_type === 'leave' ? 'calendar' : 'wallet'} size={19} /></span>
        <span><strong>{names[request.employee_id] || t('Заявка на согласование')}</strong><small>{t(request.request_type === 'leave' ? 'Отпуск' : 'Аванс')} · {request.request_type === 'leave' ? `${formatDate(request.start_date)} — ${formatDate(request.end_date)}` : `${request.amount?.toLocaleString('ru-RU')} ₸`}</small></span>
        <span className="text-link">{t('Рассмотреть')}<Icon name="chevron-right" size={16} /></span>
      </Link>)}
    </div>}
  </section>;
}
