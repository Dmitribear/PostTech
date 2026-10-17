import { usePortal } from '@/entities/session';
import { t } from '@/shared/lib/i18n';
import { ErrorState } from '@/shared/ui/index';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

export interface Balance {
  employee_id: string;
  official_days: number;
  pending_days: number;
  approved_unreconciled_days: number;
  available_days: number;
  request_days: number;
  holds: { request_id: string; days: number; state: string }[];
}

/** One source of truth for author and reviewer; no hidden subtraction from official data. */
export function LeaveBalance({
  days = 0,
  requestId,
  review = false,
  onAvailable,
  compact = false,
}: {
  days?: number;
  requestId?: string;
  review?: boolean;
  onAvailable?: (days: number | null) => void;
  compact?: boolean;
}) {
  const { api, profile, refreshKey } = usePortal();
  const [balance, setBalance] = useState<Balance | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let live = true;
    setError(null);
    setBalance(null);
    if (api.mode === 'demo') {
      setBalance({
        employee_id: profile.id,
        official_days: profile.vacation_days_remaining,
        pending_days: 0,
        approved_unreconciled_days: 0,
        available_days: profile.vacation_days_remaining,
        request_days: 0,
        holds: [],
      });
      return;
    }
    api
      .workspace<Balance>(`/leave-balance${requestId ? `?request_id=${requestId}` : ''}`)
      .then((b) => {
        if (live) setBalance(b);
      })
      .catch((e) => {
        if (live) setError(e);
      });
    return () => {
      live = false;
    };
  }, [api, profile.id, profile.vacation_days_remaining, requestId, refreshKey, retry]);
  useEffect(() => {
    onAvailable?.(balance?.available_days ?? null);
  }, [balance, onAvailable]);
  if (error)
    return compact ? (
      <p role="status">
        {t('Баланс недоступен')} ·{' '}
        <button className="text-link" onClick={() => setRetry((v) => v + 1)}>
          {t('Повторить')}
        </button>
      </p>
    ) : (
      <ErrorState error={error} retry={() => setRetry((v) => v + 1)} />
    );
  if (!balance) return <p role="status">{t('Проверяем баланс…')}</p>;
  if (compact)
    return (
      <p>
        {balance.available_days} {t('дн. доступно')}
      </p>
    );
  const after = balance.available_days - (requestId ? 0 : days);
  return (
    <section className="leave-balance" aria-label={t('Расчёт отпуска')}>
      <dl>
        <div>
          <dt>{t('Кадровый остаток')}</dt>
          <dd>
            {balance.official_days} {t('дн.')}
          </dd>
        </div>
        <div>
          <dt>{t('На согласовании')}</dt>
          <dd>
            {balance.pending_days} {t('дн.')}
          </dd>
        </div>
        <div>
          <dt>{t('Одобрено, до сверки')}</dt>
          <dd>
            {balance.approved_unreconciled_days} {t('дн.')}
          </dd>
        </div>
        <div className="leave-balance-total">
          <dt>{t('Доступно для новой заявки')}</dt>
          <dd>
            {balance.available_days} {t('дн.')}
          </dd>
        </div>
      </dl>
      {days > 0 && !requestId && (
        <p role="status" className={after < 0 ? 'req-validation' : ''}>
          {after < 0
            ? t('Недостаточно дней для выбранного периода')
            : `${t('После отправки останется')}: ${after} ${t('дн.')}`}
        </p>
      )}
      {review && (
        <p>
          {t('Доступно после согласования')}:{' '}
          <strong>
            {balance.available_days} {t('дн.')}
          </strong>
          <br />
          {t('Доступно при отказе')}:{' '}
          <strong>
            {balance.available_days + balance.request_days} {t('дн.')}
          </strong>
        </p>
      )}
      <details>
        <summary>{t('Как рассчитано')}</summary>
        <p>
          {t(
            'Календарные дни, включая выходные. Кадровый остаток не списывается автоматически. После сверки HR обновляет остаток и снимает учтённые резервы.',
          )}
        </p>
        {balance.holds.map((h) => (
          <Link key={h.request_id} to={`/requests/${h.request_id}`}>
            {t(h.state === 'pending' ? 'На согласовании' : 'Одобрено')} · {h.days} {t('дн.')} →
          </Link>
        ))}
      </details>
      {api.mode === 'demo' && <small>{t('Демонстрационный расчёт')}</small>}
    </section>
  );
}
