import { usePortal } from '@/entities/session';
import { Deadline } from '@/features/deadline';
import type { TeamCourseAssignment } from '@/shared/api/contracts';
import { formatDate } from '@/shared/lib/format';
import { t, tx } from '@/shared/lib/i18n';
import { watchVisible } from '@/shared/lib/live-refresh';
import '@/shared/styles/support.css';
import { Avatar, EmptyState, ErrorState, Icon, LoadingState, StatusBadge } from '@/shared/ui/index';
import { ListPager, useListPage } from '@/shared/ui/molecules/ListPager';
import { MyTracks } from '@/features/learning-track';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

export function TeamLearning({
  employeeId,
  onResetEmployee,
  courseId,
  onResetCourse,
}: {
  employeeId?: string;
  onResetEmployee?: () => void;
  courseId?: string;
  onResetCourse?: () => void;
}) {
  const { api, profile, refreshKey } = usePortal();
  const allowed = ['manager', 'director'].includes(profile.role) || profile.role === 'hr_admin';
  const [rows, setRows] = useState<TeamCourseAssignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  useEffect(() => {
    if (!allowed) return;
    setLoading(true);
    setError(null);
    let loaded = false;
    return watchVisible(async (signal) => {
      try {
        const value = await api.getTeamCourses({
          ...(employeeId ? { employee_id: employeeId } : {}),
          ...(courseId ? { course_id: courseId } : {}),
        });
        if (!signal.aborted) {
          setRows(value);
          setError(null);
          loaded = true;
        }
      } catch (err) {
        if (!signal.aborted && !loaded) setError(err);
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    });
  }, [api, allowed, employeeId, courseId, refreshKey, retry]);
  const visible = rows.filter(
    (row) =>
      (status === 'all' ||
        (status === 'retry'
          ? row.status !== 'completed' && row.score_percent != null
          : row.status === status)) &&
      `${row.employee.full_name} ${row.employee.department} ${row.course?.title || ''}`
        .toLocaleLowerCase('ru')
        .includes(query.toLocaleLowerCase('ru')),
  );
  const paging = useListPage(visible, `${status}|${query}|${employeeId}|${courseId}`);
  if (!allowed) return <EmptyState title={t('Обучение команды доступно руководителю и HR')} />;
  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} retry={() => setRetry((value) => value + 1)} />;

  const completed = rows.filter((row) => row.status === 'completed').length;
  const needRetry = rows.filter(
    (row) => row.status !== 'completed' && row.score_percent != null,
  ).length;
  return (
    <section className="academy-team-view">
      {tx(
        courseId && (
          <div className="support-note">
            <Icon name="book" size={16} />
            <p>
              {t('Показаны назначения курса: ')}
              <strong>{tx(rows[0]?.course?.title || 'выбранный курс')}</strong>.
            </p>
            {tx(
              onResetCourse && (
                <button className="btn btn-ghost" onClick={onResetCourse}>
                  {t('Все курсы')}
                </button>
              ),
            )}
          </div>
        ),
      )}
      {employeeId && <MyTracks employeeId={employeeId} />}
      <div className="support-toolbar">
        <div>
          <h2>{t('Обучение команды')}</h2>
          <p className="muted">
            {tx(
              employeeId
                ? 'Курсы сотрудника'
                : profile.role === 'hr_admin'
                  ? 'Все сотрудники'
                  : 'Ваша команда',
            )}
          </p>
        </div>
        {tx(
          employeeId && onResetEmployee ? (
            <button className="btn btn-secondary" onClick={onResetEmployee}>
              {t('Все сотрудники')}
            </button>
          ) : (
            <Link className="btn btn-secondary" to="/team">
              <Icon name="users" size={15} />
              {t('Назначить обучение')}
            </Link>
          ),
        )}
      </div>
      <div className="support-metrics">
        <div className="support-metric">
          <span>
            <Icon name="book" />
          </span>
          <div>
            <strong>{tx(rows.length)}</strong>
            <small>{t('Назначений')}</small>
          </div>
        </div>
        <div className="support-metric">
          <span>
            <Icon name="check-circle" />
          </span>
          <div>
            <strong>{tx(completed)}</strong>
            <small>{t('Завершено')}</small>
          </div>
        </div>
        <div className="support-metric">
          <span>
            <Icon name="refresh" />
          </span>
          <div>
            <strong>{tx(needRetry)}</strong>
            <small>{t('Нужен повтор')}</small>
          </div>
        </div>
      </div>
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
        <label className="academy-filter">
          <span>{t('Статус')}</span>
          <select
            className="input"
            aria-label={t('Статус обучения команды')}
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="all">{t('Все назначения')}</option>
            <option value="not_started">{t('Не начаты')}</option>
            <option value="in_progress">{t('В процессе')}</option>
            <option value="completed">{t('Завершены')}</option>
            <option value="retry">{t('Нужен повтор')}</option>
          </select>
        </label>
        <label className="support-search">
          <Icon name="search" size={15} />
          <input
            className="input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label={t('Поиск обучения команды')}
            placeholder={t('Сотрудник, отдел или курс')}
          />
        </label>
      </div>
      {visible.length ? (
        <div className="card academy-team-list">
          <div className="academy-team-head">
            <span>{t('Сотрудник / курс')}</span>
            <span>{t('Прогресс')}</span>
            <span>{t('Результат')}</span>
          </div>
          {paging.items.map((row) => (
            <article className="academy-team-row" key={row.id}>
              <div className="academy-team-person">
                <Avatar name={row.employee.full_name} size={34} />
                <div>
                  <strong>{row.employee.full_name}</strong>
                  <small>{tx(row.employee.department)}</small>
                  <Link
                    to={`/academy?tab=team&course=${encodeURIComponent(row.course_id)}&employee=${encodeURIComponent(row.employee_id)}`}
                  >
                    {tx(row.course?.title || 'Курс недоступен')}
                  </Link>
                </div>
              </div>
              <div className="academy-team-progress">
                <div
                  className="support-progress"
                  role="progressbar"
                  aria-label={`Прогресс ${row.employee.full_name}: ${row.course?.title || 'курс'}`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={row.progress_percent}
                >
                  <span style={{ width: `${row.progress_percent}%` }} />
                </div>
                <div className="support-progress-label">
                  <strong>{tx(row.progress_percent)}%</strong>
                  <StatusBadge status={row.status} />
                </div>
              </div>
              <div className="academy-team-score">
                <span className="academy-score-label">
                  {t(
                    row.course?.course_type === 'external'
                      ? 'Отмечено сотрудником'
                      : 'Результат теста',
                  )}
                </span>
                <strong>
                  {row.course?.course_type === 'external'
                    ? row.course.provider
                    : tx(row.score_percent == null ? '—' : `${row.score_percent}%`)}
                </strong>
                <Deadline id={row.id} due={row.due_on} status={row.status} editable />
                <details className="academy-assignment-details">
                  <summary>{t('Подробности')}</summary>
                  <dl>
                    <div>
                      <dt>{t('Назначен')}</dt>
                      <dd>{formatDate(row.assigned_at)}</dd>
                    </div>
                    {row.course?.course_type !== 'external' && (
                      <div>
                        <dt>{t('Попытки')}</dt>
                        <dd>{row.attempt_count ?? '—'}</dd>
                      </div>
                    )}
                    {row.course?.course_type !== 'external' &&
                      row.course?.passing_score != null && (
                        <div>
                          <dt>{t('Для зачёта')}</dt>
                          <dd>{row.course.passing_score}%</dd>
                        </div>
                      )}
                    {row.last_attempt_at && (
                      <div>
                        <dt>{t('Последняя попытка')}</dt>
                        <dd>{formatDate(row.last_attempt_at)}</dd>
                      </div>
                    )}
                    {row.material_completed_at && (
                      <div>
                        <dt>{t('Материал изучен')}</dt>
                        <dd>{formatDate(row.material_completed_at)}</dd>
                      </div>
                    )}
                  </dl>
                </details>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState
          title={rows.length ? 'Назначения не найдены' : 'Назначенных курсов пока нет'}
          description={
            rows.length
              ? 'Измените статус или поисковый запрос.'
              : 'Назначьте курс сотруднику из раздела команды.'
          }
        />
      )}
      <ListPager {...paging} />
    </section>
  );
}
