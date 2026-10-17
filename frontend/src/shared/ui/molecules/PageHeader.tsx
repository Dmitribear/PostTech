import { tx } from '@/shared/lib/i18n';
import { type ReactNode } from 'react';
export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  eyebrow?: string;
}) {
  return (
    <div className="page-header">
      <div>
        {tx(eyebrow && <div className="eyebrow">{tx(eyebrow)}</div>)}
        <h1 className="page-title">{tx(title)}</h1>
        {tx(description && <p className="page-description">{tx(description)}</p>)}
      </div>
      {tx(actions && <div className="page-actions">{tx(actions)}</div>)}
    </div>
  );
}
