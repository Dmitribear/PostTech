import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { usePortal } from '@/entities/session';
import { requestNumber, requestLabel } from '@/entities/hr-request';
import type { EmployeeProfile, HrRequest } from '@/shared/api/contracts';
import { watchVisible } from '@/shared/lib/live-refresh';
import { t, tx } from '@/shared/lib/i18n';
import { ErrorState, Icon, LoadingState } from '@/shared/ui';

export function ApprovalInbox() {
  const { api, refreshKey } = usePortal();
  const [data, setData] = useState<{ requests: HrRequest[]; people: EmployeeProfile[] }>();
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  useEffect(
    () =>
      watchVisible(async (signal) => {
        try {
          const [requests, people] = await Promise.all([
            api.getRequests({ scope: 'review', status: 'pending', limit: 3 }),
            api.getTeam(),
          ]);
          if (!signal.aborted) {
            setData({ requests, people });
            setError(null);
          }
        } catch (reason) {
          if (!signal.aborted) setError(reason);
        }
      }),
    [api, refreshKey, retry],
  );
  return (
    <section className="card approval-inbox" aria-label={t('Согласования')}>
      <div className="section-heading">
        <h2>{t('Согласования')}</h2>
        <Link className="text-link" to="/requests?scope=review">
          {t('Все заявки')} <Icon name="arrow-right" size={15} />
        </Link>
      </div>
      {error ? (
        <ErrorState error={error} retry={() => setRetry((v) => v + 1)} />
      ) : !data ? (
        <LoadingState />
      ) : data.requests.length ? (
        <div>
          {data.requests.map((request) => (
            <Link className="approval-inbox-row" key={request.id} to={`/requests/${request.id}`}>
              <Icon name={request.request_type === 'leave' ? 'calendar' : 'wallet'} size={20} />
              <span>
                <strong>
                  {data.people.find((p) => p.id === request.employee_id)?.full_name ||
                    requestNumber(request.id)}
                </strong>
                <small>
                  {tx(requestLabel(request))} · {requestNumber(request.id)}
                </small>
              </span>
              <Icon name="chevron-right" size={18} />
            </Link>
          ))}
        </div>
      ) : (
        <p>{t('Нет заявок на согласование')}</p>
      )}
    </section>
  );
}
