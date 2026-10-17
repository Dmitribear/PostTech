import { t, tx } from '../lib/i18n';
import { ListPager, useListPage } from '../components/ListPager';
import { Deadline } from '../components/Deadline';
import { businessToday } from './Workspace';
import { useEffect, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { usePortal } from '../context';
import { Avatar, EmptyState, ErrorState, Icon, LoadingState, Modal, PageHeader, StatusBadge } from '../components/ui';
import { errorMessage } from '../lib/api';
import { formatDate } from '../lib/format';
import type { Course, EmployeeProfile, TeamCourseAssignment } from '../lib/types';
import { ProfileFields } from './Profile';
import './support.css';
import Invitations from './Invitations';

export function TeamLearning({ employeeId, onResetEmployee, courseId, onResetCourse }: { employeeId?: string; onResetEmployee?: () => void; courseId?: string; onResetCourse?: () => void }) {
  const { api, profile, refreshKey } = usePortal();
  const allowed = profile.role === 'manager' || profile.role === 'hr_admin';
  const [rows, setRows] = useState<TeamCourseAssignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  useEffect(() => {
    if (!allowed) return;
    let active = true; setLoading(true); setError(null);
    api.getTeamCourses({ ...(employeeId ? { employee_id: employeeId } : {}), ...(courseId ? { course_id: courseId } : {}) })
      .then(value => { if (active) setRows(value); })
      .catch(err => { if (active) setError(err); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api, allowed, employeeId, courseId, refreshKey, retry]);
  const visible = rows.filter(row => (status === 'all' || (status === 'retry' ? row.status !== 'completed' && row.score_percent != null : row.status === status)) && `${row.employee.full_name} ${row.employee.department} ${row.course?.title || ''}`.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru')));
  const paging = useListPage(visible, `${status}|${query}|${employeeId}|${courseId}`);
  if (!allowed) return <EmptyState title={t("Обучение команды доступно руководителю и HR")} />;
  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} retry={() => setRetry(value => value + 1)} />;

  const completed = rows.filter(row => row.status === 'completed').length;
  const needRetry = rows.filter(row => row.status !== 'completed' && row.score_percent != null).length;
  return <section className="academy-team-view">
    {tx(courseId && <div className="support-note"><Icon name="book" size={16} /><p>{t("Показаны назначения курса: ")}<strong>{tx(rows[0]?.course?.title || 'выбранный курс')}</strong>.</p>{tx(onResetCourse && <button className="btn btn-ghost" onClick={onResetCourse}>{t("Все курсы")}</button>)}</div>)}
    <div className="support-toolbar"><div><h2>{t("Обучение команды")}</h2><p className="muted">{tx(employeeId ? 'Курсы сотрудника' : profile.role === 'hr_admin' ? 'Все сотрудники' : 'Ваша команда')}</p></div>{tx(employeeId && onResetEmployee ? <button className="btn btn-secondary" onClick={onResetEmployee}>{t("Все сотрудники")}</button> : <Link className="btn btn-secondary" to="/team"><Icon name="users" size={15} />{t("Назначить обучение")}</Link>)}</div>
    <div className="support-metrics"><div className="support-metric"><span><Icon name="book" /></span><div><strong>{tx(rows.length)}</strong><small>{t("Назначений")}</small></div></div><div className="support-metric"><span><Icon name="check-circle" /></span><div><strong>{tx(completed)}</strong><small>{t("Завершено")}</small></div></div><div className="support-metric"><span><Icon name="refresh" /></span><div><strong>{tx(needRetry)}</strong><small>{t("Нужен повтор")}</small></div></div></div>
    <div className="support-toolbar list-anchor" ref={paging.anchor}><label className="academy-filter"><span>{t("Статус")}</span><select className="input" aria-label={t("Статус обучения команды")} value={status} onChange={event => setStatus(event.target.value)}><option value="all">{t("Все назначения")}</option><option value="not_started">{t("Не начаты")}</option><option value="in_progress">{t("В процессе")}</option><option value="completed">{t("Завершены")}</option><option value="retry">{t("Нужен повтор")}</option></select></label><label className="support-search"><Icon name="search" size={15} /><input className="input" value={query} onChange={event => setQuery(event.target.value)} aria-label={t("Поиск обучения команды")} placeholder={t("Сотрудник, отдел или курс")} /></label></div>
    {visible.length ? <div className="card academy-team-list"><div className="academy-team-head"><span>{t("Сотрудник / курс")}</span><span>{t("Прогресс")}</span><span>{t("Результат")}</span><span>{t("Статус")}</span></div>{paging.items.map(row => <article className="academy-team-row" key={row.id}><div className="academy-team-person"><Avatar name={row.employee.full_name} size={34} /><div><strong>{row.employee.full_name}</strong><small>{tx(row.employee.department)}</small><Link to={`/academy?tab=team&course=${encodeURIComponent(row.course_id)}`}>{tx(row.course?.title || 'Курс недоступен')}</Link></div></div><div><div className="support-progress" role="progressbar" aria-label={`Прогресс ${row.employee.full_name}: ${row.course?.title || 'курс'}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={row.progress_percent}><span style={{ width: `${row.progress_percent}%` }} /></div><div className="support-progress-label"><strong>{tx(row.progress_percent)}%</strong><span>{tx(row.material_completed_at ? 'Материал изучен' : row.progress_percent > 0 ? 'Изучает материал' : 'Не начат')}</span></div></div><div className="academy-team-score"><strong>{tx(row.score_percent == null ? '—' : `${row.score_percent}%`)}</strong><small>{t("Попыток: ")}{tx(row.attempt_count ?? 0)}{tx(row.course?.passing_score != null ? ` · порог ${row.course.passing_score}%` : '')}</small><small>{tx(row.last_attempt_at ? formatDate(row.last_attempt_at) : `Назначен ${formatDate(row.assigned_at)}`)}</small></div><div><StatusBadge status={row.status} /><Deadline id={row.id} due={row.due_on} status={row.status} editable /></div></article>)}</div> : <EmptyState title={rows.length ? 'Назначения не найдены' : 'Назначенных курсов пока нет'} description={rows.length ? 'Измените статус или поисковый запрос.' : 'Назначьте курс сотруднику из раздела команды.'} />}
    <ListPager {...paging} />
  </section>;
}

function EmployeeDetails({ id, onClose, onAssign, onLearning }: { id: string; onClose: () => void; onAssign: () => void; onLearning: () => void }) {
  const { api } = usePortal();
  const [employee, setEmployee] = useState<EmployeeProfile | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true; setEmployee(null); setError(null);
    api.getEmployee(id).then(value => { if (active) setEmployee(value); }).catch(err => { if (active) setError(err); });
    return () => { active = false; };
  }, [api, id, retry]);
  return <Modal title={t("Профиль сотрудника")} onClose={onClose} wide>{error ? <ErrorState error={error} retry={() => setRetry(value => value + 1)} /> : !employee ? <LoadingState /> : <><div className="support-team-detail-heading"><Avatar name={employee.full_name} size={52} /><div><h3>{employee.full_name}</h3><p>{tx(employee.job_title)} · {tx(employee.department)}</p></div></div><div className="employee-detail-actions"><button className="btn btn-primary" onClick={onAssign}>{t("Назначить курс")}</button><button className="btn btn-secondary" onClick={onLearning}>{t("Обучение")}</button></div><ProfileFields profile={employee} /><div className="support-note" style={{ marginTop: 20 }}><Icon name="plane" size={18} /><p><strong>{tx(employee.vacation_days_remaining)}{t(" дней")}</strong>{t(" отпуска · данные обновляет HR.")}</p></div></>}</Modal>;
}

function AssignCourse({ employee, courses, onClose }: { employee: EmployeeProfile; courses: Course[]; onClose: () => void }) {
  const { api, notify, refresh } = usePortal();
  const [courseId, setCourseId] = useState('');
  const [dueOn, setDueOn] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!courseId || busy) return;
    setBusy(true); setError('');
    try {
      await api.assignCourse(employee.id, courseId, dueOn);
      refresh(); notify(`Курс назначен: ${employee.full_name}.`); onClose();
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  return <Modal title={t("Назначить обучение")} onClose={() => { if (!busy) onClose(); }}><form className="support-assign-form" onSubmit={submit}><div className="support-team-detail-heading"><Avatar name={employee.full_name} size={42} /><div><h3>{employee.full_name}</h3><p>{tx(employee.job_title)}</p></div></div>{tx(courses.length ? <fieldset className="assign-course-options" disabled={busy}><legend className="field-label">{t("Курс Jana Academy")}</legend>{courses.length <= 6 ? courses.map(course => <label key={course.id} className="support-option"><input type="radio" name="assigned-course" value={course.id} checked={courseId === course.id} onChange={() => setCourseId(course.id)} required /><span>{course.title}<small>{course.duration_minutes}{t(" мин")}</small></span></label>) : <select className="input" aria-label={t("Курс Jana Academy")} value={courseId} onChange={event => setCourseId(event.target.value)} required><option value="">{t("Выберите курс")}</option>{courses.map(course => <option key={course.id} value={course.id}>{course.title} · {course.duration_minutes}{t(" мин")}</option>)}</select>}</fieldset> : <EmptyState title={t("Доступных курсов пока нет")} description={t("Курсы появятся после публикации учебных материалов.")} />)}{tx(courseId && <p className="muted" style={{ fontSize: 12 }}>{tx(courses.find(course => course.id === courseId)?.description)}</p>)}<label className="field">{t("Пройти до")}<input className="input" type="date" min={businessToday()} value={dueOn} onChange={e=>setDueOn(e.target.value)} disabled={busy}/></label><div className="support-note"><Icon name="bell" size={17} /><p>{t("Сотрудник получит курс и уведомление.")}</p></div>{tx(error && <p className="support-inline-error" role="alert">{tx(error)}</p>)}<div className="support-reader-actions"><button className="btn btn-secondary" type="button" disabled={busy} onClick={onClose}>{t("Отмена")}</button><button className="btn btn-primary" disabled={busy || !courseId}>{tx(busy ? 'Назначаем…' : 'Назначить курс')}<Icon name="graduation" size={16} /></button></div></form></Modal>;
}

export default function Team() {
  const { api, profile, refreshKey } = usePortal();
  const allowed = profile.role === 'manager' || profile.role === 'hr_admin';
  const [employees, setEmployees] = useState<EmployeeProfile[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  const [search, setSearch] = useState('');
  const [details, setDetails] = useState<string | null>(null);
  const [assign, setAssign] = useState<EmployeeProfile | null>(null);
  const [params, setParams] = useSearchParams();
  const [invitations, setInvitations] = useState(false);
  const tab = params.get('tab') === 'learning' ? 'learning' : 'people';
  const learningEmployee = params.get('employee') || undefined;
  function showLearning(employeeId?: string) {
    const next = new URLSearchParams(params); next.set('tab', 'learning');
    if (employeeId) next.set('employee', employeeId); else next.delete('employee');
    setParams(next);
  }
  useEffect(() => {
    if (!allowed) { setLoading(false); return; }
    let active = true; setLoading(true); setError(null);
    Promise.all([api.getTeam(), api.getCourses()]).then(([people, catalog]) => { if (active) { setEmployees(people); setCourses(catalog); } }).catch(err => { if (active) setError(err); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api, allowed, refreshKey, retry]);
  const visible = employees.filter(employee => `${employee.full_name} ${employee.job_title} ${employee.department} ${employee.employee_code}`.toLocaleLowerCase('ru').includes(search.toLocaleLowerCase('ru')));
  const paging = useListPage(visible, search);
  return <div className="support-page people-page"><PageHeader actions={profile.role === 'hr_admin' ? <button className="btn btn-primary" onClick={() => setInvitations(true)}><Icon name="plus" size={17} />{t("Пригласить сотрудника")}</button> : undefined} title={profile.role === 'hr_admin' ? 'Сотрудники' : 'Моя команда'} description={loading ? undefined : `${employees.length} ${t("сотрудников")}`} />
    {!allowed ? <EmptyState title={t("Раздел доступен руководителям и HR")} description={t("В вашем личном кабинете доступны собственный профиль, заявки и обучение.")} /> : tab === 'learning' ? <TeamLearning employeeId={learningEmployee} onResetEmployee={() => showLearning()} /> : loading ? <LoadingState /> : error ? <ErrorState error={error} retry={() => setRetry(value => value + 1)} /> : <>
      <div className="support-toolbar list-anchor" ref={paging.anchor}><h2 style={{ margin: 0 }}>{t("Сотрудники ")}<span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>· {tx(visible.length)}</span></h2><label className="support-search"><Icon name="search" size={16} /><input className="input" value={search} onChange={event => setSearch(event.target.value)} placeholder={t("Имя, отдел или должность")} aria-label={t("Поиск сотрудника")} /></label></div>
      {visible.length ? <div className="people-list">{paging.items.map(employee => <article className="people-row" key={employee.id}><button className="people-person" onClick={() => setDetails(employee.id)} aria-label={`${t('Профиль')}: ${employee.full_name}`}><Avatar name={employee.full_name} size={40} /><span><strong>{employee.full_name}</strong><small>{tx(employee.department)}{employee.job_title ? ` · ${tx(employee.job_title)}` : ''}</small></span><Icon name="chevron-right" size={17} /></button><div className="people-actions"><button className="btn btn-ghost" onClick={() => showLearning(employee.id)}>{t('Обучение')}</button><button className="btn btn-secondary" onClick={() => setAssign(employee)}>{t('Назначить курс')}</button></div></article>)}</div> : <EmptyState title={search ? 'Сотрудники не найдены' : 'В вашей команде пока нет сотрудников'} description={search ? 'Попробуйте другое имя, должность или подразделение.' : 'Состав команды определяется кадровой системой.'} />}
      <ListPager {...paging} />
    </>}
    {tx(profile.role === 'hr_admin' && invitations && <Invitations employees={employees} onClose={() => setInvitations(false)} />)}
    {tx(allowed && details && <EmployeeDetails key={details} id={details} onClose={() => setDetails(null)} onAssign={() => { const person = employees.find(e => e.id === details); if (person) { setDetails(null); setAssign(person); } }} onLearning={() => { showLearning(details); setDetails(null); }} />)}
    {tx(allowed && assign && <AssignCourse key={assign.id} employee={assign} courses={courses} onClose={() => setAssign(null)} />)}
  </div>;
}
