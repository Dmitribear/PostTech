import { useEffect, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { usePortal } from '../context';
import { EmptyState, ErrorState, Icon, LoadingState, Modal, PageHeader, StatusBadge } from '../components/ui';
import { errorMessage } from '../lib/api';
import type { Course, CourseAssignment, CourseDetail } from '../lib/types';
import './support.css';

function Material({ content }: { content: string }) {
  return <div className="support-material">{content.split(/\n\s*\n/).map((block, index) => {
    if (/^#{1,2} /.test(block)) return <h2 key={index}>{block.replace(/^#{1,2} /, '')}</h2>;
    if (/^#{3,6} /.test(block)) return <h3 key={index}>{block.replace(/^#{3,6} /, '')}</h3>;
    if (block.split('\n').every(line => /^[-*] /.test(line))) return <ul key={index}>{block.split('\n').map((line, i) => <li key={i}>{line.slice(2)}</li>)}</ul>;
    return <p key={index}>{block}</p>;
  })}</div>;
}

function CourseReader({ id, onClose }: { id: string; onClose: () => void }) {
  const { api, refresh, notify } = usePortal();
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  const [step, setStep] = useState<'material' | 'quiz' | 'result'>('material');
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  useEffect(() => {
    let active = true;
    setCourse(null); setError(null);
    api.getCourse(id).then(value => { if (active) setCourse(value); }).catch(err => { if (active) setError(err); });
    return () => { active = false; };
  }, [api, id, retry]);
  const saveAssignment = (assignment: CourseAssignment) => {
    setCourse(previous => previous ? { ...previous, assignment } : previous);
    refresh();
  };
  async function beginQuiz() {
    if (!course || busy) return;
    setBusy(true); setActionError('');
    try {
      saveAssignment(await api.updateCourseProgress(id, 90));
      setStep('quiz');
    } catch (err) { setActionError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  async function finishQuiz(event: FormEvent) {
    event.preventDefault();
    if (!course || busy) return;
    if (course.quiz.some(question => answers[question.id] === undefined)) { setActionError('Ответьте на каждый вопрос перед отправкой.'); return; }
    setBusy(true); setActionError('');
    try {
      saveAssignment(await api.completeCourse(id, answers));
      setStep('result'); notify('Курс завершён. Результат теста сохранён.');
    } catch (err) { setActionError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  return <Modal title={course?.title || 'Учебный курс'} onClose={() => { if (!busy) onClose(); }} wide>
    {error ? <ErrorState error={error} retry={() => setRetry(value => value + 1)} /> : !course ? <LoadingState /> : <div className="support-course-reader">
      <div className="support-reader-meta"><Icon name="clock" size={15} /><span>{course.duration_minutes} мин</span>{course.assignment && <StatusBadge status={course.assignment.status} />}</div>
      {step === 'material' && <>
        <p className="muted">{course.description}</p>
        {course.material_markdown ? <Material content={course.material_markdown} /> : <EmptyState title="Материал пока не опубликован" description="Обратитесь к руководителю, чтобы уточнить содержание курса." />}
        {course.assignment?.status === 'completed' ? <div className="support-note"><Icon name="check-circle" size={18} /><p>Курс завершён. Ваш результат: <strong>{course.assignment.score_percent ?? '—'}%</strong>.</p></div> : !course.assignment ? <div className="support-note"><Icon name="info" size={18} /><p>Вы просматриваете материал курса. Для прохождения теста курс должен быть назначен вам.</p></div> : !course.quiz.length ? <div className="support-note"><Icon name="info" size={18} /><p>Итоговый тест для этого курса пока не настроен. Завершить курс можно после его публикации.</p></div> : <div className="support-reader-actions"><span className="muted">{course.quiz.length} вопроса в итоговом тесте</span><button className="btn btn-primary" disabled={busy || !course.material_markdown} onClick={beginQuiz}>{busy ? 'Сохраняем прогресс…' : 'Материал изучен · Перейти к тесту'}<Icon name="arrow-right" size={16} /></button></div>}
      </>}
      {step === 'quiz' && <form onSubmit={finishQuiz}>
        <div className="support-note" style={{ marginBottom: 22 }}><Icon name="info" size={17} /><p>Выберите один ответ для каждого вопроса. После отправки Jana Academy рассчитает и сохранит ваш результат.</p></div>
        {course.quiz.map((question, index) => <fieldset className="support-quiz" key={question.id} disabled={busy}><legend>{index + 1}. {question.prompt}</legend>{question.options.map((option, optionIndex) => <label className="support-option" key={optionIndex}><input type="radio" name={`quiz-${question.id}`} value={optionIndex} checked={answers[question.id] === optionIndex} required onChange={() => setAnswers(previous => ({ ...previous, [question.id]: optionIndex }))} /><span>{option}</span></label>)}</fieldset>)}
        <div className="support-reader-actions"><button type="button" className="btn btn-secondary" onClick={() => setStep('material')} disabled={busy}>К материалу</button><button className="btn btn-primary" disabled={busy}>{busy ? 'Проверяем ответы…' : 'Завершить тест'}<Icon name="check" size={16} /></button></div>
      </form>}
      {step === 'result' && <div className="support-result"><div className="support-result-icon"><Icon name="graduation" size={30} /></div><h2>Обучение завершено</h2><div className="support-result-score">{course.assignment?.score_percent ?? '—'}%</div><p>Ваш результат сохранён в Jana Academy.<br />Материалы курса остаются доступны для повторения.</p><button className="btn btn-primary" onClick={onClose}>Вернуться к курсам</button></div>}
      {actionError && <p className="support-inline-error" role="alert">{actionError}</p>}
    </div>}
  </Modal>;
}

export default function Academy() {
  const { api, profile, refreshKey } = usePortal();
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  const [tab, setTab] = useState('mine');
  const [search, setSearch] = useState('');
  const [params, setParams] = useSearchParams();
  const opened = params.get('course');
  useEffect(() => {
    let active = true;
    setLoading(true); setError(null);
    api.getCourses().then(value => { if (active) setCourses(value); }).catch(err => { if (active) setError(err); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api, refreshKey, retry]);
  const assigned = courses.filter(course => course.assignment);
  const completed = assigned.filter(course => course.assignment?.status === 'completed');
  const visible = courses.filter(course => (tab === 'all' || (tab === 'done' ? course.assignment?.status === 'completed' : !!course.assignment)) && `${course.title} ${course.description}`.toLocaleLowerCase('ru').includes(search.toLocaleLowerCase('ru')));
  function closeCourse() { const next = new URLSearchParams(params); next.delete('course'); setParams(next); }
  return <div className="support-page">
    <PageHeader title="Jana Academy" description="Знания, которые помогают расти каждый день" eyebrow="Обучение и развитие" />
    <section className="support-hero"><div><span className="support-eyebrow">Ваш следующий шаг</span><h2>Развивайтесь вместе с PostTech</h2><p>Проходите назначенные курсы в удобном темпе, изучайте материалы и проверяйте знания в коротких тестах.</p></div><div className="support-hero-icon"><Icon name="graduation" size={43} /></div></section>
    {loading ? <LoadingState /> : error ? <ErrorState error={error} retry={() => setRetry(value => value + 1)} /> : <>
      <div className="support-metrics"><div className="support-metric"><span><Icon name="book" /></span><div><strong>{assigned.length}</strong><small>Назначено курсов</small></div></div><div className="support-metric"><span><Icon name="clock" /></span><div><strong>{assigned.length - completed.length}</strong><small>Ожидают завершения</small></div></div><div className="support-metric"><span><Icon name="check-circle" /></span><div><strong>{completed.length}</strong><small>Завершено курсов</small></div></div></div>
      <div className="support-toolbar"><div className="support-tabs" role="group" aria-label="Фильтр курсов">{[['mine', 'Моё обучение', assigned.length], ['all', 'Каталог курсов', courses.length], ['done', 'Завершённые', completed.length]].map(([key, label, count]) => <button key={key} className="support-tab" aria-pressed={tab === key} onClick={() => setTab(String(key))}>{label}<span>{count}</span></button>)}</div><label className="support-search"><Icon name="search" size={16} /><input className="input" placeholder="Найти курс" aria-label="Поиск курса" value={search} onChange={event => setSearch(event.target.value)} /></label></div>
      {visible.length ? <div className="support-course-grid">{visible.map((course, index) => <article className="card support-course" key={course.id}><div className={`support-course-cover tone-${index % 3}`}>{course.assignment && <StatusBadge status={course.assignment.status} />}<Icon name={index % 3 === 0 ? 'graduation' : index % 3 === 1 ? 'shield' : 'book'} size={43} /></div><div className="support-course-body"><h3>{course.title}</h3><p className="support-course-description">{course.description}</p><div className="support-course-meta"><Icon name="clock" size={14} />{course.duration_minutes} минут<span>·</span>Материал и тест</div><div className="support-progress" role="progressbar" aria-label={`Прогресс: ${course.title}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={course.assignment?.progress_percent || 0}><span style={{ width: `${course.assignment?.progress_percent || 0}%` }} /></div><div className="support-progress-label"><strong>{course.assignment?.progress_percent || 0}% пройдено</strong><span>{course.assignment?.status === 'completed' ? `Результат: ${course.assignment.score_percent ?? '—'}%` : course.assignment ? 'Назначен вам' : 'Не назначен'}</span></div><button className={`btn ${course.assignment && course.assignment.status !== 'completed' ? 'btn-primary' : 'btn-secondary'}`} disabled={!course.assignment && profile.role !== 'hr_admin'} onClick={() => { const next = new URLSearchParams(params); next.set('course', course.id); setParams(next); }}>{course.assignment?.status === 'completed' ? 'Повторить материал' : course.assignment?.status === 'in_progress' ? 'Продолжить обучение' : course.assignment ? 'Начать обучение' : profile.role === 'hr_admin' ? 'Посмотреть материал' : 'Назначает руководитель'}<Icon name={course.assignment || profile.role === 'hr_admin' ? 'arrow-right' : 'lock'} size={15} /></button></div></article>)}</div> : <EmptyState title={search ? 'Курсы не найдены' : tab === 'done' ? 'Завершённых курсов пока нет' : 'Пока нет назначенных курсов'} description={search ? 'Попробуйте изменить поисковый запрос.' : 'Когда руководитель назначит обучение, оно появится здесь.'} />}
      <div className="support-note"><Icon name="info" size={18} /><p>Обучение назначает ваш руководитель или HR. Прогресс сохраняется после изучения материала, а результат — после прохождения теста.</p></div>
    </>}
    {opened && <CourseReader key={opened} id={opened} onClose={closeCourse} />}
  </div>;
}
