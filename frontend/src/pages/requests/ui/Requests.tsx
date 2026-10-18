import {
  approverNames,
  businessDate,
  dateKey,
  dayCount,
  dayWord,
  formatDay,
  leaveConflicts,
  loadRequests,
  money,
  parseDay,
  requestLabel,
  requestNumber,
} from '@/entities/hr-request';
import { usePortal } from '@/entities/session';
import { LeaveBalance } from '@/features/leave-balance';
import { LeaveConflictNotice } from '@/features/leave-conflict';
import { ApiError } from '@/shared/api/api';
import type { RequestRouting } from '@/shared/api/contracts';
import { getLocale, t, tx } from '@/shared/lib/i18n';
import { watchVisible } from '@/shared/lib/live-refresh';
import '@/shared/styles/requests.css';
import {
  Avatar,
  EmptyState,
  ErrorState,
  Icon,
  LoadingState,
  Modal,
  PageHeader,
  StatusBadge,
} from '@/shared/ui/index';
import { LeaveCalendarDownload } from '@/features/leave-calendar-download';
import { RequestFulfillment, RequestState } from '@/widgets/hr-workflow';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';

type Api = ReturnType<typeof usePortal>['api'];
export type RequestRecord = Awaited<ReturnType<Api['getRequest']>>;
type RequestEvent = Awaited<ReturnType<Api['getRequestHistory']>>[number];
type CreatePayload = Parameters<Api['createRequest']>[0];
type Employee = ReturnType<typeof usePortal>['profile'];

function pendingRequestKeys(storageKey: string): Map<string, string> {
  try {
    const entries: unknown = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
    if (!Array.isArray(entries)) return new Map();
    return new Map(
      entries.filter(
        (entry): entry is [string, string] =>
          Array.isArray(entry) &&
          entry.length === 2 &&
          typeof entry[0] === 'string' &&
          typeof entry[1] === 'string' &&
          /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(entry[1]),
      ),
    );
  } catch {
    return new Map();
  }
}

function storePendingRequestKeys(storageKey: string, keys: Map<string, string>) {
  try {
    if (keys.size) sessionStorage.setItem(storageKey, JSON.stringify([...keys]));
    else sessionStorage.removeItem(storageKey);
  } catch {
    /* In-memory retry protection remains available when browser storage is disabled. */
  }
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString(getLocale() === 'kk' ? 'kk-KZ' : 'ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Qyzylorda',
  });
}

export default function Requests() {
  const location = useLocation();
  const tail = location.pathname.replace(/\/$/, '').split('/').pop();
  if (tail === 'new') return <RequestForm />;
  if (tail && tail !== 'requests') return <RequestDetails id={tail} key={tail} />;
  return <RequestList />;
}

