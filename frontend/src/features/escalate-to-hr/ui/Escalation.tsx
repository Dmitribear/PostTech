import { usePortal } from '@/entities/session';
import { errorMessage } from '@/shared/api/api';
import { t, tx } from '@/shared/lib/i18n';
import '@/shared/styles/workspace.css';
import { ErrorState, Modal } from '@/shared/ui/index';
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
export interface Ticket {
  id: string;
  employee_id: string;
  question: string;
  context: string;
  status: 'open' | 'resolved';
  answer: string | null;
  created_at: string;
  answered_at: string | null;
}
export function Escalation({
  question,
  context,
  onClose,
}: {
  question: string;
  context: string;
  onClose: () => void;
}) {
  const { api, refresh } = usePortal();
  const [text, setText] = useState(question);
  const [details, setDetails] = useState(context.slice(0, 6000));
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [id] = useState(() => crypto.randomUUID());
  const [sent, setSent] = useState<Ticket | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      setSent(
        await api.workspace<Ticket>('/tickets', 'POST', {
          id,
          question: text,
          context: details,
          consent,
        }),
      );
      refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={sent ? 'Обращение отправлено' : 'Передать вопрос в HR'}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      {tx(
        sent ? (
          <div className="ws-stack">
            <p>
              {t(
                'HR получит только текст, который вы подтвердили. Ответ появится здесь и в уведомлениях.',
              )}
            </p>
            <Link className="btn btn-primary" to={`/support?ticket=${sent.id}`}>
              {t('Открыть обращение')}
            </Link>
          </div>
        ) : (
          <form className="ws-stack" onSubmit={submit}>
            <label className="field">
              {t('Ваш вопрос')}
              <textarea
                className="input"
                value={text}
                onChange={(e) => setText(e.target.value)}
                required
                minLength={3}
                maxLength={2000}
                rows={3}
                disabled={busy}
              />
            </label>
            <label className="field">
              {t('Контекст для HR')}
              <textarea
                className="input"
                value={details}
                onChange={(e) => setDetails(e.target.value)}
                maxLength={6000}
                rows={5}
                disabled={busy}
              />
            </label>
            <p className="muted">
              {t('Проверьте текст перед отправкой. Вся переписка не передаётся.')}
            </p>
            <label className="ws-check">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                disabled={busy}
              />
              {t('Разрешаю передать этот вопрос и контекст сотрудникам HR')}
            </label>
            {tx(Boolean(error) && <ErrorState error={error} />)}
            <button
              className="btn btn-primary"
              disabled={!consent || busy || text.trim().length < 3}
            >
              {tx(busy ? 'Отправляем…' : 'Отправить в HR')}
            </button>
          </form>
        ),
      )}
    </Modal>
  );
}
