import { ProfileFields } from '@/entities/employee';
import { usePortal } from '@/entities/session';
import { AssignRole } from '@/features/assign-role';
import Invitations from '@/features/invite-employee';
import { errorMessage } from '@/shared/api/api';
import type { Course, EmployeeProfile } from '@/shared/api/contracts';
import { businessToday } from '@/shared/lib/business-date';
import { t, tx } from '@/shared/lib/i18n';
import '@/shared/styles/support.css';
import {
  Avatar,
  EmptyState,
  ErrorState,
  Icon,
  LoadingState,
  Modal,
  PageHeader,
} from '@/shared/ui/index';
import { ListPager, useListPage } from '@/shared/ui/molecules/ListPager';
import { TeamLearning } from '@/widgets/team-learning';
import { useEffect, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

function EmployeeDetails({
  id,
  onClose,
  onAssign,
  onLearning,
}: {
  id: string;
  onClose: () => void;
  onAssign: () => void;
  onLearning: () => void;
}) {
  const { api } = usePortal();
  const [employee, setEmployee] = useState<EmployeeProfile | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setEmployee(null);
    setError(null);
    api
      .getEmployee(id)
      .then((value) => {
        if (active) setEmployee(value);
      })
      .catch((err) => {
        if (active) setError(err);
      });
    return () => {
      active = false;
    };
  }, [api, id, retry]);
  return (
    <Modal title={t('Профиль сотрудника')} onClose={onClose} wide>
      {error ? (
        <ErrorState error={error} retry={() => setRetry((value) => value + 1)} />
      ) : !employee ? (
        <LoadingState />
      ) : (
        <>
          <div className="support-team-detail-heading">
            <Avatar name={employee.full_name} size={52} />
            <div>
              <h3>{employee.full_name}</h3>
              <p>
                {tx(employee.job_title)} · {tx(employee.department)}
              </p>
            </div>
          </div>
          <div className="employee-detail-actions">
            <button className="btn btn-primary" onClick={onAssign}>
              {t('Назначить курс')}
            </button>
            <button className="btn btn-secondary" onClick={onLearning}>
              {t('Обучение')}
            </button>
          </div>
          <ProfileFields profile={employee} />
          <AssignRole
            key={employee.id + employee.role}
            employee={employee}
            onSaved={() => setRetry((value) => value + 1)}
          />
          <div className="support-note" style={{ marginTop: 20 }}>
            <Icon name="plane" size={18} />
            <p>
              <strong>
                {tx(employee.vacation_days_remaining)}
                {t(' дней')}
              </strong>
              {t(' отпуска · данные обновляет HR.')}
            </p>
          </div>
        </>
      )}
    </Modal>
  );
}

function AssignCourse({
  employee,
  courses,
  onClose,
}: {
  employee: EmployeeProfile;
  courses: Course[];
  onClose: () => void;
}) {
  const { api, notify, refresh } = usePortal();
  const [courseId, setCourseId] = useState('');
  const [dueOn, setDueOn] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!courseId || busy) return;
    setBusy(true);
    setError('');
    try {
      await api.assignCourse(employee.id, courseId, dueOn);
      refresh();
      notify(`Курс назначен: ${employee.full_name}.`);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={t('Назначить обучение')}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="support-assign-form" onSubmit={submit}>
        <div className="support-team-detail-heading">
          <Avatar name={employee.full_name} size={42} />
          <div>
            <h3>{employee.full_name}</h3>
            <p>{tx(employee.job_title)}</p>
          </div>
        </div>
        {tx(
          courses.length ? (
            <fieldset className="assign-course-options" disabled={busy}>
              <legend className="field-label">{t('Курс Jana Academy')}</legend>
              {courses.length <= 6 ? (
                courses.map((course) => (
                  <label key={course.id} className="support-option">
                    <input
                      type="radio"
                      name="assigned-course"
                      value={course.id}
                      checked={courseId === course.id}
                      onChange={() => setCourseId(course.id)}
                      required
                    />
                    <span>
                      {course.title}
                      <small>
                        {course.duration_minutes}
                        {t(' мин')}
                      </small>
                    </span>
                  </label>
                ))
              ) : (
                <select
                  className="input"
                  aria-label={t('Курс Jana Academy')}
                  value={courseId}
                  onChange={(event) => setCourseId(event.target.value)}
                  required
                >
                  <option value="">{t('Выберите курс')}</option>
                  {courses.map((course) => (
                    <option key={course.id} value={course.id}>
                      {course.title} · {course.duration_minutes}
                      {t(' мин')}
                    </option>
                  ))}
                </select>
              )}
            </fieldset>
          ) : (
            <EmptyState
              title={t('Доступных курсов пока нет')}
              description={t('Курсы появятся после публикации учебных материалов.')}
            />
          ),
        )}
        {tx(
          courseId && (
            <p className="muted" style={{ fontSize: 12 }}>
              {tx(courses.find((course) => course.id === courseId)?.description)}
            </p>
          ),
        )}
        <label className="field">
          {t('Пройти до')}
          <input
            className="input"
            type="date"
            min={businessToday()}
            value={dueOn}
            onChange={(e) => setDueOn(e.target.value)}
            disabled={busy}
          />
        </label>
        <div className="support-note">
          <Icon name="bell" size={17} />
          <p>{t('Сотрудник получит курс и уведомление.')}</p>
        </div>
        {tx(
          error && (
            <p className="support-inline-error" role="alert">
              {tx(error)}
            </p>
          ),
        )}
        <div className="support-reader-actions">
          <button className="btn btn-secondary" type="button" disabled={busy} onClick={onClose}>
            {t('Отмена')}
          </button>
          <button className="btn btn-primary" disabled={busy || !courseId}>
            {tx(busy ? 'Назначаем…' : 'Назначить курс')}
            <Icon name="graduation" size={16} />
          </button>
        </div>
      </form>
    </Modal>
  );
}

