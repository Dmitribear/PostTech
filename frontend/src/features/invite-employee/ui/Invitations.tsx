import { usePortal } from '@/entities/session';
import { errorMessage, LiveApi } from '@/shared/api/api';
import type {
  AppRole,
  EmployeeProfile,
  InvitationInput,
  InvitationRecord,
  IssuedInvitation,
} from '@/shared/api/contracts';
import { formatDate, roleLabels } from '@/shared/lib/format';
import { t, tx } from '@/shared/lib/i18n';
import { watchVisible } from '@/shared/lib/live-refresh';
import '@/shared/styles/invitations.css';
import { Icon, Modal } from '@/shared/ui/index';
import { ListPager, useListPage } from '@/shared/ui/molecules/ListPager';
import { useEffect, useRef, useState, type FormEvent } from 'react';

export default function Invitations({
  employees,
  onClose,
}: {
  employees: EmployeeProfile[];
  onClose: () => void;
}) {
  const { api, profile } = usePortal();
  const live = api instanceof LiveApi ? api : null;
  const [view, setView] = useState<'create' | 'list'>('create');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<IssuedInvitation | null>(null);
  const [rows, setRows] = useState<InvitationRecord[]>([]);
  const [search, setSearch] = useState('');
  const filtered = rows.filter((row) =>
    `${row.email} ${row.department}`
      .toLocaleLowerCase()
      .includes(search.toLocaleLowerCase().trim()),
  );
  const paging = useListPage(filtered, search, 10);
  const [copied, setCopied] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const mutation = useRef(false);
  const revision = useRef(0);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const retrySeconds = Math.max(0, Math.ceil((retryAt - now) / 1000));
  const mailLabels: Record<string, string> = {
    accepted: 'Письмо передано почтовому сервису',
    failed: 'Почтовый сервис отклонил письмо',
    unknown: 'Отправка не подтверждена — проверьте почту',
    sending: 'Результат отправки пока не подтверждён',
    not_sent: 'Письмо ещё не отправлено',
    not_configured: 'Приглашение создано. Отправка почты пока не настроена',
  };
  const [listVersion, setListVersion] = useState(0);
  const [input, setInput] = useState<InvitationInput>({
    email: '',
    employee_code: '',
    company: profile.company,
    job_title: '',
    department: profile.department,
    hired_at: new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Qyzylorda',
    }).format(new Date()),
    manager_id: null,
    role: 'worker',
    vacation_days_remaining: 0,
    expires_in_hours: 72,
  });
  const update = <K extends keyof InvitationInput>(key: K, value: InvitationInput[K]) =>
    setInput((previous) => ({ ...previous, [key]: value }));
  useEffect(() => {
    if (view !== 'list' || !live || result) return;
    let loaded = false;
    setBusy(true);
    setError('');
    return watchVisible(async (signal) => {
      if (mutation.current) return;
      const version = revision.current;
      try {
        const data = await live.getInvitations();
        if (!signal.aborted && version === revision.current) {
          setRows(data);
          setError('');
          loaded = true;
        }
      } catch (err) {
        if (!signal.aborted && version === revision.current && !loaded) setError(errorMessage(err));
      } finally {
        if (!signal.aborted && version === revision.current) setBusy(false);
      }
    }, 3000);
  }, [view, live, listVersion, result]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    mutation.current = true;
    revision.current += 1;
    setBusy(true);
    setError('');
    try {
      const value = live
        ? await live.issueInvitation({
            ...input,
            email: input.email.trim(),
            employee_code: input.employee_code.trim(),
          })
        : {
            id: 'demo',
            invitation_code: 'JP-DEMO-2026',
            email: input.email,
            role: input.role,
            department: input.department,
            expires_at: new Date(Date.now() + input.expires_in_hours * 3600000).toISOString(),
          };
      setResult(value);
      setCopied(false);
      setRetryAt(Date.now() + 60000);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  }
  async function revoke(id: string) {
    if (!live || busy) return;
    mutation.current = true;
    revision.current += 1;
    setBusy(true);
    setError('');
    try {
      await live.revokeInvitation(id);
      setListVersion((value) => value + 1);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  }
  async function sendEmail(id: string) {
    if (!live || busy) return;
    mutation.current = true;
    revision.current += 1;
    setBusy(true);
    setError('');
    try {
      setResult(await live.sendInvitation(id));
      setCopied(false);
      setRetryAt(Date.now() + 60000);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  }
  async function copyCode() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.invitation_code);
      setCopied(true);
    } catch {
      setError('Не удалось скопировать автоматически. Выделите код и скопируйте его вручную.');
    }
  }
  return (
    <Modal
      title={result ? 'Приглашение готово' : 'Приглашения'}
      wide
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      {tx(
        !live && (
          <div className="invite-note">
            <Icon name="info" size={18} />
            <span>{t('Демоверсия: приглашение не создаёт рабочий аккаунт.')}</span>
          </div>
        ),
      )}
      {result ? (
        <div className="invite-result">
          <span className="invite-result-icon">
            <Icon name="mail" size={30} />
          </span>
          <h3>{result.email}</h3>
          <p>
            {tx(roleLabels[result.role])} · {tx(result.department)}
          </p>
          <p role="status">
            {tx(
              live
                ? mailLabels[result.email_status || 'not_sent']
                : 'Демоверсия: письмо не отправляется',
            )}
          </p>
          <p className="muted">
            {t('Роль назначена HR. Сотруднику останется задать пароль и подтвердить почту.')}
          </p>
          {live && result.email_status !== 'not_configured' && (
            <button
              className="btn btn-secondary"
              disabled={busy || retrySeconds > 0}
              onClick={() => sendEmail(result.id)}
            >
              {tx(retrySeconds ? `Повторить через ${retrySeconds} с` : 'Отправить новый код')}
            </button>
          )}
          <details>
            <summary>{t('Передать код вручную')}</summary>
            <label className="field">
              <span className="field-label">{t('Код приглашения')}</span>
              <input
                className="input invite-code"
                readOnly
                value={result.invitation_code}
                onFocus={(event) => event.target.select()}
              />
            </label>
            <button className="btn btn-secondary" onClick={copyCode}>
              {tx(copied ? 'Код скопирован' : 'Скопировать код')}
            </button>
          </details>
          <p className="muted">
            {t('Действует до ')}
            {tx(formatDate(result.expires_at))}
            {t('. Повторная отправка заменяет предыдущий код.')}
          </p>
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={() => {
              setResult(null);
              setView('list');
              setListVersion((v) => v + 1);
            }}
          >
            {t('К списку приглашений')}
          </button>
        </div>
      ) : (
        <>
          <div className="support-tabs">
            <button
              className="support-tab"
              disabled={busy}
              aria-pressed={view === 'create'}
              onClick={() => {
                setView('create');
                setError('');
              }}
            >
              {t('Новое')}
            </button>
            <button
              className="support-tab"
              disabled={busy}
              aria-pressed={view === 'list'}
              onClick={() => {
                setView('list');
                setError('');
              }}
            >
              {t('Выданные')}
            </button>
          </div>
          {view === 'create' ? (
            <form className="invite-form" onSubmit={submit}>
              <p className="muted">
                {t('Назначьте роль и руководителя. Отправим сотруднику письмо с кодом доступа.')}
              </p>
              <div className="invite-fields">
                <label className="field">
                  <span className="field-label">{t('Рабочая почта')}</span>
                  <input
                    className="input"
                    type="email"
                    required
                    maxLength={320}
                    autoComplete="off"
                    value={input.email}
                    onChange={(e) => update('email', e.target.value)}
                  />
                </label>
                <label className="field">
                  <span className="field-label">{t('Табельный номер')}</span>
                  <input
                    className="input"
                    required
                    maxLength={80}
                    value={input.employee_code}
                    onChange={(e) => update('employee_code', e.target.value)}
                  />
                </label>
                <label className="field">
                  <span className="field-label">{t('Должность')}</span>
                  <input
                    className="input"
                    required
                    maxLength={160}
                    value={input.job_title}
                    onChange={(e) => update('job_title', e.target.value)}
                  />
                </label>
                <label className="field">
                  <span className="field-label">{t('Подразделение')}</span>
                  <input
                    className="input"
                    required
                    maxLength={160}
                    value={input.department}
                    onChange={(e) => update('department', e.target.value)}
                  />
                </label>
                <label className="field">
                  <span className="field-label">{t('Роль')}</span>
                  <select
                    className="input"
                    value={input.role}
                    onChange={(e) => update('role', e.target.value as AppRole)}
                  >
                    {tx(
                      (['worker', 'manager', 'director', 'hr_admin'] as AppRole[]).map((role) => (
                        <option key={role} value={role}>
                          {tx(roleLabels[role])}
                        </option>
                      )),
                    )}
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">{t('Руководитель')}</span>
                  <select
                    className="input"
                    value={input.manager_id || ''}
                    onChange={(e) => update('manager_id', e.target.value || null)}
                  >
                    <option value="">{t('Согласование через HR')}</option>
                    {employees
                      .filter((item) => item.role !== 'worker')
                      .map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.full_name} · {item.employee_code}
                        </option>
                      ))}
                  </select>
                </label>
                <label className="field">
                  <span className="field-label">{t('Компания')}</span>
                  <input
                    className="input"
                    required
                    maxLength={120}
                    value={input.company}
                    onChange={(e) => update('company', e.target.value)}
                  />
                </label>
                <label className="field">
                  <span className="field-label">{t('Дата приёма')}</span>
                  <input
                    className="input"
                    type="date"
                    required
                    value={input.hired_at}
                    onChange={(e) => update('hired_at', e.target.value)}
                  />
                </label>
                <label className="field">
                  <span className="field-label">{t('Остаток отпуска, дней')}</span>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    max={9999.9}
                    step={0.1}
                    required
                    value={input.vacation_days_remaining}
                    onChange={(e) => update('vacation_days_remaining', Number(e.target.value))}
                  />
                </label>
                <label className="field">
                  <span className="field-label">{t('Срок действия')}</span>
                  <select
                    className="input"
                    value={input.expires_in_hours}
                    onChange={(e) => update('expires_in_hours', Number(e.target.value))}
                  >
                    <option value={24}>{t('1 день')}</option>
                    <option value={72}>{t('3 дня')}</option>
                    <option value={168}>{t('7 дней')}</option>
                  </select>
                </label>
              </div>
              {tx(
                input.role === 'hr_admin' && (
                  <div className="invite-note">
                    <Icon name="shield" size={18} />
                    <span>
                      {t(
                        'HR-администратор получает доступ к сотрудникам, согласованию, приглашениям и обучению.',
                      )}
                    </span>
                  </div>
                ),
              )}
              <div className="ws-form-actions">
                <button className="btn btn-primary" disabled={busy}>
                  {tx(busy ? 'Отправляем…' : 'Пригласить по почте')}
                  <Icon name="plus" size={16} />
                </button>
              </div>
            </form>
          ) : (
            <>
              <div className="list-anchor" ref={paging.anchor}>
                <label className="field">
                  {t('Поиск приглашения')}
                  <input
                    className="input"
                    type="search"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder={t('Почта или подразделение')}
                  />
                </label>
              </div>
              <div className="invite-list">
                {tx(busy && <p role="status">{t('Загружаем…')}</p>)}
                {tx(
                  !busy && !filtered.length && (
                    <p className="muted">
                      {t(search ? 'Приглашения не найдены' : 'Выданных приглашений пока нет.')}
                    </p>
                  ),
                )}
                {paging.items.map((row) => {
                  const state = row.consumed_at
                    ? 'Активировано'
                    : row.revoked_at
                      ? 'Отозвано'
                      : new Date(row.expires_at).getTime() <= Date.now()
                        ? 'Истекло'
                        : 'Ожидает активации';
                  return (
                    <article key={row.id}>
                      <div>
                        <strong>{row.email}</strong>
                        <small>
                          {tx(roleLabels[row.role])} · {tx(row.department)}
                        </small>
                        <small>
                          {tx(state)}
                          {t(' · до ')}
                          {tx(formatDate(row.expires_at))}
                        </small>
                        <small>{tx(mailLabels[row.email_status || 'not_sent'])}</small>
                      </div>
                      {state === 'Ожидает активации' && live && (
                        <button
                          className="btn btn-secondary"
                          disabled={
                            busy ||
                            Boolean(
                              row.email_attempted_at &&
                                now < new Date(row.email_attempted_at).getTime() + 60000,
                            )
                          }
                          onClick={() => sendEmail(row.id)}
                        >
                          {t('Отправить новый код')}
                        </button>
                      )}
                      {tx(
                        state === 'Ожидает активации' && (
                          <button
                            className="btn btn-ghost"
                            disabled={busy}
                            onClick={() => revoke(row.id)}
                          >
                            {t('Отозвать')}
                          </button>
                        ),
                      )}
                    </article>
                  );
                })}
              </div>
              <ListPager {...paging} />
            </>
          )}
        </>
      )}
      {tx(
        error && (
          <div className="inline-error" role="alert">
            {tx(error)}
            {tx(
              view === 'list' && (
                <button className="text-link" onClick={() => setListVersion((value) => value + 1)}>
                  {t('Повторить')}
                </button>
              ),
            )}
          </div>
        ),
      )}
    </Modal>
  );
}
