import { usePortal } from '@/entities/session';
import { t, tx } from '@/shared/lib/i18n';
import '@/shared/styles/workspace.css';
import { EmptyState, ErrorState, LoadingState, Modal, PageHeader } from '@/shared/ui/index';
import { ListPager, useListPage } from '@/shared/ui/molecules/ListPager';
import { useEffect, useState } from 'react';

type Question = {
  id: string;
  prompt: string;
  options: string[];
  answer_index: number;
};
type Lesson = { id: string; title: string; material_markdown: string };
type Translation = {
  title: string;
  description: string;
  material_markdown: string;
  quiz: Question[];
  lessons?: Lesson[];
};
type Content = Translation & {
  course_type: 'internal' | 'external';
  provider: string;
  external_url: string | null;
  duration_minutes: number;
  passing_score: number;
  category: string;
  audience: string;
  family_id?: string;
  translations: { kk?: Translation };
};
interface AdminCourse extends Content {
  id: string;
  version: number;
  revision: number;
  publication_state: 'draft' | 'published' | 'archived';
}
const blank = (): Content => ({
  course_type: 'external',
  provider: '',
  external_url: '',
  title: '',
  description: '',
  material_markdown: '',
  lessons: [],
  duration_minutes: 0,
  passing_score: 80,
  category: 'Повышение квалификации',
  audience: 'Все сотрудники',
  quiz: [],
  translations: {},
});