export default function Team() {
  const { api, profile, refreshKey } = usePortal();
  const allowed = ['manager', 'director'].includes(profile.role) || profile.role === 'hr_admin';
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
    const next = new URLSearchParams(params);
    next.set('tab', 'learning');
    if (employeeId) next.set('employee', employeeId);
    else next.delete('employee');
    setParams(next);
  }
  useEffect(() => {
    if (!allowed) {
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([api.getTeam(), api.getCourses()])
      .then(([people, catalog]) => {
        if (active) {
          setEmployees(people);
          setCourses(catalog);
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
  }, [api, allowed, refreshKey, retry]);
  const visible = employees.filter((employee) =>
    `${employee.full_name} ${employee.job_title} ${employee.department} ${employee.employee_code}`
      .toLocaleLowerCase('ru')
      .includes(search.toLocaleLowerCase('ru')),
  );
  const paging = useListPage(visible, search);
  return (
    <div className="support-page people-page">
      <PageHeader
        actions={
          profile.role === 'hr_admin' ? (
            <button className="btn btn-primary" onClick={() => setInvitations(true)}>
              <Icon name="plus" size={17} />
              {t('Пригласить сотрудника')}
            </button>
          ) : undefined
        }
        title={profile.role === 'hr_admin' ? 'Сотрудники' : 'Моя команда'}
        description={loading ? undefined : `${employees.length} ${t('сотрудников')}`}
      />
      {!allowed ? (
        <EmptyState
          title={t('Раздел доступен руководителям и HR')}
          description={t(
            'В вашем личном кабинете доступны собственный профиль, заявки и обучение.',
          )}
        />
      ) : tab === 'learning' ? (
        <TeamLearning employeeId={learningEmployee} onResetEmployee={() => showLearning()} />
      ) : loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} retry={() => setRetry((value) => value + 1)} />
      ) : (
        <>
          {profile.role === 'hr_admin' && (
            <div className="hf-actions">
              <Link className="text-link" to="/hr-workflow?tab=import">
                {t('Импорт сотрудников')}
              </Link>
              <Link className="text-link" to="/hr-workflow?tab=tracks">
                {t('Планы адаптации')}
              </Link>
            </div>
          )}
          <div className="support-toolbar list-anchor" ref={paging.anchor}>
            <h2 style={{ margin: 0 }}>
              {t('Сотрудники ')}
              <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>
                · {tx(visible.length)}
              </span>
            </h2>
            <label className="support-search">
              <Icon name="search" size={16} />
              <input
                className="input"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={t('Имя, отдел или должность')}
                aria-label={t('Поиск сотрудника')}
              />
            </label>
          </div>
          {visible.length ? (
            <div className="people-list">
              {paging.items.map((employee) => (
                <article className="people-row" key={employee.id}>
                  <button
                    className="people-person"
                    onClick={() => setDetails(employee.id)}
                    aria-label={`${t('Профиль')}: ${employee.full_name}`}
                  >
                    <Avatar name={employee.full_name} size={40} />
                    <span>
                      <strong>{employee.full_name}</strong>
                      <small>
                        {tx(employee.department)}
                        {employee.job_title ? ` · ${tx(employee.job_title)}` : ''}
                      </small>
                    </span>
                    <Icon name="chevron-right" size={17} />
                  </button>
                  <div className="people-actions">
                    <button className="btn btn-ghost" onClick={() => showLearning(employee.id)}>
                      {t('Обучение')}
                    </button>
                    <button className="btn btn-secondary" onClick={() => setAssign(employee)}>
                      {t('Назначить курс')}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState
              title={search ? 'Сотрудники не найдены' : 'В вашей команде пока нет сотрудников'}
              description={
                search
                  ? 'Попробуйте другое имя, должность или подразделение.'
                  : 'Состав команды определяется кадровой системой.'
              }
            />
          )}
          <ListPager {...paging} />
        </>
      )}
      {tx(
        profile.role === 'hr_admin' && invitations && (
          <Invitations employees={employees} onClose={() => setInvitations(false)} />
        ),
      )}
      {tx(
        allowed && details && (
          <EmployeeDetails
            key={details}
            id={details}
            onClose={() => setDetails(null)}
            onAssign={() => {
              const person = employees.find((e) => e.id === details);
              if (person) {
                setDetails(null);
                setAssign(person);
              }
            }}
            onLearning={() => {
              showLearning(details);
              setDetails(null);
            }}
          />
        ),
      )}
      {tx(
        allowed && assign && (
          <AssignCourse
            key={assign.id}
            employee={assign}
            courses={courses}
            onClose={() => setAssign(null)}
          />
        ),
      )}
    </div>
  );
}
