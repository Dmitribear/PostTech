import { useEffect, useState, type FormEvent } from 'react';
import { usePortal } from '../context';
import { Avatar, EmptyState, ErrorState, Icon, LoadingState, Modal, PageHeader } from '../components/ui';
import { errorMessage } from '../lib/api';
import { roleLabels } from '../lib/format';
import type { Course, EmployeeProfile } from '../lib/types';
import { ProfileFields } from './Profile';
import './support.css';

function EmployeeDetails({ id, onClose }: { id: string; onClose: () => void }) {
  const { api } = usePortal();
  const [employee, setEmployee] = useState<EmployeeProfile | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true; setEmployee(null); setError(null);
    api.getEmployee(id).then(value => { if (active) setEmployee(value); }).catch(err => { if (active) setError(err); });
    return () => { active = false; };
  }, [api, id, retry]);
  return <Modal title="Профиль сотрудника" onClose={onClose} wide>{error ? <ErrorState error={error} retry={() => setRetry(value => value + 1)} /> : !employee ? <LoadingState /> : <><div className="support-team-detail-heading"><Avatar name={employee.full_name} size={52} /><div><h3>{employee.full_name}</h3><p>{employee.job_title} · {employee.department}</p></div></div><ProfileFields profile={employee} /><div className="support-note" style={{ marginTop: 20 }}><Icon name="plane" size={18} /><p>Доступно дней отпуска: <strong>{employee.vacation_days_remaining}</strong>. Кадровые сведения доступны только для чтения.</p></div></>}</Modal>;
}

function AssignCourse({ employee, courses, onClose }: { employee: EmployeeProfile; courses: Course[]; onClose: () => void }) {
  const { api, notify, refresh } = usePortal();
  const [courseId, setCourseId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!courseId || busy) return;
    setBusy(true); setError('');
    try {
      await api.assignCourse(employee.id, courseId);
      refresh(); notify(`Курс назначен: ${employee.full_name}.`); onClose();
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  return <Modal title="Назначить обучение" onClose={() => { if (!busy) onClose(); }}><form className="support-assign-form" onSubmit={submit}><div className="support-team-detail-heading"><Avatar name={employee.full_name} size={42} /><div><h3>{employee.full_name}</h3><p>{employee.job_title}</p></div></div>{courses.length ? <label className="field"><span className="field-label">Курс Jana Academy</span><select className="input" value={courseId} onChange={event => setCourseId(event.target.value)} disabled={busy} required><option value="">Выберите курс</option>{courses.map(course => <option key={course.id} value={course.id}>{course.title} · {course.duration_minutes} мин</option>)}</select></label> : <EmptyState title="Доступных курсов пока нет" description="Курсы появятся после публикации учебных материалов." />}{courseId && <p className="muted" style={{ fontSize: 12 }}>{courses.find(course => course.id === courseId)?.description}</p>}<div className="support-note"><Icon name="bell" size={17} /><p>После назначения курс появится у сотрудника в Jana Academy. Система отправит уведомление о новом обучении.</p></div>{error && <p className="support-inline-error" role="alert">{error}</p>}<div className="support-reader-actions"><button className="btn btn-secondary" type="button" disabled={busy} onClick={onClose}>Отмена</button><button className="btn btn-primary" disabled={busy || !courseId}>{busy ? 'Назначаем…' : 'Назначить курс'}<Icon name="graduation" size={16} /></button></div></form></Modal>;
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
  useEffect(() => {
    if (!allowed) { setLoading(false); return; }
    let active = true; setLoading(true); setError(null);
    Promise.all([api.getTeam(), api.getCourses()]).then(([people, catalog]) => { if (active) { setEmployees(people); setCourses(catalog); } }).catch(err => { if (active) setError(err); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api, allowed, refreshKey, retry]);
  const visible = employees.filter(employee => `${employee.full_name} ${employee.job_title} ${employee.department} ${employee.employee_code}`.toLocaleLowerCase('ru').includes(search.toLocaleLowerCase('ru')));
  return <div className="support-page"><PageHeader title={profile.role === 'hr_admin' ? 'Сотрудники компании' : 'Моя команда'} description="Профили сотрудников и назначение обучения" eyebrow={profile.role === 'hr_admin' ? 'HR-пространство' : 'Пространство руководителя'} />
    {!allowed ? <EmptyState title="Раздел доступен руководителям и HR" description="В вашем личном кабинете доступны собственный профиль, заявки и обучение." /> : loading ? <LoadingState /> : error ? <ErrorState error={error} retry={() => setRetry(value => value + 1)} /> : <>
      <div className="support-metrics"><div className="support-metric"><span><Icon name="users" /></span><div><strong>{employees.length}</strong><small>{profile.role === 'hr_admin' ? 'Сотрудников компании' : 'Сотрудников в команде'}</small></div></div><div className="support-metric"><span><Icon name="building" /></span><div><strong>{new Set(employees.map(employee => employee.department)).size}</strong><small>Подразделений</small></div></div><div className="support-metric"><span><Icon name="graduation" /></span><div><strong>{courses.length}</strong><small>Курсов для назначения</small></div></div></div>
      <div className="support-toolbar"><h2 style={{ margin: 0 }}>Сотрудники <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>· {visible.length}</span></h2><label className="support-search"><Icon name="search" size={16} /><input className="input" value={search} onChange={event => setSearch(event.target.value)} placeholder="Имя, отдел или должность" aria-label="Поиск сотрудника" /></label></div>
      {visible.length ? <div className="support-team-grid">{visible.map(employee => <article className="card support-team-member" key={employee.id}><div className="support-team-person"><Avatar name={employee.full_name} size={43} /><div><h3>{employee.full_name}</h3><p>{employee.job_title}</p></div></div><span className="support-profile-role">{roleLabels[employee.role]}</span><div className="support-team-line"><Icon name="building" size={14} />{employee.department}</div><div className="support-team-line"><Icon name="mail" size={14} />{employee.email}</div><div className="support-team-line"><Icon name="user" size={14} />{employee.employee_code}</div><div className="support-team-actions"><button className="btn btn-secondary" onClick={() => setDetails(employee.id)}>Профиль<Icon name="arrow-right" size={13} /></button><button className="btn btn-primary" onClick={() => setAssign(employee)}><Icon name="graduation" size={14} />Назначить курс</button></div></article>)}</div> : <EmptyState title={search ? 'Сотрудники не найдены' : 'В вашей команде пока нет сотрудников'} description={search ? 'Попробуйте другое имя, должность или подразделение.' : 'Состав команды определяется кадровой системой.'} />}
      <div className="support-note"><Icon name="shield" size={18} /><p>{profile.role === 'hr_admin' ? 'Вам доступны профили сотрудников компании в рамках роли HR.' : 'Вам доступны только сотрудники, для которых вы назначены руководителем.'} Для изменения кадровых данных обратитесь в HR.</p></div>
    </>}
    {allowed && details && <EmployeeDetails key={details} id={details} onClose={() => setDetails(null)} />}
    {allowed && assign && <AssignCourse key={assign.id} employee={assign} courses={courses} onClose={() => setAssign(null)} />}
  </div>;
}