function RequestList() {
  const { api, profile, refreshKey } = usePortal();
  const [params, setParams] = useSearchParams();
  const [records, setRecords] = useState<RequestRecord[]>([]);
  const [team, setTeam] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reload, setReload] = useState(0);
  const [search, setSearch] = useState(params.get('q') || '');
  const [kind, setKind] = useState('all');
  const [page, setPage] = useState(1);
  const isReviewer = ['manager', 'director'].includes(profile.role) || profile.role === 'hr_admin';
  const scope =
    ['review', 'team'].includes(params.get('scope') || '') && isReviewer ? 'review' : 'mine';
  const statusParam = params.get('status') || (scope === 'review' ? 'pending' : 'all');
  const status = ['pending', 'approved', 'rejected', 'cancelled'].includes(statusParam)
    ? statusParam
    : 'all';

  useEffect(() => {
    setLoading(true);
    setError(null);
    let loaded = false;
    return watchVisible(async (signal) => {
      try {
        const data = await loadRequests(api, { scope });
        if (!signal.aborted) {
          setRecords(data);
          setError(null);
          loaded = true;
        }
      } catch (reason) {
        if (!signal.aborted && !loaded) setError(reason);
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    });
  }, [api, profile.id, scope, refreshKey, reload]);

  useEffect(() => {
    let active = true;
    if (isReviewer)
      api
        .getTeam()
        .then((data) => {
          if (active) setTeam(data);
        })
        .catch(() => {
          /* Employee identifiers remain available. */
        });
    return () => {
      active = false;
    };
  }, [api, isReviewer]);

  useEffect(() => {
    setPage(1);
  }, [scope, status, kind, search]);
  useEffect(() => {
    setSearch(params.get('q') || '');
  }, [params.get('q')]);
  const people = useMemo(
    () => new Map([profile, ...team].map((person) => [person.id, person])),
    [profile, team],
  );
  const scoped = useMemo(
    () =>
      scope === 'review'
        ? records.filter((request) => request.employee_id !== profile.id)
        : records,
    [records, scope, profile.id],
  );
  const filtered = useMemo(
    () =>
      scoped.filter((request) => {
        const query = search.trim().toLocaleLowerCase(getLocale() === 'kk' ? 'kk-KZ' : 'ru-RU');
        const matchesQuery =
          !query ||
          `${requestNumber(request.id)} ${request.id} ${requestLabel(request)} ${request.comment} ${people.get(request.employee_id)?.full_name || ''}`
            .toLocaleLowerCase(getLocale() === 'kk' ? 'kk-KZ' : 'ru-RU')
            .includes(query);
        return (
          matchesQuery &&
          (status === 'all' || request.status === status) &&
          (kind === 'all' || request.request_type === kind)
        );
      }),
    [scoped, search, status, kind, people],
  );
  const pages = Math.max(1, Math.ceil(filtered.length / 10));
  const currentPage = Math.min(page, pages);
  const visible = filtered.slice((currentPage - 1) * 10, currentPage * 10);

  function changeFilter(key: string, value: string) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      if (key === 'scope') {
        if (value === 'mine') {
          next.delete(key);
          next.delete('status');
        } else {
          next.set(key, value);
          next.set('status', 'pending');
        }
      } else next.set(key, value);
      return next;
    });
  }

  function changeSearch(value: string) {
    setSearch(value);
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        if (value) next.set('q', value);
        else next.delete('q');
        return next;
      },
      { replace: true },
    );
  }

  return (
    <div className={`req-page ${scope === 'review' ? 'review-inbox' : 'personal-inbox'}`}>
      <PageHeader
        title={scope === 'review' ? 'На согласование' : 'Мои заявки'}
        actions={
          scope === 'mine' ? (
            <Link className="btn btn-primary" to="/requests/new">
              <Icon name="plus" size={18} />
              {t(' Создать заявку')}
            </Link>
          ) : profile.role === 'hr_admin' ? (
            <Link className="btn btn-secondary" to="/hr-workflow">
              {t('Оформление HR')}
            </Link>
          ) : undefined
        }
      />
      <section className="card req-list-card">
        <div className="req-list-heading">
          <h2>{t('Заявки')}</h2>
          <span className="muted">{tx(loading ? 'Загрузка…' : `${filtered.length} заявок`)}</span>
        </div>
        <div className="req-filters">
          <label className="req-search">
            <Icon name="search" size={18} />
            <input
              value={search}
              onChange={(event) => changeSearch(event.target.value)}
              placeholder={t('Найти заявку…')}
              aria-label={t('Поиск заявок')}
            />
            {tx(
              search && (
                <button onClick={() => changeSearch('')} aria-label={t('Очистить поиск')}>
                  <Icon name="x" size={15} />
                </button>
              ),
            )}
          </label>
          <select
            className="input req-filter-select"
            aria-label={t('Тип заявки')}
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          >
            <option value="all">{t('Все типы')}</option>
            <option value="leave">{t('Отпуск')}</option>
            <option value="advance">{t('Аванс')}</option>
          </select>
          <select
            className="input req-filter-select"
            aria-label={t('Статус заявки')}
            value={status}
            onChange={(event) => changeFilter('status', event.target.value)}
          >
            <option value="all">{t('Все статусы')}</option>
            <option value="pending">{t('На согласовании')}</option>
            <option value="approved">{t('Согласовано')}</option>
            <option value="rejected">{t('Отклонено')}</option>
            <option value="cancelled">{t('Отменено')}</option>
          </select>
        </div>
        {loading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} retry={() => setReload((value) => value + 1)} />
        ) : visible.length === 0 ? (
          <EmptyState
            title={
              scoped.length
                ? 'Заявки не найдены'
                : scope === 'review'
                  ? 'Заявок сотрудников пока нет'
                  : 'Здесь появятся ваши заявки'
            }
            description={
              scoped.length
                ? 'Попробуйте изменить фильтры или поисковый запрос.'
                : 'Отпуск или аванс — начните с новой заявки.'
            }
            action={
              !scoped.length && scope === 'mine' ? (
                <Link className="btn btn-primary" to="/requests/new">
                  {t('Создать первую заявку ')}
                  <Icon name="arrow-right" size={16} />
                </Link>
              ) : undefined
            }
          />
        ) : (
          <>
            <div className="req-table-scroll">
              <table className="req-table">
                <thead>
                  <tr>
                    <th>{t('Заявка')}</th>
                    {tx(scope === 'review' && <th>{t('Сотрудник')}</th>)}
                    <th>{t('Период / сумма')}</th>
                    <th>{t('Дата создания')}</th>
                    <th>{t('Статус')}</th>
                    <th>
                      <span className="req-sr-only">{t('Открыть')}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((request) => (
                    <tr key={request.id}>
                      <td>
                        <Link to={`/requests/${request.id}`} className="req-table-title">
                          <span
                            className={`req-type-icon ${request.request_type === 'advance' ? 'req-type-money' : ''}`}
                          >
                            <Icon
                              name={request.request_type === 'leave' ? 'calendar' : 'wallet'}
                              size={18}
                            />
                          </span>
                          <span>
                            <strong>{tx(requestLabel(request))}</strong>
                            <small>{tx(requestNumber(request.id))}</small>
                          </span>
                        </Link>
                      </td>
                      {scope === 'review' && (
                        <td className="req-employee-cell">
                          <div className="req-employee-small">
                            <Avatar
                              name={people.get(request.employee_id)?.full_name || '?'}
                              size={28}
                            />
                            <span>
                              {people.get(request.employee_id)?.full_name ||
                                `Сотрудник ${request.employee_id.slice(0, 8)}`}
                            </span>
                          </div>
                        </td>
                      )}
                      <td data-label={t('Период / сумма')}>
                        {tx(
                          request.request_type === 'leave' ? (
                            <>
                              <span>{tx(formatDay(request.start_date))} —</span>
                              <br />
                              <span>{tx(formatDay(request.end_date))}</span>
                            </>
                          ) : (
                            <strong>{tx(money(request.amount || 0))}</strong>
                          ),
                        )}
                      </td>
                      <td className="muted req-created-cell" data-label={t('Создана')}>
                        {tx(formatDay(request.created_at))}
                      </td>
                      <td className="req-status-cell">
                        <RequestState request={request} />
                        {request.status === 'pending' && (
                          <small className="req-status-context">
                            {scope === 'review' && request.can_review !== false ? (
                              t('Ждёт вашего решения')
                            ) : (
                              <>
                                {t('Согласует')}: {tx(approverNames(request.approvers))}
                              </>
                            )}
                          </small>
                        )}
                      </td>
                      <td>
                        <Link
                          className="req-open-link"
                          to={`/requests/${request.id}`}
                          aria-label={`Открыть ${requestNumber(request.id)}`}
                        >
                          {t(
                            scope === 'review' &&
                              request.status === 'pending' &&
                              request.can_review !== false
                              ? 'Рассмотреть'
                              : 'Открыть',
                          )}
                          <Icon name="chevron-right" size={16} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="req-list-footer">
              <span>
                {t('Показано ')}
                {tx((currentPage - 1) * 10 + 1)}–{tx(Math.min(currentPage * 10, filtered.length))}
                {t(' из ')}
                {tx(filtered.length)}
              </span>
              <div>
                <button
                  className="btn btn-secondary"
                  disabled={currentPage <= 1}
                  onClick={() => setPage(currentPage - 1)}
                  aria-label={t('Предыдущая страница')}
                >
                  <Icon name="chevron-left" size={16} />
                </button>
                <span>
                  {tx(currentPage)} / {tx(pages)}
                </span>
                <button
                  className="btn btn-secondary"
                  disabled={currentPage >= pages}
                  onClick={() => setPage(currentPage + 1)}
                  aria-label={t('Следующая страница')}
                >
                  <Icon name="chevron-right" size={16} />
                </button>
              </div>
            </div>
          </>
        )}
      </section>
      <div className="req-info-strip">
        <Link to="/calendar">
          <Icon name="calendar" size={17} />
          {t(' Отпуска в календаре ')}
          <Icon name="arrow-right" size={15} />
        </Link>
      </div>
    </div>
  );
}

