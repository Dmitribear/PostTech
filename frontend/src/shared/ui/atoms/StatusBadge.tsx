import { tx } from '@/shared/lib/i18n';
export function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    pending: 'На согласовании',
    approved: 'Одобрено',
    rejected: 'Отклонено',
    cancelled: 'Отменено',
    not_started: 'Не начат',
    in_progress: 'В процессе',
    completed: 'Завершён',
  };
  return (
    <span className={`badge badge-${status}`}>
      <span className="badge-dot" />
      {tx(labels[status] || status)}
    </span>
  );
}
