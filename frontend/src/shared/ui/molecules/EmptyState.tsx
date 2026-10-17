import { tx } from '@/shared/lib/i18n';
import { type ReactNode } from 'react';
import { Icon } from '../atoms/Icon';
export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <Icon name="clipboard" size={28} />
      </span>
      <h3>{tx(title)}</h3>
      {tx(description && <p>{tx(description)}</p>)}
      {tx(action)}
    </div>
  );
}
