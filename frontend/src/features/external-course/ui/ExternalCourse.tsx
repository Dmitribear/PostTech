import { usePortal } from '@/entities/session';
import { errorMessage } from '@/shared/api/api';
import type { CourseAssignment, CourseDetail } from '@/shared/api/contracts';
import { t } from '@/shared/lib/i18n';
import { useEffect, useState } from 'react';

export function ExternalCourse({
  course,
  readOnly,
  onSave,
}: {
  course: CourseDetail;
  readOnly?: boolean;
  onSave: (assignment: CourseAssignment) => void;
}) {
  const { api, notify } = usePortal();
  const assignment = course.assignment;
  const [percent, setPercent] = useState(assignment?.progress_percent ?? 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    setPercent(assignment?.progress_percent ?? 0);
  }, [assignment?.progress_percent]);
  async function save() {
    if (busy || readOnly) return;
    setBusy(true);
    setError('');
    try {
      const result = assignment
        ? await api.updateCourseProgress(course.id, percent)
        : await api.enrollExternalCourse(course.id);
      onSave(result);
      notify(t(assignment ? 'Прогресс сохранён' : 'Курс добавлен в моё обучение'));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }
  const safeUrl = course.external_url?.startsWith('https://') ? course.external_url : undefined;
  return (
    <section className="external-course">
      <span className="muted">{course.provider}</span>
      <p>{course.description}</p>
      {safeUrl && (
        <a className="btn btn-primary" href={safeUrl} target="_blank" rel="noopener noreferrer">
          {t('Открыть на площадке')}
        </a>
      )}
      <p className="muted">
        {t('Обучение проходит на внешней площадке. Прогресс в PostTech отмечает сотрудник.')}
      </p>
      {assignment && (
        <>
          <div className="support-progress-label">
            <strong>{assignment.progress_percent}%</strong>
            <span>{t('Отмечено сотрудником')}</span>
          </div>
          <div
            className="support-progress"
            role="progressbar"
            aria-label={t('Прогресс курса')}
            aria-valuenow={assignment.progress_percent}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <span style={{ width: `${assignment.progress_percent}%` }} />
          </div>
        </>
      )}
      {!readOnly && assignment?.status !== 'completed' && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
          className="external-progress-form"
        >
          {assignment && (
            <>
              <label className="field">
                {t('Пройдено, %')}
                <input
                  className="input"
                  type="number"
                  min={assignment.progress_percent}
                  max={100}
                  step={1}
                  required
                  disabled={busy}
                  value={percent}
                  onChange={(e) => {
                    setPercent(e.target.valueAsNumber);
                    setConfirmed(false);
                  }}
                />
              </label>
              {percent === 100 && (
                <label className="external-completion">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                    required
                    disabled={busy}
                  />
                  <span>{t('Я завершил курс на площадке')}</span>
                </label>
              )}
            </>
          )}
          <button
            className="btn btn-secondary"
            disabled={
              busy ||
              (Boolean(assignment) &&
                (!Number.isInteger(percent) ||
                  percent <= assignment!.progress_percent ||
                  percent > 100 ||
                  (percent === 100 && !confirmed)))
            }
          >
            {t(busy ? 'Сохраняем…' : assignment ? 'Сохранить прогресс' : 'Добавить в моё обучение')}
          </button>
        </form>
      )}
      {error && (
        <p role="alert" className="field-error">
          {error}
        </p>
      )}
    </section>
  );
}
