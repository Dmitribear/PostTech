import { usePortal } from '@/entities/session';
import { formatDate } from '@/shared/lib/format';
import { t } from '@/shared/lib/i18n';
import { ErrorState } from '@/shared/ui';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
export type MyTrack = {
  id: string;
  completed_at: string | null;
  learning_tracks: { title: string };
  steps: {
    position: number;
    course_id: string;
    days_to_complete: number;
    courses: { title: string };
    assignment: {
      status: string;
      progress_percent: number;
      due_on: string | null;
    } | null;
  }[];
};
export function MyTracks({ employeeId }: { employeeId?: string }) {
  const { api, refreshKey } = usePortal();
  const [rows, setRows] = useState<MyTrack[]>([]),
    [error, setError] = useState<unknown>(null),
    [retry, setRetry] = useState(0);
  useEffect(() => {
    if (api.mode === 'demo') return;
    let active = true;
    api
      .workspace<MyTrack[]>(`/my-tracks${employeeId ? '?employee_id=' + employeeId : ''}`)
      .then((v) => {
        if (active) {
          setRows(v);
          setError(null);
        }
      })
      .catch((e) => {
        if (active) setError(e);
      });
    return () => {
      active = false;
    };
  }, [api, employeeId, refreshKey, retry]);
  if (api.mode === 'demo') return null;
  return (
    <div className="hf-stack">
      {Boolean(error) && <ErrorState error={error} retry={() => setRetry((v) => v + 1)} />}{' '}
      {rows.map((row) => {
        const done = row.steps.filter((s) => s.assignment?.status === 'completed').length;
        const next = row.steps.find((s) => s.assignment?.status !== 'completed');
        return (
          <section className="card hf-card" key={row.id}>
            <div className="hf-row">
              <h2>{row.learning_tracks.title}</h2>
              <span>
                {done} / {row.steps.length}
              </span>
            </div>
            {next ? (
              <p>
                {t('Следующий шаг')}: <strong>{next.courses.title}</strong>
                {next.assignment?.due_on && ` · ${t('до')} ${formatDate(next.assignment.due_on)}`}
              </p>
            ) : (
              <p>{t('План адаптации завершён')}</p>
            )}
            {next?.assignment && !employeeId && (
              <Link className="btn btn-secondary" to={`/academy?course=${next.course_id}`}>
                {t('Продолжить адаптацию')}
              </Link>
            )}
            <details>
              <summary>{t('Все шаги')}</summary>
              <ol className="hf-track-steps">
                {row.steps.map((s) => (
                  <li key={s.position}>
                    <span>{s.courses.title}</span>
                    <small>
                      {t(
                        s.assignment?.status === 'completed'
                          ? 'Пройден'
                          : s === next
                            ? 'Текущий шаг'
                            : 'Далее по плану',
                      )}{' '}
                      · {s.days_to_complete} {t('дн. после открытия')}
                    </small>
                  </li>
                ))}
              </ol>
            </details>
          </section>
        );
      })}
    </div>
  );
}
