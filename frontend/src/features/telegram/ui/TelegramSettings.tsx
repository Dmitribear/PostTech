import { useEffect, useState } from 'react';
import { usePortal } from '@/entities/session';
import { errorMessage } from '@/shared/api/api';
import { localizedDate, t } from '@/shared/lib/i18n';
import type { TelegramLink, TelegramStatus } from '@/shared/api/contracts';
import { Icon, Modal } from '@/shared/ui/index';
import './telegram-settings.css';

export default function TelegramSettings() {
  const { api, mode, notify } = usePortal();
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [link, setLink] = useState<TelegramLink | null>(null);
  const [now, setNow] = useState(Date.now);
  const [busy, setBusy] = useState<string | null>(mode === 'demo' ? null : 'status');
  const [error, setError] = useState('');
  const [confirmUnlink, setConfirmUnlink] = useState(false);
  const expiresAt = link ? Date.parse(link.expires_at) : 0;
  const expired = Boolean(link && now >= expiresAt);
  const startCommand =
    link && !expired ? `/start ${new URL(link.url).searchParams.get('start')}` : '';

  useEffect(() => {
    let active = true;
    setLink(null);
    setStatus(null);
    setError('');
    if (mode === 'demo') {
      setBusy(null);
      return;
    }
    setBusy('status');
    api
      .getTelegramStatus()
      .then((value) => {
        if (active) setStatus(value);
      })
      .catch((reason) => {
        if (active) setError(errorMessage(reason));
      })
      .finally(() => {
        if (active) setBusy(null);
      });
    return () => {
      active = false;
    };
  }, [api, mode]);

  useEffect(() => {
    if (!link) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [link]);

  async function reload() {
    setBusy('status');
    setError('');
    try {
      const current = await api.getTelegramStatus();
      setStatus(current);
      if (current.linked || !current.enabled) setLink(null);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(null);
    }
  }
  async function createLink() {
    setBusy('link');
    setError('');
    setLink(null);
    try {
      setLink(await api.createTelegramLink());
      setNow(Date.now());
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(null);
    }
  }
  async function toggleNotifications(enabled: boolean) {
    setBusy('notifications');
    setError('');
    try {
      setStatus(await api.setTelegramNotifications(enabled));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(null);
    }
  }
  async function unlink() {
    setBusy('unlink');
    setError('');
    try {
      await api.unlinkTelegram();
      setStatus((previous) =>
        previous
          ? { ...previous, linked: false, telegram_username: null, notifications_enabled: false }
          : null,
      );
      setLink(null);
      setConfirmUnlink(false);
      notify(t('Telegram отключён. Уведомления в бот больше не поступают.'));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(null);
    }
  }
  async function copyLink() {
    if (!link || Date.now() >= expiresAt) return;
    try {
      await navigator.clipboard.writeText(link.url);
      notify(t('Ссылка скопирована. Откройте её только в своём Telegram.'));
    } catch {
      setError(t('Не удалось скопировать. Выделите ссылку в поле и скопируйте вручную.'));
    }
  }
  async function copyCommand() {
    if (!link || !startCommand || Date.now() >= expiresAt) return;
    try {
      await navigator.clipboard.writeText(startCommand);
      notify(t('Команда скопирована. Отправьте её целиком в личный чат с ботом.'));
    } catch {
      setError(t('Не удалось скопировать. Выделите команду в поле и скопируйте вручную.'));
    }
  }

  return (
    <section
      className="card support-settings-section telegram-settings"
      aria-labelledby="telegram-title"
      aria-busy={Boolean(busy)}
    >
      <h2 id="telegram-title">
        <Icon name="send" size={20} />
        Telegram
      </h2>
      <p>
        {t(
          'Один рабочий аккаунт на сайте и в боте: общие заявки, курсы, прогресс обучения и помощник Jana.',
        )}
      </p>
      {mode === 'demo' ? (
        <div className="support-note">
          <Icon name="info" size={18} />
          <p>
            {t(
              'Telegram недоступен в демонстрационном режиме. Войдите в рабочий аккаунт, чтобы подключить бота.',
            )}
          </p>
        </div>
      ) : (
        <>
          <div className="telegram-status-row">
            <p role="status">
              {busy === 'status' ? (
                t('Проверяем подключение…')
              ) : status?.linked ? (
                <>
                  <strong>{t('Telegram подключён')}</strong>
                  {status.telegram_username && <span> @{status.telegram_username}</span>}
                </>
              ) : status?.enabled ? (
                t('Telegram не подключён')
              ) : status ? (
                t('Подключение Telegram ещё не настроено')
              ) : (
                t('Не удалось проверить подключение')
              )}
            </p>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={reload}
              disabled={Boolean(busy)}
            >
              <Icon name="refresh" size={15} />
              {t('Обновить статус')}
            </button>
          </div>
          {error && (
            <p className="support-inline-error" role="alert">
              {error}
            </p>
          )}
          {status && !status.enabled && (
            <div className="support-note">
              <Icon name="info" size={18} />
              <p>
                {t(
                  'Администратору нужно включить бота на сервере. После настройки обновите статус.',
                )}
              </p>
            </div>
          )}
          {status?.enabled && !status.linked && (
            <>
              <div className="telegram-permission">
                <Icon name="shield" size={18} />
                <p>
                  {t(
                    'При подключении Telegram получит уведомления и данные действий, которые вы выполняете в боте. Доступ будет соответствовать вашей роли на сайте. Подключение и уведомления можно отключить здесь в любое время.',
                  )}
                </p>
              </div>
              {(!link || expired) && (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={createLink}
                  disabled={Boolean(busy)}
                >
                  <Icon name="send" size={16} />
                  {busy === 'link' ? t('Создаём ссылку…') : t('Подключить Telegram')}
                </button>
              )}
              {link && (
                <div className="telegram-link-panel">
                  {expired ? (
                    <p role="status">
                      {t('Срок ссылки истёк. Создайте новую ссылку для подключения.')}
                    </p>
                  ) : (
                    <>
                      <p>
                        {t(
                          'Откройте бота по этой ссылке, нажмите «Старт», затем вернитесь сюда и обновите статус.',
                        )}
                      </p>
                      <p className="telegram-link-expiry">
                        {t('Одноразовая ссылка действует до')}{' '}
                        <time dateTime={link.expires_at}>
                          {localizedDate(new Date(link.expires_at), {
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </time>{' '}
                        · {Math.ceil(Math.max(0, expiresAt - now) / 1000)} {t('сек.')}
                      </p>
                      <div className="telegram-actions">
                        <a
                          className="btn btn-primary"
                          href={link.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          referrerPolicy="no-referrer"
                        >
                          <Icon name="send" size={16} />
                          {t('Открыть Telegram')}
                        </a>
                        <button type="button" className="btn btn-secondary" onClick={copyLink}>
                          {t('Скопировать ссылку')}
                        </button>
                      </div>
                      <label className="telegram-link-label" htmlFor="telegram-one-use-link">
                        {t('Личная ссылка подключения — никому не пересылайте')}
                      </label>
                      <input
                        id="telegram-one-use-link"
                        className="telegram-link-input"
                        type="text"
                        readOnly
                        value={link.url}
                        onFocus={(event) => event.target.select()}
                        spellCheck={false}
                        autoComplete="off"
                      />
                      <label className="telegram-link-label" htmlFor="telegram-start-command">
                        {t('Если кнопка не сработала, отправьте боту эту команду целиком')}
                      </label>
                      <input
                        id="telegram-start-command"
                        className="telegram-link-input"
                        type="text"
                        readOnly
                        value={startCommand}
                        onFocus={(event) => event.target.select()}
                        spellCheck={false}
                        autoComplete="off"
                      />
                      <div className="telegram-actions">
                        <button type="button" className="btn btn-secondary" onClick={copyCommand}>
                          {t('Скопировать команду')}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </>
          )}
          {status?.linked && (
            <>
              <div className="support-setting-row">
                <div>
                  <h3 id="telegram-notifications-label">{t('Уведомления в Telegram')}</h3>
                  <p id="telegram-notifications-description">
                    {t(
                      'Новые события по заявкам и обучению. Все уведомления остаются доступны на сайте.',
                    )}
                  </p>
                </div>
                <input
                  type="checkbox"
                  role="switch"
                  className="support-switch"
                  aria-labelledby="telegram-notifications-label"
                  aria-describedby="telegram-notifications-description"
                  checked={status.notifications_enabled}
                  disabled={Boolean(busy) || !status.enabled}
                  onChange={(event) => toggleNotifications(event.target.checked)}
                />
              </div>
              <div className="support-setting-row">
                <div>
                  <h3>{t('Отключить аккаунт')}</h3>
                  <p>
                    {t(
                      'Бот потеряет доступ к вашему рабочему аккаунту. Данные и прогресс на сайте сохранятся.',
                    )}
                  </p>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    setError('');
                    setConfirmUnlink(true);
                  }}
                  disabled={Boolean(busy)}
                >
                  {t('Отключить Telegram')}
                </button>
              </div>
            </>
          )}
        </>
      )}
      {confirmUnlink && (
        <Modal
          title={t('Отключить Telegram?')}
          onClose={() => {
            if (!busy) setConfirmUnlink(false);
          }}
        >
          <p>
            {t(
              'Бот больше не сможет показывать ваши рабочие данные и присылать уведомления. Чтобы подключиться снова, потребуется новая ссылка с сайта.',
            )}
          </p>
          {error && (
            <p className="support-inline-error" role="alert">
              {error}
            </p>
          )}
          <div className="telegram-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setConfirmUnlink(false)}
              disabled={Boolean(busy)}
            >
              {t('Отмена')}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={unlink}
              disabled={Boolean(busy)}
            >
              {busy === 'unlink' ? t('Отключаем…') : t('Отключить Telegram')}
            </button>
          </div>
        </Modal>
      )}
    </section>
  );
}
