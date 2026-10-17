import type { HrRequest } from '@/shared/api/contracts';
import { t } from '@/shared/lib/i18n';
import '@/shared/styles/hr-workflows.css';
import { StatusBadge } from '@/shared/ui/index';

export function RequestState({ request }: { request: HrRequest }) {
  if (request.status !== 'approved') return <StatusBadge status={request.status} />;
  return (
    <span className="hf-label">
      {t(
        request.fulfillment?.status === 'completed'
          ? 'Оформлено'
          : request.fulfillment?.status === 'processing'
            ? 'Оформляет HR'
            : request.fulfillment
              ? 'Ожидает HR'
              : 'Согласовано',
      )}
    </span>
  );
}