function RequestForm() {
  const { api, profile, refresh, notify } = usePortal();
  const [params] = useSearchParams();
  const location = useLocation();
  const carriedDraft = location.state?.requestDraft;
  const navigate = useNavigate();
  const [availableDays, setAvailableDays] = useState<number | null>(null);
  const [type, setType] = useState<'leave' | 'advance'>(
    params.get('type') === 'advance' ? 'advance' : 'leave',
  );
  const [start, setStart] = useState(
    validDateParam(params.get('start')) || validDateParam(carriedDraft?.start),
  );
  const [end, setEnd] = useState(
    validDateParam(params.get('end')) || validDateParam(carriedDraft?.end),
  );
  const [amount, setAmount] = useState(
    typeof carriedDraft?.amount === 'string' ? carriedDraft.amount : '',
  );
  const [comment, setComment] = useState(
    typeof carriedDraft?.comment === 'string' ? carriedDraft.comment.slice(0, 2000) : '',
  );
  const [step, setStep] = useState(
    params.get('review') === '1' &&
      params.get('type') !== 'advance' &&
      validDateParam(params.get('start')) >= businessDate() &&
      validDateParam(params.get('end')) >= validDateParam(params.get('start'))
      ? 2
      : 1,
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [validation, setValidation] = useState('');
  const [created, setCreated] = useState<RequestRecord | null>(null);
  const [conflictRecords, setConflictRecords] = useState<RequestRecord[]>([]);
  const [routing, setRouting] = useState<RequestRouting | null>(null);
  const [routingError, setRoutingError] = useState<unknown>(null);
  const [routingReload, setRoutingReload] = useState(0);
  const [draftAvailable, setDraftAvailable] = useState(() => {
    try {
      return Boolean(sessionStorage.getItem(`posttech-request-draft:${api.mode}:${profile.id}`));
    } catch {
      return false;
    }
  });
  const idempotencyKeys = useRef(new Map<string, string>());
  const inFlight = useRef(false);
  const days = start && end && end >= start ? dayCount(start, end) : 0;
  const conflicts = type === 'leave' ? leaveConflicts(conflictRecords, profile.id, start, end) : [];
  const payload: CreatePayload =
    type === 'leave'
      ? {
          request_type: 'leave',
          start_date: start,
          end_date: end,
          comment: comment.trim(),
        }
      : {
          request_type: 'advance',
          amount: Number(amount.replace(',', '.')),
          comment: comment.trim(),
        };
  const recoveringSubmission = pendingRequestKeys(
    `posttech-request-pending:${api.mode}:${profile.id}`,
  ).has(JSON.stringify(payload));
  const canSubmit = Boolean(
    recoveringSubmission ||
      (routing?.can_submit &&
        (type !== 'leave' || (availableDays !== null && days <= availableDays))),
  );
  const today = routing?.today || businessDate();

  useEffect(() => {
    let active = true;
    setRouting(null);
    setRoutingError(null);
    api
      .getRequestRouting()
      .then((value) => {
        if (active) setRouting(value);
      })
      .catch((reason) => {
        if (active) setRoutingError(reason);
      });
    return () => {
      active = false;
    };
  }, [api, profile.id, routingReload]);

  function proceed(event: React.FormEvent) {
    event.preventDefault();
    setValidation('');
    if (!canSubmit) {
      setValidation(
        routing?.can_submit
          ? 'Проверьте доступный остаток отпуска.'
          : 'Не удалось назначить согласующего. Обратитесь в HR или обновите маршрут согласования.',
      );
      return;
    }
    if (type === 'leave' && (!start || !end || end < start)) {
      setValidation('Укажите период отпуска. Дата окончания должна быть не раньше даты начала.');
      return;
    }
    if (type === 'leave' && start < today && !recoveringSubmission) {
      setValidation(
        'По правилам прототипа отпуск нельзя оформить задним числом. Выберите сегодняшнюю или будущую дату.',
      );
      return;
    }
    const number = Number(amount.replace(',', '.'));
    if (
      type === 'advance' &&
      (!Number.isFinite(number) ||
        number <= 0 ||
        number > 1000000 ||
        Math.abs(number * 100 - Math.round(number * 100)) > 0.000001)
    ) {
      setValidation('Укажите сумму от 0,01 до 1 000 000 ₸, не более двух знаков после запятой.');
      return;
    }
    setError(null);
    setStep(2);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function saveDraft() {
    try {
      sessionStorage.setItem(
        `posttech-request-draft:${api.mode}:${profile.id}`,
        JSON.stringify({ type, start, end, amount, comment }),
      );
      setDraftAvailable(false);
      notify('Черновик сохранён в текущей вкладке браузера');
    } catch {
      setValidation(
        'Не удалось сохранить черновик в браузере. Вы можете продолжить оформление заявки.',
      );
    }
  }

  function restoreDraft() {
    try {
      const draft = JSON.parse(
        sessionStorage.getItem(`posttech-request-draft:${api.mode}:${profile.id}`) || '{}',
      );
      setType(draft.type === 'advance' ? 'advance' : 'leave');
      setStart(validDateParam(draft.start));
      setEnd(validDateParam(draft.end));
      setAmount(typeof draft.amount === 'string' ? draft.amount : '');
      setComment(typeof draft.comment === 'string' ? draft.comment.slice(0, 2000) : '');
      setDraftAvailable(false);
      notify('Черновик восстановлен');
    } catch {
      setDraftAvailable(false);
      setValidation('Сохранённый черновик не удалось открыть. Заполните заявку заново.');
    }
  }

  async function submit() {
    if (step !== 2 || !canSubmit || conflicts.length || inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    setError(null);
    const fingerprint = JSON.stringify(payload);
    const pendingStorageKey = `posttech-request-pending:${api.mode}:${profile.id}`;
    const memoryKey = `${api.mode}:${profile.id}:${fingerprint}`;
    const persistedKeys = pendingRequestKeys(pendingStorageKey);
    let key = idempotencyKeys.current.get(memoryKey) || persistedKeys.get(fingerprint);
    if (!key) key = crypto.randomUUID();
    idempotencyKeys.current.set(memoryKey, key);
    persistedKeys.set(fingerprint, key);
    // Save before sending: an uncertain network result can be retried after a reload.
    storePendingRequestKeys(pendingStorageKey, persistedKeys);
    try {
      sessionStorage.setItem(
        `posttech-request-draft:${api.mode}:${profile.id}`,
        JSON.stringify({ type, start, end, amount, comment }),
      );
    } catch {
      /* Submitting remains available when browser storage is disabled. */
    }
    try {
      const request = await api.createRequest(payload, key);
      setCreated(request);
      idempotencyKeys.current.delete(memoryKey);
      persistedKeys.delete(fingerprint);
      storePendingRequestKeys(pendingStorageKey, persistedKeys);
      try {
        sessionStorage.removeItem(`posttech-request-draft:${api.mode}:${profile.id}`);
      } catch {
        /* Request is already saved on the server. */
      }
      refresh();
      notify('Заявка отправлена на согласование');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (reason) {
      setError(reason);
      if (
        type === 'leave' &&
        reason instanceof ApiError &&
        reason.detail === 'Leave overlaps an existing pending or approved request'
      ) {
        // The server remains authoritative, including conflicts created in another tab.
        try {
          setConflictRecords(await loadRequests(api, { scope: 'mine', request_type: 'leave' }));
        } catch {
          /* Keep the original error visible if the conflicting record cannot be loaded. */
        }
      }
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }

  if (created)
    return (
      <div className="req-success-wrap">
        <section className="card req-success">
          <div className="req-success-art" aria-hidden="true">
            <span className="req-success-icon">
              <Icon name="check" size={36} />
            </span>
            <i />
            <i />
            <i />
            <i />
          </div>
          <h1>{t('Заявка отправлена!')}</h1>
          <p className="muted">
            {tx(
              type === 'leave'
                ? `${formatDay(created.start_date)} — ${formatDay(created.end_date)}`
                : money(created.amount || 0),
            )}
            {tx(
              type === 'leave' && (
                <>
                  <br />
                  {tx(days)} {tx(dayWord(days, true))}
                </>
              ),
            )}
          </p>
          <div className="req-success-state">
            <span className="req-type-icon">
              <Icon name="clock" size={23} />
            </span>
            <div>
              <span>{t('Статус заявки')}</span>
              <StatusBadge status={created.status} />
            </div>
          </div>
          <div className="req-success-reviewer">
            <span>{t('Согласует')}</span>
            <strong>{tx(approverNames(created.approvers))}</strong>
          </div>
          <div className="req-success-actions">
            <Link className="btn btn-primary" to={`/requests/${created.id}`}>
              {t('Открыть заявку ')}
              <Icon name="arrow-right" size={17} />
            </Link>
            <Link className="btn btn-secondary" to="/">
              {t('Вернуться на главную')}
            </Link>
          </div>
          <span className="req-success-number">{tx(requestNumber(created.id))}</span>
        </section>
      </div>
    );

  return (
    <div className="req-page req-create-page">
      <Link className="req-back" to="/requests">
        <Icon name="chevron-left" size={16} />
        {t(' Мои заявки')}
      </Link>
      <PageHeader
        title={
          step === 2 ? 'Проверьте заявку' : type === 'leave' ? 'Оформить отпуск' : 'Запросить аванс'
        }
        actions={
          <div className="req-steps" aria-label={`Шаг ${step} из 2`}>
            <span className={step === 1 ? 'active' : 'done'}>
              <b>{tx(step > 1 ? <Icon name="check" size={13} /> : 1)}</b>
              {t(' Данные')}
            </span>
            <Icon name="chevron-right" size={16} />
            <span className={step === 2 ? 'active' : ''}>
              <b>2</b>
              {t(' Проверка')}
            </span>
          </div>
        }
      />
      <div className="req-form-layout">
        <div className="stack">
          {tx(
            routing && !routing.can_submit && !recoveringSubmission && (
              <p className="req-validation" role="alert">
                <Icon name="alert" size={18} />
                {t('Нет согласующего. Сохраните черновик и обратитесь в HR.')}
              </p>
            ),
          )}
          {step === 1 ? (
            <form id="request-form" className="stack" onSubmit={proceed}>
              {tx(
                draftAvailable && (
                  <div className="req-draft-note">
                    <Icon name="file" size={18} />
                    <span>{t('Есть сохранённый черновик')}</span>
                    <button type="button" className="btn btn-secondary" onClick={restoreDraft}>
                      {t('Восстановить')}
                    </button>
                  </div>
                ),
              )}
              <section className="card req-form-card">
                <h2>{t('Что оформляем?')}</h2>
                <div className="req-kind-selector">
                  <button
                    type="button"
                    className={type === 'leave' ? 'active' : ''}
                    onClick={() => {
                      setType('leave');
                      setValidation('');
                    }}
                    aria-pressed={type === 'leave'}
                  >
                    <Icon name="calendar" size={22} />
                    <span>
                      <strong>{t('Отпуск')}</strong>
                    </span>
                    {tx(type === 'leave' && <Icon name="check" size={17} />)}
                  </button>
                  <button
                    type="button"
                    className={type === 'advance' ? 'active' : ''}
                    onClick={() => {
                      setType('advance');
                      setValidation('');
                    }}
                    aria-pressed={type === 'advance'}
                  >
                    <Icon name="wallet" size={22} />
                    <span>
                      <strong>{t('Аванс')}</strong>
                    </span>
                    {tx(type === 'advance' && <Icon name="check" size={17} />)}
                  </button>
                </div>
              </section>
              <section className="card req-form-card">
                <div className="req-card-heading">
                  <h2>{tx(type === 'leave' ? 'Даты отпуска' : 'Сумма аванса')}</h2>
                  {tx(
                    type === 'leave' && (
                      <Link
                        className="btn btn-ghost req-small-btn"
                        state={{
                          requestDraft: { type, start, end, amount, comment },
                        }}
                        to={`/calendar?select=1${start ? `&start=${start}` : ''}${end ? `&end=${end}` : ''}`}
                      >
                        <Icon name="calendar" size={16} />
                        {t(' Календарь')}
                      </Link>
                    ),
                  )}
                </div>
                {tx(
                  type === 'leave' ? (
                    <>
                      <div className="req-date-fields">
                        <label className="field">
                          <span className="field-label">{t('С')}</span>
                          <input
                            className="input"
                            aria-label={t('Дата начала')}
                            type="date"
                            required
                            min={recoveringSubmission ? undefined : today}
                            value={start}
                            onChange={(event) => {
                              setStart(event.target.value);
                              if (end && event.target.value > end) setEnd('');
                            }}
                          />
                        </label>
                        <span className="req-date-arrow">
                          <Icon name="arrow-right" size={18} />
                        </span>
                        <label className="field">
                          <span className="field-label">{t('По')}</span>
                          <input
                            className="input"
                            aria-label={t('Дата окончания')}
                            type="date"
                            required
                            min={start || (recoveringSubmission ? undefined : today)}
                            value={end}
                            onChange={(event) => setEnd(event.target.value)}
                          />
                        </label>
                      </div>
                      <div className="req-date-caption">
                        <Icon name="calendar-check" size={18} />
                        <span>
                          {tx(
                            days ? (
                              <>
                                <strong>{tx(days)}</strong> {tx(dayWord(days, true))}
                              </>
                            ) : (
                              'Выберите начало и конец отпуска'
                            ),
                          )}
                        </span>
                      </div>
                    </>
                  ) : (
                    <>
                      <label className="field">
                        <span className="field-label">{t('Сумма, ₸')}</span>
                        <input
                          className="input req-amount-input"
                          type="number"
                          inputMode="decimal"
                          min="0.01"
                          max="1000000"
                          step="0.01"
                          required
                          value={amount}
                          onChange={(event) => setAmount(event.target.value)}
                          placeholder="50 000"
                        />
                      </label>
                      <p className="req-field-help">{t('От 0,01 до 1 000 000 ₸')}</p>
                    </>
                  ),
                )}
                <div className="req-inline-comment">
                  <label className="field">
                    <span className="field-label">
                      {t('Комментарий ')}
                      <span className="muted">{t('· необязательно')}</span>
                    </span>
                    <textarea
                      className="input req-comment"
                      value={comment}
                      maxLength={2000}
                      onChange={(event) => setComment(event.target.value)}
                      placeholder={
                        type === 'leave'
                          ? 'Например, планирую поездку с семьёй'
                          : 'Для чего нужен аванс'
                      }
                    />
                  </label>
                  {tx(
                    comment.length > 1800 && (
                      <div className="req-character-count">{tx(comment.length)} / 2000</div>
                    ),
                  )}
                </div>
              </section>
              {tx(
                validation && (
                  <p className="req-validation" role="alert">
                    <Icon name="info" size={17} />
                    {tx(validation)}
                  </p>
                ),
              )}
              <div className="req-form-actions req-mobile-actions">
                <button type="button" className="btn btn-secondary" onClick={saveDraft}>
                  <Icon name="file" size={17} />
                  {t(' Черновик')}
                </button>
                <button type="submit" className="btn btn-primary" disabled={!canSubmit}>
                  {t('Продолжить ')}
                  <Icon name="arrow-right" size={18} />
                </button>
              </div>
            </form>
          ) : (
            <>
              <section className="card req-form-card req-review-summary">
                <div className="req-review-hero">
                  <span className="req-type-icon">
                    <Icon name={type === 'leave' ? 'calendar' : 'wallet'} size={26} />
                  </span>
                  <div>
                    <span>{tx(type === 'leave' ? 'Трудовой отпуск' : 'Аванс')}</span>
                    <strong>
                      {tx(
                        type === 'leave'
                          ? `${formatDay(start)} — ${formatDay(end)}`
                          : money(Number(amount.replace(',', '.'))),
                      )}
                    </strong>
                    {tx(
                      type === 'leave' && (
                        <b>
                          {tx(days)} {tx(dayWord(days, true))}
                        </b>
                      ),
                    )}
                  </div>
                  <button
                    className="btn btn-ghost req-small-btn"
                    onClick={() => {
                      setStep(1);
                    }}
                  >
                    {t('Изменить')}
                  </button>
                </div>
                {type === 'leave' && <LeaveBalance days={days} onAvailable={setAvailableDays} />}
                <label className="field req-review-comment">
                  <span className="field-label">
                    {t('Комментарий ')}
                    <span className="muted">{t('· необязательно')}</span>
                  </span>
                  <textarea
                    className="input req-comment"
                    value={comment}
                    maxLength={2000}
                    disabled={submitting}
                    onChange={(event) => setComment(event.target.value)}
                    placeholder={t('Добавить комментарий')}
                  />
                </label>
                <div className="req-review-approver">
                  <span className="req-routing-label">
                    {tx(routing?.route === 'manager' ? 'Согласует руководитель' : 'Согласует HR')}
                  </span>
                  {routingError ? (
                    <ErrorState
                      error={routingError}
                      retry={() => setRoutingReload((value) => value + 1)}
                    />
                  ) : !routing ? (
                    <LoadingState />
                  ) : (
                    <div className="req-approvers">
                      {routing.approvers.map((person) => (
                        <div key={person.id}>
                          <Avatar name={person.full_name} size={36} />
                          <span>
                            <strong>{person.full_name}</strong>
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </section>
              {conflicts.length ? (
                <LeaveConflictNotice
                  records={conflicts}
                  onChangeDates={() => {
                    setStep(1);
                    setError(null);
                    setStart('');
                    setEnd('');
                  }}
                />
              ) : (
                Boolean(error) && <ErrorState error={error} />
              )}
              <div className="req-confirm-actions req-mobile-actions">
                <button
                  className="btn btn-secondary"
                  disabled={submitting}
                  onClick={() => {
                    setStep(1);
                    setError(null);
                  }}
                >
                  <Icon name="chevron-left" size={17} />
                  {t(' Назад')}
                </button>
                <button
                  className="btn btn-primary"
                  disabled={!canSubmit || submitting || conflicts.length > 0}
                  onClick={submit}
                >
                  {tx(submitting ? 'Отправляем…' : 'Отправить заявку')}
                  <Icon name="arrow-right" size={18} />
                </button>
              </div>
            </>
          )}
        </div>
        <aside className={`stack req-form-aside ${step === 2 ? 'req-review-aside' : ''}`}>
          {step === 1 && type === 'leave' && (
            <section className="card req-balance-card">
              <LeaveBalance days={days} onAvailable={setAvailableDays} />
            </section>
          )}
          {step === 1 && (
            <section className="card req-form-card req-routing-card">
              <h2>{t('Согласует')}</h2>
              {routingError ? (
                <ErrorState
                  error={routingError}
                  retry={() => setRoutingReload((value) => value + 1)}
                />
              ) : !routing ? (
                <LoadingState />
              ) : routing.can_submit ? (
                <div className="req-approvers">
                  {routing.approvers.map((person) => (
                    <div key={person.id}>
                      <Avatar name={person.full_name} size={36} />
                      <span>
                        <strong>{person.full_name}</strong>
                        <small>{tx(person.role === 'hr_admin' ? 'HR' : 'Руководитель')}</small>
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="req-route-unavailable" role="alert">
                  <strong>{t('Не назначен согласующий')}</strong>
                  <p>{t('Обратитесь в HR для настройки маршрута.')}</p>
                  <button
                    className="btn btn-secondary"
                    onClick={() => setRoutingReload((value) => value + 1)}
                  >
                    {t('Проверить снова')}
                  </button>
                </div>
              )}
            </section>
          )}
          <details className="card req-policy">
            <summary>
              <Icon name="info" size={17} />
              {t(' Условия оформления ')}
              <Icon name="chevron-down" size={16} />
            </summary>
            <p>
              {tx(
                type === 'leave'
                  ? 'Считаем календарные дни, включая выходные. Отпуск начинается сегодня или позже и не пересекается с вашими действующими заявками. При отправке дни резервируются. После согласования резерв сохраняется до сверки кадрового остатка.'
                  : 'Сумма указывается в тенге. Решение и комментарий согласующего появятся в заявке.',
              )}
            </p>
            <p>{t('Автор не согласует свою заявку. До решения её можно отозвать.')}</p>
          </details>
          <button className="req-aside-link" onClick={() => navigate('/jana')}>
            <span className="req-type-icon">
              <Icon name="message" size={21} />
            </span>
            <strong>{t('Помощь AI Jana')}</strong>
            <Icon name="chevron-right" size={18} />
          </button>
        </aside>
      </div>
    </div>
  );
}

function validDateParam(value: unknown): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return '';
  const parsed = parseDay(value);
  return Number.isNaN(parsed.getTime()) || dateKey(parsed) !== value ? '' : value;
}

function RequestDetails({ id }: { id: string }) {
  const { api, profile, refresh, refreshKey, notify } = usePortal();
  const [record, setRecord] = useState<RequestRecord | null>(null);
  const [history, setHistory] = useState<RequestEvent[]>([]);
  const [people, setPeople] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [historyError, setHistoryError] = useState<unknown>(null);
  const [reviewError, setReviewError] = useState<unknown>(null);
  const [reload, setReload] = useState(0);
  const [reviewComment, setReviewComment] = useState('');
  const [decision, setDecision] = useState<'approved' | 'rejected' | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<unknown>(null);
  const reviewInFlight = useRef(false);
  const cancelInFlight = useRef(false);
  useEffect(() => {
    setLoading(true);
    setError(null);
    setHistoryError(null);
    let loaded = false;
    return watchVisible(async (signal) => {
      if (reviewInFlight.current || cancelInFlight.current) return;
      const [recordResult, historyResult] = await Promise.allSettled([
        api.getRequest(id),
        api.getRequestHistory(id),
      ]);
      if (signal.aborted || reviewInFlight.current || cancelInFlight.current) return;
      if (recordResult.status === 'fulfilled') {
        setRecord(recordResult.value);
        setError(null);
        loaded = true;
      } else if (
        !loaded ||
        (recordResult.reason instanceof ApiError && [403, 404].includes(recordResult.reason.status))
      ) {
        setError(recordResult.reason);
      }
      if (historyResult.status === 'fulfilled') {
        setHistory(historyResult.value);
        setHistoryError(null);
      } else setHistoryError(historyResult.reason);
      setLoading(false);
    });
  }, [api, id, reload, refreshKey]);
  useEffect(() => {
    let active = true;
    if (['manager', 'director'].includes(profile.role) || profile.role === 'hr_admin')
      api
        .getTeam()
        .then((data) => {
          if (active) setPeople(data);
        })
        .catch(() => {
          /* Show identifier if employee details are unavailable. */
        });
    return () => {
      active = false;
    };
  }, [api, profile.role]);
  const employee =
    record?.employee_id === profile.id
      ? profile
      : people.find((person) => person.id === record?.employee_id);
  const canReview = Boolean(
    record &&
      record.employee_id !== profile.id &&
      record.status === 'pending' &&
      (record.can_review ??
        (profile.role === 'hr_admin' ||
          (['manager', 'director'].includes(profile.role) &&
            record.approvers?.some((person) => person.id === profile.id)))),
  );
  const canCancel = record?.employee_id === profile.id && record.status === 'pending';

  async function cancelRequest() {
    if (!record || !canCancel || cancelInFlight.current) return;
    cancelInFlight.current = true;
    setCancelling(true);
    setCancelError(null);
    try {
      const updated = await api.cancelRequest(record.id);
      setRecord(updated);
      setCancelOpen(false);
      refresh();
      notify('Заявка отозвана. Согласующие получили уведомление.');
    } catch (reason) {
      setCancelError(reason);
    } finally {
      cancelInFlight.current = false;
      setCancelling(false);
    }
  }

  async function review() {
    if (!decision || !record || reviewInFlight.current) return;
    if (decision === 'rejected' && !reviewComment.trim()) {
      setReviewError(new Error('Укажите причину отказа, чтобы сотрудник понимал решение.'));
      return;
    }
    reviewInFlight.current = true;
    setReviewing(true);
    setReviewError(null);
    try {
      const updated = await api.reviewRequest(record.id, {
        status: decision,
        reviewer_comment: reviewComment.trim() || null,
      });
      setRecord(updated);
      setDecision(null);
      refresh();
      notify(updated.status === 'approved' ? 'Заявка согласована' : 'Заявка отклонена');
    } catch (reason) {
      setReviewError(reason);
    } finally {
      setReviewing(false);
      reviewInFlight.current = false;
    }
  }
  if (loading) return <LoadingState />;
  if (error instanceof ApiError && error.status === 403) {
    const reviewer = ['manager', 'director', 'hr_admin'].includes(profile.role);
    return (
      <EmptyState
        title="Заявка больше недоступна"
        description="Согласование могло завершиться или ваши права доступа изменились. Вернитесь к списку заявок."
        action={
          <Link
            className="btn btn-primary"
            to={reviewer ? '/requests?scope=review' : '/requests?scope=mine'}
          >
            {t(reviewer ? 'На согласование' : 'Мои заявки')}
          </Link>
        }
      />
    );
  }
  if (error || !record)
    return (
      <div className="stack">
        <Link className="req-back" to="/requests">
          <Icon name="chevron-left" size={16} />
          {t(' Все заявки')}
        </Link>
        <ErrorState
          error={error || 'Заявка не найдена'}
          retry={() => setReload((value) => value + 1)}
        />
      </div>
    );
  return (
    <div className="req-page">
      <Link
        className="req-back"
        to={
          record.employee_id !== profile.id && profile.role !== 'worker'
            ? '/requests?scope=review'
            : '/requests'
        }
      >
        <Icon name="chevron-left" size={16} />
        {t(
          record.employee_id !== profile.id && profile.role !== 'worker'
            ? 'На согласование'
            : 'Мои заявки',
        )}
        <span>/</span> {tx(requestNumber(record.id))}
      </Link>
      <PageHeader
        title={`${requestLabel(record)}`}
        description={`№ ${requestNumber(record.id)} · Создана ${formatTime(record.created_at)}`}
        actions={
          <div className="req-detail-actions">
            <RequestState request={record} />
            {tx(
              canCancel && (
                <button
                  className="btn req-btn-danger-outline"
                  onClick={() => {
                    setCancelError(null);
                    setCancelOpen(true);
                  }}
                >
                  <Icon name="x" size={16} />
                  {t('Отозвать заявку')}
                </button>
              ),
            )}
          </div>
        }
      />
      <section
        className={`req-workflow-summary req-workflow-${record.status}`}
        aria-label={t('Состояние заявки')}
      >
        <Icon
          name={
            record.status === 'pending'
              ? 'clock'
              : record.status === 'approved'
                ? 'check-circle'
                : 'info'
          }
          size={23}
        />
        <div>
          <strong>
            {tx(
              record.status === 'pending'
                ? canReview
                  ? 'Заявка ждёт вашего решения'
                  : 'Ожидает согласования'
                : record.status === 'approved'
                  ? 'Заявка согласована'
                  : record.status === 'rejected'
                    ? 'Заявка отклонена'
                    : 'Заявка отозвана',
            )}
          </strong>
          <p>
            {record.status === 'pending' ? (
              canReview ? (
                t('Проверьте даты или сумму и примите решение.')
              ) : (
                <>
                  {t('Согласует')}: {tx(approverNames(record.approvers))}.{' '}
                  {t('Решение появится здесь и в уведомлениях.')}
                </>
              )
            ) : record.status === 'approved' ? (
              t('Повторно отправлять заявку не нужно.')
            ) : record.status === 'rejected' ? (
              record.reviewer_comment || t('Причина указана в истории согласования.')
            ) : (
              t('При необходимости можно оформить новую заявку.')
            )}
          </p>
        </div>
        {canReview && (
          <a
            className="btn btn-primary"
            href="#request-decision"
            onClick={(event) => {
              event.preventDefault();
              document.getElementById('request-decision')?.focus();
            }}
          >
            {t('Перейти к решению')}
            <Icon name="arrow-right" size={16} />
          </a>
        )}
      </section>
      <div className="req-form-layout">
        <div className="stack">
          {record.status === 'approved' && <RequestFulfillment request={record} />}
          <section className="card req-form-card">
            <h2>
              <Icon name="file" size={19} />
              {t(' Детали заявки')}
            </h2>
            <div className="req-detail-summary">
              <div>
                <span className="req-type-icon">
                  <Icon name="user" size={20} />
                </span>
                <div>
                  <span>{t('Инициатор заявки')}</span>
                  <strong>
                    {employee?.full_name || `Сотрудник ${record.employee_id.slice(0, 8)}`}
                  </strong>
                  {tx(employee && <small>{tx(employee.job_title)}</small>)}
                </div>
              </div>
              <div>
                <span className="req-type-icon">
                  <Icon name={record.request_type === 'leave' ? 'calendar' : 'wallet'} size={20} />
                </span>
                <div>
                  <span>
                    {tx(record.request_type === 'leave' ? 'Период отсутствия' : 'Сумма аванса')}
                  </span>
                  <strong>
                    {tx(
                      record.request_type === 'leave'
                        ? `${formatDay(record.start_date)} — ${formatDay(record.end_date)}`
                        : money(record.amount || 0),
                    )}
                  </strong>
                  {tx(
                    record.start_date && record.end_date && (
                      <small className="req-green">
                        {tx(dayCount(record.start_date, record.end_date))}{' '}
                        {tx(dayWord(dayCount(record.start_date, record.end_date), true))}
                      </small>
                    ),
                  )}
                </div>
              </div>
              {tx(
                employee && (
                  <div>
                    <span className="req-type-icon">
                      <Icon name="building" size={20} />
                    </span>
                    <div>
                      <span>{t('Подразделение')}</span>
                      <strong>{tx(employee.department)}</strong>
                      <small>{tx(employee.company)}</small>
                    </div>
                  </div>
                ),
              )}
              <div>
                <span className="req-type-icon">
                  <Icon name="clock" size={20} />
                </span>
                <div>
                  <span>{t('Последнее обновление')}</span>
                  <strong>{tx(formatTime(record.updated_at))}</strong>
                  <small>
                    {tx(
                      record.reviewed_at
                        ? 'Решение принято'
                        : record.status === 'pending'
                          ? 'Ожидает рассмотрения'
                          : 'Статус обновлён',
                    )}
                  </small>
                </div>
              </div>
            </div>
          </section>
          {tx(
            canReview && (
              <section
                id="request-decision"
                tabIndex={-1}
                className="card req-form-card req-review-card"
              >
                <h2>
                  <Icon name="check" size={19} />
                  {t(' Рассмотрение заявки')}
                </h2>
                {record.request_type === 'leave' && <LeaveBalance requestId={record.id} review />}
                <label className="field">
                  <span className="field-label">
                    {t('Комментарий к решению (обязателен при отказе)')}
                  </span>
                  <textarea
                    className="input req-comment"
                    maxLength={2000}
                    value={reviewComment}
                    disabled={reviewing}
                    onChange={(event) => {
                      setReviewComment(event.target.value);
                      setDecision(null);
                    }}
                    placeholder={t('Укажите причину или оставьте пояснение для сотрудника…')}
                  />
                </label>
                {tx(
                  Boolean(reviewError) && (
                    <ErrorState error={reviewError} retry={() => setReload((value) => value + 1)} />
                  ),
                )}
                {tx(
                  decision ? (
                    <div className="req-decision-confirm">
                      <p>
                        {t('Подтвердите решение: ')}
                        <strong>
                          {tx(decision === 'approved' ? 'согласовать' : 'отклонить')}
                          {t(' заявку')}
                        </strong>
                        {t('. Решение будет сохранено в истории и отправлено сотруднику.')}
                      </p>
                      <div>
                        <button
                          className="btn btn-secondary"
                          disabled={reviewing}
                          onClick={() => setDecision(null)}
                        >
                          {t('Вернуться')}
                        </button>
                        <button
                          className={`btn ${decision === 'approved' ? 'btn-primary' : 'req-btn-danger'}`}
                          disabled={reviewing}
                          onClick={review}
                        >
                          {tx(reviewing ? 'Сохраняем…' : 'Подтвердить решение')}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="req-review-actions">
                      <button
                        className="btn req-btn-danger-outline"
                        disabled={!reviewComment.trim()}
                        onClick={() => setDecision('rejected')}
                      >
                        <Icon name="x" size={17} />
                        {t(' Отклонить')}
                      </button>
                      <button className="btn btn-primary" onClick={() => setDecision('approved')}>
                        <Icon name="check" size={17} />
                        {t(' Согласовать заявку')}
                      </button>
                    </div>
                  ),
                )}
              </section>
            ),
          )}
          <section className="card req-form-card">
            <h2>
              <Icon name="message" size={19} />
              {t(' Комментарии к заявке')}
            </h2>
            <div className="req-comment-block">
              <strong>{t('Комментарий сотрудника')}</strong>
              <p>{record.comment || 'Комментарий не добавлен.'}</p>
            </div>
            {record.reviewer_comment && (
              <div className="req-comment-block req-reviewer-comment">
                <strong>{t('Комментарий согласующего')}</strong>
                <p>{record.reviewer_comment}</p>
              </div>
            )}
          </section>
          <section className="card req-form-card">
            <div className="req-card-heading">
              <h2>
                <Icon name="clock" size={19} />
                {t(' История согласования')}
              </h2>
            </div>
            {historyError ? (
              <ErrorState error={historyError} retry={() => setReload((value) => value + 1)} />
            ) : history.length ? (
              <ol className="req-history">
                {history.map((event) => (
                  <li key={event.id}>
                    <span className={`req-history-dot req-history-${event.event_type}`}>
                      <Icon
                        name={
                          event.event_type === 'rejected' || event.event_type === 'cancelled'
                            ? 'x'
                            : 'check'
                        }
                        size={15}
                      />
                    </span>
                    <div>
                      <div className="req-history-title">
                        <strong>
                          {tx(
                            event.event_type === 'created'
                              ? 'Заявка подана сотрудником'
                              : event.event_type === 'approved'
                                ? 'Заявка согласована'
                                : event.event_type === 'cancelled'
                                  ? 'Заявка отозвана автором'
                                  : 'Заявка отклонена',
                          )}
                        </strong>
                        <time dateTime={event.created_at}>{tx(formatTime(event.created_at))}</time>
                      </div>
                      <p>
                        {event.event_type === 'created' || event.event_type === 'cancelled'
                          ? employee?.full_name || 'Сотрудник'
                          : people.find((person) => person.id === event.actor_id)?.full_name ||
                            record.approvers?.find((person) => person.id === event.actor_id)
                              ?.full_name ||
                            (event.actor_id === profile.id
                              ? profile.full_name
                              : 'Руководитель / HR')}
                      </p>
                      {tx(
                        event.delegation_id && <small>{t('Решение принято заместителем')}</small>,
                      )}
                      {event.comment && <p className="req-history-comment">{event.comment}</p>}
                    </div>
                  </li>
                ))}
                {tx(
                  record.status === 'pending' && (
                    <li>
                      <span className="req-history-dot req-history-pending">
                        <Icon name="clock" size={15} />
                      </span>
                      <div>
                        <strong>{t('Ожидает рассмотрения')}</strong>
                        <p>{tx(approverNames(record.approvers))}</p>
                      </div>
                    </li>
                  ),
                )}
              </ol>
            ) : (
              <p className="muted">{t('История изменений пока отсутствует.')}</p>
            )}
          </section>
        </div>
        <aside className="stack">
          <section className="card req-form-card req-routing-card">
            <h2>
              <Icon name="users" size={19} />
              {t('Согласующие')}
            </h2>
            {record.approvers?.length ? (
              <div className="req-approvers">
                {record.approvers.map((person) => (
                  <div key={person.id}>
                    <Avatar name={person.full_name} size={32} />
                    <span>
                      <strong>{person.full_name}</strong>
                      <small>
                        {tx(person.role === 'hr_admin' ? 'HR / администратор' : 'Руководитель')}
                      </small>
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="req-field-help">
                {t(
                  'Для этой заявки маршрут ранее не был сохранён. Другой сотрудник HR может принять её в работу.',
                )}
              </p>
            )}
          </section>
          <section className="card req-form-card">
            <h2>{t('Карточка заявки')}</h2>
            <dl className="req-metadata">
              <div>
                <dt>{t('Номер')}</dt>
                <dd>{tx(requestNumber(record.id))}</dd>
              </div>
              <div>
                <dt>{t('Тип')}</dt>
                <dd>{tx(record.request_type === 'leave' ? 'Отпуск' : 'Аванс')}</dd>
              </div>
              <div>
                <dt>{t('Создана')}</dt>
                <dd>{tx(formatDay(record.created_at))}</dd>
              </div>
              <div>
                <dt>{t('Статус')}</dt>
                <dd>
                  <RequestState request={record} />
                </dd>
              </div>
              {tx(
                record.reviewed_at && (
                  <div>
                    <dt>{t('Рассмотрена')}</dt>
                    <dd>{tx(formatDay(record.reviewed_at))}</dd>
                  </div>
                ),
              )}
            </dl>
            {tx(
              record.request_type === 'leave' && (
                <Link
                  className="btn btn-secondary req-full-width"
                  to={`/calendar?date=${record.start_date || ''}`}
                >
                  <Icon name="calendar" size={16} />
                  {t(' Открыть в календаре')}
                </Link>
              ),
            )}
          </section>
          {record.request_type === 'leave' && record.status === 'approved' && (
            <LeaveCalendarDownload requestId={record.id} />
          )}
          <div className="req-detail-note">
            <Icon name="info" size={20} />
            <p>
              {tx(
                record.status === 'pending'
                  ? 'Можно отозвать до решения согласующего.'
                  : record.status === 'cancelled'
                    ? 'Заявка отозвана. При необходимости создайте новую.'
                    : 'Решение сохранено. Вопросы можно уточнить у согласующего.',
              )}
            </p>
          </div>
        </aside>
      </div>
      {tx(
        cancelOpen && (
          <Modal
            title={t('Отозвать заявку?')}
            onClose={() => {
              if (!cancelling) setCancelOpen(false);
            }}
          >
            <p className="req-cancel-description">
              {t('Заявка ')}
              {tx(requestNumber(record.id))}
              {t(
                ' перестанет ожидать согласования. Мы сохраним отзыв в истории и уведомим согласующих. Возобновить эту заявку нельзя, но можно создать новую.',
              )}
            </p>
            {tx(
              Boolean(cancelError) && (
                <ErrorState
                  error={cancelError}
                  retry={() => {
                    setCancelOpen(false);
                    setReload((value) => value + 1);
                  }}
                />
              ),
            )}
            <div className="req-review-actions">
              <button
                className="btn btn-secondary"
                disabled={cancelling}
                onClick={() => setCancelOpen(false)}
              >
                {t('Оставить заявку')}
              </button>
              <button className="btn req-btn-danger" disabled={cancelling} onClick={cancelRequest}>
                {tx(cancelling ? 'Отзываем…' : 'Подтвердить отзыв')}
              </button>
            </div>
          </Modal>
        ),
      )}
    </div>
  );
}
