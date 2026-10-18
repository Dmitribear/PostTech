import { tx } from '@/shared/lib/i18n';
export function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    pending: 'Ждёт решения',
    approved: 'Согласовано',
    rejected: 'Отклонено',
    cancelled: 'Отменено',
    not_started: 'Не начат',
    in_progress: 'В процессе',
    completed: 'Завершён',
  };
  return <span className={`badge badge-${status}`}>{tx(labels[status] || status)}</span>;
}