export default function CourseEditor() {
  const { api, profile, refresh, refreshKey, notify } = usePortal();
  const [rows, setRows] = useState<AdminCourse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [editing, setEditing] = useState<AdminCourse | null>(null);
  const [data, setData] = useState<Content | null>(null);
  const [lang, setLang] = useState<'ru' | 'kk'>('ru');
  const [busy, setBusy] = useState(false);
  const [id, setId] = useState(() => crypto.randomUUID());
  const [initial, setInitial] = useState('');
  const dirty = !!data && JSON.stringify(data) !== initial;
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [discard, setDiscard] = useState(false);
  const filtered = rows.filter(
    (c) =>
      (status === 'all' || c.publication_state === status) &&
      `${c.title} ${c.category}`.toLocaleLowerCase().includes(search.toLocaleLowerCase().trim()),
  );
  const paging = useListPage(filtered, `${search}|${status}`);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const [confirmation, setConfirmation] = useState<{
    course: AdminCourse;
    action: 'publish' | 'archive';
  } | null>(null);
  useEffect(() => {
    let active = true;
    setLoading(true);
    api
      .workspace<AdminCourse[]>('/courses')
      .then((r) => {
        if (active) setRows(r);
      })
      .catch((e) => {
        if (active) setError(e);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, refreshKey]);
  if (profile.role !== 'hr_admin') return <EmptyState title={t('Раздел доступен HR')} />;
  function open(course?: AdminCourse) {
    setError(null);
    setLang('ru');
    setId(crypto.randomUUID());
    setEditing(course?.publication_state === 'draft' ? course : null);
    const next = course
      ? {
          course_type: course.course_type || 'internal',
          provider: course.provider || '',
          external_url: course.external_url || null,
          title: course.title,
          description: course.description,
          material_markdown: course.material_markdown,
          quiz: structuredClone(course.quiz),
          lessons: structuredClone(course.lessons || []),
          duration_minutes: course.duration_minutes,
          passing_score: course.passing_score,
          category: course.category,
          audience: course.audience,
          family_id: course.family_id,
          translations: structuredClone(course.translations),
        }
      : blank();
    setData(next);
    setInitial(JSON.stringify(next));
  }
  function change(key: keyof Translation, value: string | Question[] | Lesson[]) {
    if (!data) return;
    if (lang === 'ru') setData({ ...data, [key]: value });
    else
      setData({
        ...data,
        translations: {
          kk: {
            ...(data.translations.kk || {
              title: '',
              description: '',
              material_markdown: '',
              lessons: (data.lessons || []).map((l) => ({
                ...l,
                title: '',
                material_markdown: '',
              })),
              quiz: data.quiz.map((q) => ({
                ...q,
                prompt: '',
                options: q.options.map(() => ''),
              })),
            }),
            [key]: value,
          },
        },
      });
  }
  function switchLanguage(value: 'ru' | 'kk') {
    if (value === 'kk' && data && !data.translations.kk)
      setData({
        ...data,
        translations: {
          kk: {
            title: '',
            description: '',
            material_markdown: '',
            lessons: (data.lessons || []).map((l) => ({
              ...l,
              title: '',
              material_markdown: '',
            })),
            quiz: data.quiz.map((q) => ({
              ...q,
              prompt: '',
              options: q.options.map(() => ''),
            })),
          },
        },
      });
    setLang(value);
  }
  async function save() {
    if (!data || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.workspace<AdminCourse>('/courses', 'POST', {
        id: editing?.id || id,
        action: editing ? 'save' : 'create',
        revision: editing?.revision || 0,
        data,
      });
      setEditing(result);
      setData(null);
      setSearch(result.title);
      setStatus('all');
      notify(t('Черновик сохранён'));
      refresh();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function transition() {
    if (!confirmation || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.workspace('/courses', 'POST', {
        id: confirmation.course.id,
        revision: confirmation.course.revision,
        action: confirmation.action,
      });
      setConfirmation(null);
      refresh();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  const current = data && (lang === 'ru' ? data : data.translations.kk);
  function question(index: number, patch: Partial<Question>) {
    if (!current || !data) return;
    const quiz = current.quiz.map((q, i) => (i === index ? { ...q, ...patch } : q));
    if (lang === 'ru' && data.translations.kk && patch.answer_index !== undefined) {
      setData({
        ...data,
        quiz,
        translations: {
          kk: {
            ...data.translations.kk,
            quiz: data.translations.kk.quiz.map((q, i) =>
              i === index ? { ...q, answer_index: patch.answer_index! } : q,
            ),
          },
        },
      });
    } else change('quiz', quiz);
  }
  return (
    <div className="support-page">
      <PageHeader
        title={t('Редактор курсов')}
        actions={
          !data && (
            <button className="btn btn-primary" onClick={() => open()}>
              {t('Создать курс')}
            </button>
          )
        }
      />
      {tx(Boolean(error) && <ErrorState error={error} retry={refresh} />)}
      {data && current ? (
        <form
          className="card ws-editor ws-stack"
          onInvalidCapture={(e) => {
            const details = (e.target as HTMLElement).closest('details');
            if (details) details.open = true;
          }}
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <div className="ws-row">
            <h2>{tx(editing ? 'Черновик курса' : 'Новая версия курса')}</h2>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={busy}
              onClick={() => {
                if (dirty) setDiscard(true);
                else {
                  setData(null);
                  setError(null);
                }
              }}
            >
              {t('Закрыть')}
            </button>
          </div>
          <nav className="ws-section-nav" aria-label={t('Разделы курса')}>
            <a href="#course-basics">{t('Основное')}</a>
            {data.course_type === 'internal' && (
              <>
                <a href="#course-material">{t('Материал')}</a>
                <a href="#course-quiz">{t('Тест')}</a>
              </>
            )}
          </nav>
          <label className="field">
            {t('Формат курса')}
            <select
              className="input"
              value={data.course_type}
              disabled={busy || Boolean(editing) || Boolean(data.family_id)}
              onChange={(e) =>
                setData({
                  ...data,
                  course_type: e.target.value as Content['course_type'],
                  translations: {},
                  lessons: [],
                  quiz:
                    e.target.value === 'internal'
                      ? [{ id: 'q1', prompt: '', options: ['', ''], answer_index: 0 }]
                      : [],
                })
              }
            >
              <option value="external">{t('На внешней площадке')}</option>
              <option value="internal">{t('Внутренний материал и тест')}</option>
            </select>
          </label>
          {data.course_type === 'external' && (
            <>
              <label className="field">
                {t('Площадка')}
                <input
                  className="input"
                  required
                  maxLength={160}
                  placeholder="Яндекс Практикум, Coursera…"
                  value={data.provider}
                  disabled={busy}
                  onChange={(e) => setData({ ...data, provider: e.target.value })}
                />
              </label>
              <label className="field">
                {t('Ссылка на курс')}
                <input
                  className="input"
                  type="url"
                  pattern="https://.*"
                  required
                  maxLength={2000}
                  placeholder="https://…"
                  value={data.external_url || ''}
                  disabled={busy}
                  onChange={(e) => setData({ ...data, external_url: e.target.value })}
                />
              </label>
            </>
          )}
          <div id="course-basics" className="ws-languages">
            <button
              type="button"
              className="btn btn-secondary"
              aria-pressed={lang === 'ru'}
              onClick={() => switchLanguage('ru')}
            >
              {t('Русский')}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              aria-pressed={lang === 'kk'}
              onClick={() => switchLanguage('kk')}
            >
              {t('Қазақша')}
            </button>
          </div>
          <label className="field">
            {t('Название курса')}
            <input
              className="input"
              required
              minLength={3}
              maxLength={200}
              value={current.title}
              onChange={(e) => change('title', e.target.value)}
              disabled={busy}
            />
          </label>
          <label className="field">
            {t('Краткое описание')}
            <textarea
              className="input"
              maxLength={2000}
              value={current.description}
              onChange={(e) => change('description', e.target.value)}
              disabled={busy}
            />
          </label>
          <div className="ws-columns">
            <label className="field">
              {t('Длительность, минут')}
              <input
                className="input"
                type="number"
                min={data.course_type === 'external' ? 0 : 1}
                max={525600}
                required
                value={data.duration_minutes}
                onChange={(e) => setData({ ...data, duration_minutes: Number(e.target.value) })}
                disabled={busy}
              />
            </label>
            {data.course_type === 'internal' && (
              <label className="field">
                {t('Проходной балл, %')}
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={100}
                  required
                  value={data.passing_score}
                  onChange={(e) => setData({ ...data, passing_score: Number(e.target.value) })}
                  disabled={busy}
                />
              </label>
            )}
          </div>
          <div className="ws-columns">
            <label className="field">
              {t('Категория')}
              <input
                className="input"
                maxLength={100}
                required
                value={data.category}
                onChange={(e) => setData({ ...data, category: e.target.value })}
                disabled={busy}
              />
            </label>
            <label className="field">
              {t('Для кого')}
              <input
                className="input"
                maxLength={100}
                required
                value={data.audience}
                onChange={(e) => setData({ ...data, audience: e.target.value })}
                disabled={busy}
              />
            </label>
          </div>
          {data.course_type === 'internal' && (
            <>
              <label id="course-material" className="field">
                {t('Материал курса')}
                <textarea
                  className="input"
                  required
                  minLength={3}
                  maxLength={60000}
                  rows={12}
                  value={current.material_markdown}
                  onChange={(e) => change('material_markdown', e.target.value)}
                  disabled={busy}
                />
              </label>
              <section className="ws-stack">
                <h3>{t('Уроки')}</h3>
                <p className="muted">
                  {t(
                    'Разделите материал на короткие уроки. Прогресс каждого урока сохраняется отдельно. Без уроков курс работает как один материал.',
                  )}
                </p>
                {(current.lessons || []).map((lesson, index) => (
                  <details className="lesson-editor" key={lesson.id} open={!lesson.title}>
                    <summary>
                      {index + 1}. {lesson.title || t('Новый урок')}
                    </summary>
                    <div className="ws-stack">
                      <label className="field">
                        {t('Название урока')}
                        <input
                          className="input"
                          required
                          minLength={3}
                          maxLength={200}
                          disabled={busy}
                          value={lesson.title}
                          onChange={(e) =>
                            change(
                              'lessons',
                              (current.lessons || []).map((l, i) =>
                                i === index ? { ...l, title: e.target.value } : l,
                              ),
                            )
                          }
                        />
                      </label>
                      <label className="field">
                        {t('Материал урока')}
                        <textarea
                          className="input"
                          required
                          minLength={3}
                          maxLength={60000}
                          rows={8}
                          disabled={busy}
                          value={lesson.material_markdown}
                          onChange={(e) =>
                            change(
                              'lessons',
                              (current.lessons || []).map((l, i) =>
                                i === index ? { ...l, material_markdown: e.target.value } : l,
                              ),
                            )
                          }
                        />
                      </label>
                      {lang === 'ru' && !data.translations.kk && (
                        <div className="ws-actions">
                          <button
                            type="button"
                            className="btn btn-secondary"
                            disabled={busy || index === 0}
                            onClick={() => {
                              const lessons = [...(current.lessons || [])];
                              [lessons[index - 1], lessons[index]] = [
                                lessons[index],
                                lessons[index - 1],
                              ];
                              change('lessons', lessons);
                            }}
                          >
                            {t('Выше')}
                          </button>
                          <button
                            type="button"
                            className="btn btn-secondary"
                            disabled={busy || index === (current.lessons || []).length - 1}
                            onClick={() => {
                              const lessons = [...(current.lessons || [])];
                              [lessons[index + 1], lessons[index]] = [
                                lessons[index],
                                lessons[index + 1],
                              ];
                              change('lessons', lessons);
                            }}
                          >
                            {t('Ниже')}
                          </button>
                          <button
                            type="button"
                            className="btn btn-secondary"
                            disabled={busy}
                            onClick={() =>
                              change(
                                'lessons',
                                (current.lessons || []).filter((l) => l.id !== lesson.id),
                              )
                            }
                          >
                            {t('Удалить урок')}
                          </button>
                        </div>
                      )}
                    </div>
                  </details>
                ))}
                {lang === 'ru' && !data.translations.kk && (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    disabled={busy || (current.lessons || []).length >= 50}
                    onClick={() =>
                      change('lessons', [
                        ...(current.lessons || []),
                        {
                          id: crypto.randomUUID(),
                          title: '',
                          material_markdown: '',
                        },
                      ])
                    }
                  >
                    {t('Добавить урок')}
                  </button>
                )}
              </section>
              <h3 id="course-quiz">{t('Проверка знаний')}</h3>
              <p className="muted">
                {t('Правильные ответы видит только HR. В переводе сохраняйте порядок вариантов.')}
              </p>
              {tx(
                current.quiz.map((q, i) => (
                  <details
                    key={`${lang}-${q.id}`}
                    className="ws-question"
                    open={i === 0 || !q.prompt}
                  >
                    <summary>
                      {t('Вопрос ')}
                      {i + 1}
                      <span>{q.prompt || t('Новый вопрос')}</span>
                    </summary>
                    <div className="ws-stack">
                      <label className="field">
                        {t('Вопрос ')}
                        {tx(i + 1)}
                        <input
                          className="input"
                          required
                          minLength={3}
                          maxLength={2000}
                          value={q.prompt}
                          onChange={(e) => question(i, { prompt: e.target.value })}
                          disabled={busy}
                        />
                      </label>
                      {tx(
                        q.options.map((option, j) => (
                          <label className="field" key={j}>
                            {t('Вариант ')}
                            {tx(j + 1)}
                            <input
                              className="input"
                              required
                              maxLength={1000}
                              value={option}
                              onChange={(e) =>
                                question(i, {
                                  options: q.options.map((v, k) => (j === k ? e.target.value : v)),
                                })
                              }
                              disabled={busy}
                            />
                          </label>
                        )),
                      )}
                      <label className="field">
                        {t('Правильный вариант')}
                        <select
                          className="input"
                          value={q.answer_index}
                          onChange={(e) => question(i, { answer_index: Number(e.target.value) })}
                          disabled={busy || lang === 'kk'}
                        >
                          {tx(
                            q.options.map((_, j) => (
                              <option key={j} value={j}>
                                {tx(j + 1)}
                              </option>
                            )),
                          )}
                        </select>
                      </label>
                      {tx(
                        lang === 'ru' && !data.translations.kk && (
                          <div className="ws-actions">
                            <button
                              type="button"
                              className="btn btn-secondary"
                              disabled={busy || q.options.length >= 10}
                              onClick={() => question(i, { options: [...q.options, ''] })}
                            >
                              {t('Добавить вариант')}
                            </button>
                            <button
                              type="button"
                              className="btn btn-secondary"
                              disabled={busy || current.quiz.length === 1}
                              onClick={() =>
                                change(
                                  'quiz',
                                  current.quiz.filter((_, n) => n !== i),
                                )
                              }
                            >
                              {t('Удалить вопрос')}
                            </button>
                          </div>
                        ),
                      )}
                    </div>
                  </details>
                )),
              )}
              {tx(
                lang === 'ru' && !data.translations.kk && (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    disabled={busy || current.quiz.length >= 50}
                    onClick={() =>
                      change('quiz', [
                        ...current.quiz,
                        {
                          id: crypto.randomUUID(),
                          prompt: '',
                          options: ['', ''],
                          answer_index: 0,
                        },
                      ])
                    }
                  >
                    {t('Добавить вопрос')}
                  </button>
                ),
              )}
            </>
          )}
          {tx(
            data.course_type === 'internal' && data.translations.kk && (
              <p className="muted">
                {t(
                  'Структура теста общая для двух языков. Для изменения структуры сначала удалите перевод.',
                )}
              </p>
            ),
          )}
          {tx(
            data.translations.kk && (
              <button
                type="button"
                className="btn btn-secondary"
                disabled={busy}
                onClick={() => {
                  setData({ ...data, translations: {} });
                  setLang('ru');
                }}
              >
                {t('Удалить перевод из черновика')}
              </button>
            ),
          )}
          <div className="ws-form-actions">
            <button className="btn btn-primary" disabled={busy}>
              {tx(busy ? 'Сохраняем…' : 'Сохранить черновик')}
            </button>
          </div>
        </form>
      ) : (
        <>
          <div className="ws-list-tools list-anchor" ref={paging.anchor}>
            <label className="field">
              {t('Поиск курса')}
              <input
                className="input"
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('Название или категория')}
              />
            </label>
            <label className="field">
              {t('Статус')}
              <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="all">{t('Все')}</option>
                <option value="draft">{t('Черновик')}</option>
                <option value="published">{t('Опубликован')}</option>
                <option value="archived">{t('Архив')}</option>
              </select>
            </label>
          </div>
          {loading ? (
            <LoadingState />
          ) : filtered.length ? (
            <div className="ws-stack">
              {tx(
                paging.items.map((c) => (
                  <article className="card ws-row" key={c.id}>
                    <div>
                      <strong>{tx(c.title)}</strong>
                      <small>
                        v{tx(c.version)} ·{' '}
                        {tx(
                          c.publication_state === 'draft'
                            ? 'Черновик'
                            : c.publication_state === 'published'
                              ? 'Опубликован'
                              : 'Архив',
                        )}{' '}
                        · {tx(c.translations.kk ? 'RU / KZ' : 'RU')}
                      </small>
                    </div>
                    <div className="ws-actions">
                      <button className="btn btn-secondary" onClick={() => open(c)}>
                        {tx(c.publication_state === 'draft' ? 'Редактировать' : 'Новая версия')}
                      </button>
                      {tx(
                        c.publication_state === 'draft' && (
                          <button
                            className="btn btn-primary"
                            onClick={() => {
                              setError(null);
                              setConfirmation({ course: c, action: 'publish' });
                            }}
                          >
                            {t('Опубликовать')}
                          </button>
                        ),
                      )}
                      {tx(
                        c.publication_state === 'published' && (
                          <button
                            className="btn btn-secondary"
                            onClick={() => {
                              setError(null);
                              setConfirmation({ course: c, action: 'archive' });
                            }}
                          >
                            {t('В архив')}
                          </button>
                        ),
                      )}
                    </div>
                  </article>
                )),
              )}
            </div>
          ) : (
            <EmptyState title={t(rows.length ? 'Курсы не найдены' : 'Создайте первый курс')} />
          )}
          <ListPager {...paging} />
        </>
      )}
      {discard && (
        <Modal title={t('Закрыть без сохранения?')} onClose={() => setDiscard(false)}>
          <p>{t('Несохранённые изменения будут потеряны.')}</p>
          <div className="ws-actions">
            <button className="btn btn-secondary" onClick={() => setDiscard(false)}>
              {t('Продолжить редактирование')}
            </button>
            <button
              className="btn btn-primary"
              onClick={() => {
                setDiscard(false);
                setData(null);
                setError(null);
              }}
            >
              {t('Закрыть')}
            </button>
          </div>
        </Modal>
      )}
      {tx(
        confirmation && (
          <Modal
            title={
              confirmation.action === 'publish' ? 'Опубликовать курс?' : 'Убрать курс из каталога?'
            }
            onClose={() => {
              if (!busy) setConfirmation(null);
            }}
          >
            <p>
              {tx(
                confirmation.action === 'publish'
                  ? 'Новая версия появится в каталоге. Сотрудники с прежним назначением продолжат свою версию.'
                  : 'Новые назначения будут недоступны. Ранее назначенный курс можно пройти до конца.',
              )}
            </p>
            {tx(Boolean(error) && <ErrorState error={error} />)}
            <button className="btn btn-primary" disabled={busy} onClick={transition}>
              {t('Подтвердить')}
            </button>
          </Modal>
        ),
      )}
    </div>
  );
}
