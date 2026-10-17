import { usePortal } from '@/entities/session';
import type { CourseAssignment, CourseDetail } from '@/shared/api/contracts';
import { t } from '@/shared/lib/i18n';
import { ErrorState } from '@/shared/ui/index';
import { useState } from 'react';

export function LessonReader({
  course,
  onSave,
  render,
}: {
  course: CourseDetail;
  onSave: (a: CourseAssignment) => void;
  render: (text: string) => React.ReactNode;
}) {
  const { api } = usePortal();
  const lessons = course.lessons || [];
  const completed = course.assignment?.completed_lesson_ids || [];
  const [index, setIndex] = useState(() =>
    Math.max(
      0,
      lessons.findIndex((l) => !completed.includes(l.id)),
    ),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const lesson = lessons[index];
  async function finish() {
    if (!lesson || busy) return;
    setBusy(true);
    setError(null);
    try {
      const a = await api.workspace<CourseAssignment>(
        `/courses/${course.id}/lessons/${lesson.id}/complete`,
        'POST',
      );
      onSave(a);
      const next = lessons.findIndex((l) => !a.completed_lesson_ids?.includes(l.id));
      if (next >= 0) setIndex(next);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  if (!lesson) return null;
  return (
    <section className="lesson-reader">
      <label className="field">
        {t('Урок')} {index + 1} / {lessons.length}
        <select
          className="input"
          aria-label={t('Выбрать урок')}
          disabled={busy}
          value={index}
          onChange={(e) => setIndex(Number(e.target.value))}
        >
          {lessons.map((l, i) => (
            <option key={l.id} value={i}>
              {completed.includes(l.id) ? '✓ ' : ''}
              {i + 1}. {l.title}
            </option>
          ))}
        </select>
      </label>
      <h2>{lesson.title}</h2>
      {render(lesson.material_markdown)}
      {Boolean(error) && <ErrorState error={error} />}
      {course.assignment && (
        <button
          className="btn btn-primary"
          disabled={busy || completed.includes(lesson.id)}
          onClick={finish}
        >
          {t(
            busy
              ? 'Сохраняем…'
              : completed.includes(lesson.id)
                ? 'Урок завершён'
                : 'Завершить урок',
          )}
        </button>
      )}
      <p className="muted" aria-live="polite">
        {t('Пройдено уроков')}: {completed.length} / {lessons.length}
      </p>
    </section>
  );
}
