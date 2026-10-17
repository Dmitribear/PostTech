import { usePortal } from '@/entities/session';
import { Deadline } from '@/features/deadline';
import { LessonReader } from '@/features/lesson-reader';
import { errorMessage } from '@/shared/api/api';
import type { Course, CourseAssignment, CourseAttempt, CourseDetail } from '@/shared/api/contracts';
import { formatDate } from '@/shared/lib/format';
import { getLocale, t, tx } from '@/shared/lib/i18n';
import '@/shared/styles/support.css';
import {
  EmptyState,
  ErrorState,
  Icon,
  LoadingState,
  Modal,
  PageHeader,
  StatusBadge,
} from '@/shared/ui/index';
import { MyTracks } from '@/widgets/hr-workflow';
import { TeamLearning } from '@/widgets/team-learning';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';

function Material({ content }: { content: string }) {
  return (
    <div className="support-material">
      {tx(
        content
          .replace(/\r/g, '')
          .split(/\n\s*\n/)
          .map((block) => block.trim())
          .filter(Boolean)
          .map((block, index) => {
            if (/^#{1,2} /.test(block))
              return <h2 key={index}>{tx(block.replace(/^#{1,2} /, ''))}</h2>;
            if (/^#{3,6} /.test(block))
              return <h3 key={index}>{tx(block.replace(/^#{3,6} /, ''))}</h3>;
            if (block.split('\n').every((line) => /^[-*] /.test(line)))
              return (
                <ul key={index}>
                  {tx(block.split('\n').map((line, i) => <li key={i}>{tx(line.slice(2))}</li>))}
                </ul>
              );
            return <p key={index}>{tx(block)}</p>;
          }),
      )}
    </div>
  );
}

function CourseReader({ id, onClose }: { id: string; onClose: () => void }) {
  const { api, profile, refresh, notify } = usePortal();
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  const [step, setStep] = useState<'material' | 'quiz' | 'result'>('material');
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [attempts, setAttempts] = useState<CourseAttempt[]>([]);
  const [attemptError, setAttemptError] = useState<unknown>(null);
  const pendingKeys = useRef(new Map<string, string>());
  const submitting = useRef(false);
  const storageKey = `posttech-quiz-pending:${api.mode}:${profile.id}:${id}`;
  function attemptKey() {
    const fingerprint = JSON.stringify(
      Object.entries(answers).sort(([a], [b]) => a.localeCompare(b)),
    );
    let persisted: Record<string, string> = {};
    try {
      persisted = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
    } catch {
      /* In-memory fallback. */
    }
    const candidate =
      persisted && typeof persisted === 'object' ? persisted[fingerprint] : undefined;
    const key =
      pendingKeys.current.get(fingerprint) ||
      (typeof candidate === 'string' && /^[\da-f-]{36}$/i.test(candidate)
        ? candidate
        : crypto.randomUUID());
    pendingKeys.current.set(fingerprint, key);
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({ ...persisted, [fingerprint]: key }));
    } catch {
      /* In-memory fallback. */
    }
    return { key, fingerprint };
  }
  function clearAttemptKey(fingerprint: string) {
    pendingKeys.current.delete(fingerprint);
    try {
      const persisted = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
      delete persisted[fingerprint];
      if (Object.keys(persisted).length)
        sessionStorage.setItem(storageKey, JSON.stringify(persisted));
      else sessionStorage.removeItem(storageKey);
    } catch {
      /* A saved result remains valid without browser storage. */
    }
  }
  async function refreshAttempts() {
    try {
      setAttempts(await api.getCourseAttempts(id));
      setAttemptError(null);
    } catch (err) {
      setAttemptError(err);
    }
  }
  useEffect(() => {
    let active = true;
    setCourse(null);
    setError(null);
    api
      .getCourse(id)
      .then(async (value) => {
        if (!active) return;
        setCourse(value);
        if (value.assignment) {
          try {
            const rows = await api.getCourseAttempts(id);
            if (active) setAttempts(rows);
          } catch (err) {
            if (active) setAttemptError(err);
          }
        }
      })
      .catch((err) => {
        if (active) setError(err);
      });
    return () => {
      active = false;
    };
  }, [api, id, retry]);
  const saveAssignment = (assignment: CourseAssignment) => {
    setCourse((previous) => (previous ? { ...previous, assignment } : previous));
    refresh();
  };
  async function beginQuiz() {
    if (!course || busy) return;
    setBusy(true);
    setActionError('');
    try {
      const updated = await api.updateCourseProgress(id, 90);
      saveAssignment(updated);
      setStep(updated.status === 'completed' ? 'result' : 'quiz');
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  async function finishQuiz(event: FormEvent) {
    event.preventDefault();
    if (!course || busy || submitting.current) return;
    if (course.quiz.some((question) => answers[question.id] === undefined)) {
      setActionError('Ответьте на каждый вопрос перед отправкой.');
      return;
    }
    submitting.current = true;
    setBusy(true);
    setActionError('');
    const submission = attemptKey();
    try {
      const updated = await api.completeCourse(id, answers, submission.key);
      saveAssignment(updated);
      clearAttemptKey(submission.fingerprint);
      setStep('result');
      notify(
        updated.status === 'completed'
          ? 'Курс завершён. Результат сохранён.'
          : 'Попытка сохранена. Тест можно повторить.',
      );
      await refreshAttempts();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
      submitting.current = false;
    }
  }
  return (
    <Modal
      title={course?.title || 'Учебный курс'}
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      {error ? (
        <ErrorState error={error} retry={() => setRetry((value) => value + 1)} />
      ) : !course ? (
        <LoadingState />
      ) : (
        <div className="support-course-reader">
          <div className="support-reader-meta">
            <Icon name="clock" size={15} />
            <span>
              {tx(course.duration_minutes)}
              {t(' мин')}
            </span>
            {tx(
              course.assignment && (
                <>
                  <StatusBadge status={course.assignment.status} />
                  <Deadline due={course.assignment.due_on} status={course.assignment.status} />
                </>
              ),
            )}
          </div>
          <div className="academy-course-facts">
            <span>{tx(course.category || 'Общее')}</span>
            <span>{tx(course.audience || 'Все сотрудники')}</span>
            <strong>
              {t('Проходной балл — ')}
              {tx(course.passing_score ?? 80)}%
            </strong>
          </div>
          {step === 'material' && (
            <>
              <p className="muted">{tx(course.description)}</p>
              {course.material_markdown ? (
                <>
                  {course.content_language === 'ru' && getLocale() === 'kk' && (
                    <p className="muted">Материал орыс тілінде берілген</p>
                  )}
                  {course.lessons?.length ? (
                    <LessonReader
                      course={course}
                      onSave={saveAssignment}
                      render={(text) => <Material content={text} />}
                    />
                  ) : (
                    <Material content={course.material_markdown} />
                  )}
                </>
              ) : (
                <EmptyState
                  title={t('Материал пока не опубликован')}
                  description={t('Обратитесь к руководителю, чтобы уточнить содержание курса.')}
                />
              )}
              {course.assignment?.status === 'completed' ? (
                <div className="support-note">
                  <Icon name="check-circle" size={18} />
                  <p>
                    {t('Курс завершён. Ваш результат: ')}
                    <strong>{tx(course.assignment.score_percent ?? '—')}%</strong>.
                  </p>
                </div>
              ) : !course.assignment ? (
                <div className="support-note">
                  <Icon name="info" size={18} />
                  <p>{t('Для прохождения теста нужно назначение курса.')}</p>
                </div>
              ) : !course.quiz.length ? (
                <div className="support-note">
                  <Icon name="info" size={18} />
                  <p>{t('Тест пока не опубликован.')}</p>
                </div>
              ) : (
                <div className="support-reader-actions">
                  <span className="muted">
                    {t('Вопросов: ')}
                    {tx(course.quiz.length)}
                  </span>
                  <button
                    className="btn btn-primary"
                    disabled={
                      busy ||
                      !course.material_markdown ||
                      Boolean(
                        course.lessons?.some(
                          (l) => !course.assignment?.completed_lesson_ids?.includes(l.id),
                        ),
                      )
                    }
                    onClick={beginQuiz}
                  >
                    {tx(busy ? 'Сохраняем прогресс…' : 'Перейти к тесту')}
                    <Icon name="arrow-right" size={16} />
                  </button>
                </div>
              )}
            </>
          )}
          {tx(
            step === 'quiz' && (
              <form onSubmit={finishQuiz}>
                <div className="support-note" style={{ marginBottom: 22 }}>
                  <Icon name="info" size={17} />
                  <p>
                    {t('Один ответ на вопрос · проходной балл ')}
                    {tx(course.passing_score ?? 80)}
                    {t('% · можно повторить.')}
                  </p>
                </div>
                {tx(
                  course.quiz.map((question, index) => (
                    <fieldset className="support-quiz" key={question.id} disabled={busy}>
                      <legend>
                        {tx(index + 1)}. {tx(question.prompt)}
                      </legend>
                      {tx(
                        question.options.map((option, optionIndex) => (
                          <label className="support-option" key={optionIndex}>
                            <input
                              type="radio"
                              name={`quiz-${question.id}`}
                              value={optionIndex}
                              checked={answers[question.id] === optionIndex}
                              required
                              onChange={() =>
                                setAnswers((previous) => ({
                                  ...previous,
                                  [question.id]: optionIndex,
                                }))
                              }
                            />
                            <span>{tx(option)}</span>
                          </label>
                        )),
                      )}
                    </fieldset>
                  )),
                )}
                <div className="support-reader-actions">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setStep('material')}
                    disabled={busy}
                  >
                    {t('К материалу')}
                  </button>
                  <button className="btn btn-primary" disabled={busy}>
                    {tx(busy ? 'Проверяем ответы…' : 'Завершить тест')}
                    <Icon name="check" size={16} />
                  </button>
                </div>
              </form>
            ),
          )}
          {tx(
            step === 'result' && (
              <div
                className={`support-result ${course.assignment?.status === 'completed' ? '' : 'academy-result-failed'}`}
              >
                <div className="support-result-icon">
                  <Icon
                    name={course.assignment?.status === 'completed' ? 'graduation' : 'book'}
                    size={30}
                  />
                </div>
                <h2>
                  {tx(
                    course.assignment?.status === 'completed'
                      ? 'Обучение завершено'
                      : 'Попробуйте ещё раз',
                  )}
                </h2>
                <div className="support-result-score">
                  {tx(course.assignment?.score_percent ?? '—')}%
                </div>
                <p>
                  {tx(
                    course.assignment?.status === 'completed'
                      ? 'Отличная работа! Результат сохранён.'
                      : `Нужно набрать ${course.passing_score ?? 80}%. Повторите материал или попробуйте снова.`,
                  )}
                </p>
                <div className="academy-result-actions">
                  {tx(
                    course.assignment?.status !== 'completed' && (
                      <>
                        <button className="btn btn-secondary" onClick={() => setStep('material')}>
                          {t('Повторить материал')}
                        </button>
                        <button
                          className="btn btn-primary"
                          onClick={() => {
                            setAnswers({});
                            setActionError('');
                            setStep('quiz');
                          }}
                        >
                          {t('Повторить тест')}
                        </button>
                      </>
                    ),
                  )}
                  <button
                    className={`btn ${course.assignment?.status === 'completed' ? 'btn-primary' : 'btn-ghost'}`}
                    onClick={onClose}
                  >
                    {t('Вернуться к курсам')}
                  </button>
                </div>
              </div>
            ),
          )}
          {tx(
            course.assignment && step !== 'quiz' && (
              <section className="academy-attempts">
                <h3>
                  {t('История попыток ')}
                  <span className="muted">
                    · {tx(course.assignment.attempt_count ?? attempts.length)}
                  </span>
                </h3>
                {tx(
                  attemptError ? (
                    <ErrorState error={attemptError} retry={() => void refreshAttempts()} />
                  ) : attempts.length ? (
                    <ol>
                      {tx(
                        attempts.map((attempt) => (
                          <li key={attempt.id}>
                            <span>
                              {t('Попытка ')}
                              {tx(attempt.attempt_number)}
                              <small>
                                {tx(
                                  formatDate(attempt.submitted_at, {
                                    hour: '2-digit',
                                    minute: '2-digit',
                                    timeZone: 'Asia/Qyzylorda',
                                  }),
                                )}
                              </small>
                            </span>
                            <strong>{tx(attempt.score_percent)}%</strong>
                            <span
                              className={`badge ${attempt.passed ? 'badge-approved' : 'badge-pending'}`}
                            >
                              {tx(attempt.passed ? 'Зачтено' : 'Нужен повтор')}
                            </span>
                          </li>
                        )),
                      )}
                    </ol>
                  ) : (
                    <p className="muted">
                      {tx(
                        course.assignment.status === 'completed'
                          ? 'Курс завершён ранее, без истории попыток.'
                          : 'Вы ещё не проходили тест.',
                      )}
                    </p>
                  ),
                )}
              </section>
            ),
          )}
          {tx(
            actionError && (
              <p className="support-inline-error" role="alert">
                {tx(actionError)}
              </p>
            ),
          )}
        </div>
      )}
    </Modal>
  );
}

export default function Academy() {
  const { api, profile, refreshKey } = usePortal();
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [params, setParams] = useSearchParams();
  const opened = params.get('course');
  const canManage = ['manager', 'director'].includes(profile.role) || profile.role === 'hr_admin';
  const tab =
    params.get('tab') === 'team' && canManage
      ? 'team'
      : params.get('tab') === 'all'
        ? 'all'
        : 'mine';
  function changeTab(value: string) {
    const next = new URLSearchParams(params);
    next.set('tab', value);
    next.delete('course');
    setParams(next);
  }
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([api.getCourses(), api.getMyCourses()])
      .then(([catalog, mine]) => {
        if (active) {
          const merged = new Map(catalog.map((c) => [c.id, c]));
          for (const a of mine)
            if (a.course) merged.set(a.course_id, { ...a.course, assignment: a });
          setCourses([...merged.values()]);
        }
      })
      .catch((err) => {
        if (active) setError(err);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, refreshKey, retry]);
  const assigned = courses.filter((course) => course.assignment);
  const completed = assigned.filter((course) => course.assignment?.status === 'completed');
  const visible = courses.filter(
    (course) =>
      (tab === 'all' || !!course.assignment) &&
      (statusFilter === 'all' || course.assignment?.status === statusFilter) &&
      `${course.title} ${course.description} ${course.category || ''}`
        .toLocaleLowerCase('ru')
        .includes(search.toLocaleLowerCase('ru')),
  );
  function closeCourse() {
    const next = new URLSearchParams(params);
    next.delete('course');
    setParams(next);
  }
  return (
    <div className="support-page">
      <PageHeader
        title={t('Обучение')}
        description={t('Новый навык — в вашем темпе')}
        actions={
          <span className="academy-brand">
            <Icon name="graduation" size={19} />
            Jana Academy
          </span>
        }
      />
      {tab !== 'team' && <MyTracks />}
      <div className="support-tabs" role="group" aria-label={t('Разделы обучения')}>
        <button
          className="support-tab"
          aria-pressed={tab === 'mine'}
          onClick={() => changeTab('mine')}
        >
          {t('Моё обучение')}
          <span>{tx(assigned.length)}</span>
        </button>
        <button
          className="support-tab"
          aria-pressed={tab === 'all'}
          onClick={() => changeTab('all')}
        >
          {t('Каталог курсов')}
          <span>{tx(courses.length)}</span>
        </button>
        {tx(
          canManage && (
            <button
              className="support-tab"
              aria-pressed={tab === 'team'}
              onClick={() => changeTab('team')}
            >
              {t('Обучение команды')}
            </button>
          ),
        )}
      </div>
      {tx(
        tab === 'team' && canManage ? (
          <TeamLearning
            courseId={params.get('courseFilter') || undefined}
            onResetCourse={() => {
              const next = new URLSearchParams(params);
              next.delete('courseFilter');
              setParams(next);
            }}
          />
        ) : loading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} retry={() => setRetry((value) => value + 1)} />
        ) : (
          <>
            <div className="support-metrics">
              <div className="support-metric">
                <span>
                  <Icon name="book" />
                </span>
                <div>
                  <strong>{tx(assigned.length)}</strong>
                  <small>{t('Всего назначено')}</small>
                </div>
              </div>
              <div className="support-metric">
                <span>
                  <Icon name="clock" />
                </span>
                <div>
                  <strong>{tx(assigned.length - completed.length)}</strong>
                  <small>{t('Осталось пройти')}</small>
                </div>
              </div>
              <div className="support-metric">
                <span>
                  <Icon name="check-circle" />
                </span>
                <div>
                  <strong>{tx(completed.length)}</strong>
                  <small>{t('Завершено')}</small>
                </div>
              </div>
            </div>
            <div className="support-toolbar">
              <label className="academy-filter">
                <span>{t('Статус')}</span>
                <select
                  className="input"
                  aria-label={t('Статус обучения')}
                  value={statusFilter}
                  onChange={(event) => setStatusFilter(event.target.value)}
                >
                  <option value="all">{t('Все курсы')}</option>
                  <option value="not_started">{t('Не начаты')}</option>
                  <option value="in_progress">{t('В процессе')}</option>
                  <option value="completed">{t('Завершены')}</option>
                </select>
              </label>
              <label className="support-search">
                <Icon name="search" size={16} />
                <input
                  className="input"
                  placeholder={t('Название или категория')}
                  aria-label={t('Поиск курса')}
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </label>
            </div>
            {tx(
              visible.length ? (
                <div className="support-course-grid">
                  {tx(
                    visible.map((course, index) => (
                      <article className="card support-course" key={course.id}>
                        <div className="support-course-heading">
                          <span className={`support-course-icon tone-${index % 3}`}>
                            <Icon
                              name={
                                index % 3 === 0 ? 'graduation' : index % 3 === 1 ? 'shield' : 'book'
                              }
                              size={26}
                            />
                          </span>
                          {tx(
                            course.assignment ? (
                              <>
                                <StatusBadge status={course.assignment.status} />
                                <Deadline
                                  due={course.assignment.due_on}
                                  status={course.assignment.status}
                                />
                              </>
                            ) : (
                              <span className="academy-unassigned">{t('В каталоге')}</span>
                            ),
                          )}
                        </div>
                        <div className="support-course-body">
                          <span className="academy-card-category">
                            {tx(course.category || 'Общее')}
                          </span>
                          <h3>{tx(course.title)}</h3>
                          <p className="support-course-description">{tx(course.description)}</p>
                          <div className="support-course-meta">
                            <span>
                              <Icon name="clock" size={14} />
                              {tx(course.duration_minutes)}
                              {t(' мин')}
                            </span>
                            <span>
                              <Icon name="users" size={14} />
                              {tx(course.audience || 'Все сотрудники')}
                            </span>
                          </div>
                          {tx(
                            course.assignment && (
                              <div className="support-course-progress">
                                <div className="support-progress-label">
                                  <strong>
                                    {tx(course.assignment.progress_percent)}
                                    {t('% пройдено')}
                                  </strong>
                                  <span>
                                    {tx(
                                      course.assignment.score_percent != null
                                        ? `Тест: ${course.assignment.score_percent}%`
                                        : `Порог ${course.passing_score ?? 80}%`,
                                    )}
                                  </span>
                                </div>
                                <div
                                  className="support-progress"
                                  role="progressbar"
                                  aria-label={`Прогресс: ${course.title}`}
                                  aria-valuemin={0}
                                  aria-valuemax={100}
                                  aria-valuenow={course.assignment.progress_percent}
                                >
                                  <span
                                    style={{
                                      width: `${course.assignment.progress_percent}%`,
                                    }}
                                  />
                                </div>
                              </div>
                            ),
                          )}
                          <button
                            className={`btn ${course.assignment && course.assignment.status !== 'completed' ? 'btn-primary' : 'btn-secondary'}`}
                            disabled={!course.assignment && !canManage}
                            onClick={() => {
                              const next = new URLSearchParams(params);
                              next.set('course', course.id);
                              setParams(next);
                            }}
                          >
                            {tx(
                              course.assignment?.status === 'completed'
                                ? 'К материалам'
                                : course.assignment?.status === 'in_progress'
                                  ? 'Продолжить'
                                  : course.assignment
                                    ? 'Начать курс'
                                    : canManage
                                      ? 'Посмотреть курс'
                                      : 'Назначает руководитель',
                            )}
                            <Icon
                              name={course.assignment || canManage ? 'arrow-right' : 'lock'}
                              size={16}
                            />
                          </button>
                        </div>
                      </article>
                    )),
                  )}
                </div>
              ) : (
                <EmptyState
                  title={
                    search
                      ? 'Курсы не найдены'
                      : statusFilter !== 'all'
                        ? 'Нет курсов с выбранным статусом'
                        : tab === 'all'
                          ? 'Каталог пока пуст'
                          : 'Пока нет назначенных курсов'
                  }
                  description={
                    search ? 'Попробуйте другой запрос.' : 'Курсы назначает руководитель или HR.'
                  }
                />
              ),
            )}
          </>
        ),
      )}
      {tx(opened && <CourseReader key={opened} id={opened} onClose={closeCourse} />)}
    </div>
  );
}
