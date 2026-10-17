import { approverNames, formatDay } from '@/entities/hr-request';
import type { HrRequest as RequestRecord } from '@/shared/api/contracts';
import { t, tx } from '@/shared/lib/i18n';
import '@/shared/styles/requests.css';
import { Icon } from '@/shared/ui/index';
import { RequestState } from '@/entities/hr-request';
import { Link } from 'react-router-dom';
export function LeaveConflictNotice({
  records,
  onChangeDates,
}: {
  records: RequestRecord[];
  onChangeDates: () => void;
}) {
  return (
    <section
      id="leave-conflict"
      tabIndex={-1}
      className="req-conflict"
      aria-label={t('Пересечение дат')}
    >
      <div className="req-conflict-heading" role="alert">
        <Icon name="info" size={20} />
        <div>
          <strong>{t('На эти даты уже есть заявка')}</strong>
          <p>{t('Выбранный период пересекается с отпуском ниже. Повторная заявка не нужна.')}</p>
        </div>
      </div>
      <ul className="req-conflict-list">
        {records.map((record) => (
          <li key={record.id}>
            <div className="req-conflict-status">
              <strong>{t('Отпуск')}</strong>
              <RequestState request={record} />
            </div>
            <p>
              {formatDay(record.start_date)} — {formatDay(record.end_date)}
            </p>
            {record.status === 'pending' && (
              <p className="req-conflict-reviewer">
                <span>{t('Согласует')}: </span>
                {tx(approverNames(record.approvers))}
              </p>
            )}
            <Link className="btn btn-secondary" to={`/requests/${record.id}`}>
              {t('Открыть заявку')}
              <Icon name="arrow-right" size={16} />
            </Link>
          </li>
        ))}
      </ul>
      <button type="button" className="btn btn-ghost" onClick={onChangeDates}>
        <Icon name="calendar" size={17} />
        {t('Выбрать другие даты')}
      </button>
    </section>
  );
}
