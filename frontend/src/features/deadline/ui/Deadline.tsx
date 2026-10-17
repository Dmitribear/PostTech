import { usePortal } from '@/entities/session';
import { errorMessage } from '@/shared/api/api';
import { businessToday } from '@/shared/lib/business-date';
import { formatDate } from '@/shared/lib/format';
import { t, tx } from '@/shared/lib/i18n';
import { useState } from 'react';

export function Deadline({
  id,
  due,
  status,
  editable = false,
}: {
  id?: string;
  due?: string | null;
  status: string;
  editable?: boolean;
}) {
  const { api, refresh } = usePortal();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(due || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const overdue = !!due && due < businessToday() && status !== 'completed';
  async function save() {
    if (busy || !id) return;
    setBusy(true);
    setError('');
    try {
      await api.workspace(`/assignments/${id}/deadline`, 'PATCH', {
        due_on: value || null,
      });
      setOpen(false);
      refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="ws-deadline">
      <small className={overdue ? 'ws-overdue' : ''}>
        {tx(
          due ? (
            <>
              {tx(overdue ? 'Просрочено · ' : 'Пройти до ')}
              {tx(formatDate(due))}
            </>
          ) : (
            'Без срока'
          ),
        )}
      </small>
      {tx(
        editable &&
          status !== 'completed' &&
          (open ? (
            <>
              <input
                className="input"
                aria-label={t('Срок обучения')}
                type="date"
                value={value}
                min={businessToday()}
                onChange={(e) => setValue(e.target.value)}
                disabled={busy}
              />
              <button className="btn btn-secondary" disabled={busy} onClick={save}>
                {t('Сохранить')}
              </button>
              <button className="btn btn-ghost" disabled={busy} onClick={() => setOpen(false)}>
                {t('Отмена')}
              </button>
            </>
          ) : (
            <button
              className="btn btn-ghost"
              onClick={() => {
                setValue(due || '');
                setOpen(true);
              }}
            >
              {t('Срок')}
            </button>
          )),
      )}
      {tx(error && <span role="alert">{tx(error)}</span>)}
    </div>
  );
}
