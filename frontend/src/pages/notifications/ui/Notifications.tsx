import { usePortal } from '@/entities/session';
import { errorMessage } from '@/shared/api/api';
import type { Notification } from '@/shared/api/contracts';
import { formatDate, notificationHref } from '@/shared/lib/format';
import { t, tx } from '@/shared/lib/i18n';
import { watchVisible } from '@/shared/lib/live-refresh';
import '@/shared/styles/support.css';
import { EmptyState, ErrorState, Icon, LoadingState, PageHeader } from '@/shared/ui/index';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

const PAGE_SIZE = 25;
export default function Notifications() {
  const { api, refresh, notify } = usePortal();
  const [items, setItems] = useState<Notification[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState('');
  const [retry, setRetry] = useState(0);
  const [pending, setPending] = useState<string[]>([]);
  const generation = useRef(0);
  const loadedCount = useRef(PAGE_SIZE);
  const mutations = useRef(0);
  const revision = useRef(0);
  useEffect(() => {
    const current = ++generation.current;
    loadedCount.current = PAGE_SIZE;
    let loaded = false;
    setLoading(true);
    setError(null);
    setActionError('');
    setItems([]);
    setLoadingMore(false);
    const stop = watchVisible(async (signal) => {
      if (mutations.current) return;
      const version = revision.current;
      try {
        const value: Notification[] = [];
        let more = true;
        for (let offset = 0; offset < loadedCount.current && more; offset += PAGE_SIZE) {
          const batch = await api.getNotifications({
            unread_only: unreadOnly,
            limit: PAGE_SIZE,
            offset,
          });
          value.push(...batch);
          more = batch.length === PAGE_SIZE;
          if (signal.aborted || version !== revision.current) return;
        }
        if (!signal.aborted && generation.current === current && version === revision.current) {
          setItems([...new Map(value.map((item) => [item.id, item])).values()]);
          setHasMore(more);
          setError(null);
          loaded = true;
        }
      } catch (err) {
        if (!signal.aborted && !loaded) setError(err);
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    });
    return () => {
      stop();
      generation.current += 1;
    };
  }, [api, unreadOnly, retry]);
  async function loadMore() {
    if (loadingMore || pending.length) return;
    const current = generation.current;
    mutations.current += 1;
    revision.current += 1;
    setLoadingMore(true);
    setActionError('');
    try {
      const next = await api.getNotifications({
        unread_only: unreadOnly,
        limit: PAGE_SIZE,
        offset: items.length,
      });
      if (current === generation.current) {
        loadedCount.current += PAGE_SIZE;
        setItems((previous) => [
          ...previous,
          ...next.filter((item) => !previous.some((existing) => existing.id === item.id)),
        ]);
        setHasMore(next.length === PAGE_SIZE);
      }
    } catch (err) {
      if (current === generation.current) setActionError(errorMessage(err));
    } finally {
      mutations.current -= 1;
      if (current === generation.current) setLoadingMore(false);
    }
  }
  async function markRead(item: Notification) {
    if (pending.includes(item.id) || loadingMore) return;
    const current = generation.current;
    mutations.current += 1;
    revision.current += 1;
    setPending((previous) => [...previous, item.id]);
    setActionError('');
    try {
      const updated = await api.markNotificationRead(item.id);
      if (current === generation.current)
        setItems((previous) =>
          unreadOnly
            ? previous.filter((row) => row.id !== item.id)
            : previous.map((row) => (row.id === item.id ? updated : row)),
        );
      refresh();
      notify('Уведомление отмечено прочитанным.');
    } catch (err) {
      if (current === generation.current) setActionError(errorMessage(err));
    } finally {
      mutations.current -= 1;
      setPending((previous) => previous.filter((id) => id !== item.id));
    }
  }
  return (
    <div className="support-page">
      <PageHeader
        title={t('Уведомления')}
        description={t('Всё важное — здесь')}
        actions={
          <button
            className="btn btn-secondary"
            onClick={() => setRetry((value) => value + 1)}
            disabled={loading || loadingMore || pending.length > 0}
          >
            <Icon name="refresh" size={16} />
            {t('Обновить')}
          </button>
        }
      />
      <div className="support-toolbar">
        <div className="support-tabs" role="group" aria-label={t('Фильтр уведомлений')}>
          <button
            className="support-tab"
            aria-pressed={!unreadOnly}
            disabled={loadingMore || pending.length > 0}
            onClick={() => setUnreadOnly(false)}
          >
            {t('Все')}
          </button>
          <button
            className="support-tab"
            aria-pressed={unreadOnly}
            disabled={loadingMore || pending.length > 0}
            onClick={() => setUnreadOnly(true)}
          >
            {t('Непрочитанные')}
          </button>
        </div>
      </div>
      {tx(
        actionError && (
          <p className="support-inline-error" role="alert">
            {tx(actionError)}
          </p>
        ),
      )}
      {tx(
        loading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} retry={() => setRetry((value) => value + 1)} />
        ) : !items.length ? (
          <EmptyState
            title={
              hasMore
                ? 'Загрузите следующие уведомления'
                : unreadOnly
                  ? 'Все уведомления прочитаны'
                  : 'Уведомлений пока нет'
            }
            description={
              hasMore ? 'Нажмите «Показать ещё».' : 'Здесь появятся обновления по заявкам и курсам.'
            }
          />
        ) : (
          <section className="card support-notifications-list" aria-label={t('Список уведомлений')}>
            {tx(
              items.map((item) => (
                <article
                  className={`support-notification ${item.read_at ? '' : 'unread'}`}
                  key={item.id}
                >
                  <span className="support-notification-icon">
                    <Icon
                      name={
                        item.notification_type.includes('course') ||
                        item.notification_type.includes('training')
                          ? 'graduation'
                          : item.notification_type.includes('approved')
                            ? 'check-circle'
                            : 'bell'
                      }
                      size={20}
                    />
                  </span>
                  <div className="support-notification-content">
                    <h3>{tx(item.title)}</h3>
                    <div>
                      {tx(item.body)}
                      {item.original_body && (
                        <details>
                          <summary>{t('Оригинал уведомления')}</summary>
                          <p>{item.original_body}</p>
                        </details>
                      )}
                    </div>
                    <time dateTime={item.created_at}>
                      {tx(
                        formatDate(item.created_at, {
                          hour: '2-digit',
                          minute: '2-digit',
                          timeZone: 'Asia/Qyzylorda',
                        }),
                      )}
                    </time>
                    <div className="support-notification-actions">
                      {item.ticket_id && (
                        <Link className="btn btn-secondary" to={notificationHref(item)}>
                          {t('Открыть обращение')}
                        </Link>
                      )}
                      {item.notification_type === 'delegation_assigned' && (
                        <Link className="btn btn-secondary" to={notificationHref(item)}>
                          {t('На согласование')}
                        </Link>
                      )}
                      {tx(
                        item.request_id && (
                          <Link className="btn btn-secondary" to={`/requests/${item.request_id}`}>
                            {t('Открыть заявку')}
                            <Icon name="arrow-right" size={12} />
                          </Link>
                        ),
                      )}
                      {tx(
                        (item.notification_type.includes('course') ||
                          item.notification_type.includes('training')) && (
                          <Link className="btn btn-secondary" to={notificationHref(item)}>
                            {t('К обучению')}
                            <Icon name="arrow-right" size={12} />
                          </Link>
                        ),
                      )}
                      {tx(
                        !item.read_at ? (
                          <button
                            className="btn btn-ghost"
                            aria-label={`Отметить прочитанным: ${item.title}`}
                            title={t('Отметить прочитанным')}
                            disabled={pending.includes(item.id) || loadingMore}
                            onClick={() => void markRead(item)}
                          >
                            <Icon name="check-check" size={14} />
                            {tx(pending.includes(item.id) ? 'Сохраняем…' : 'Прочитано')}
                          </button>
                        ) : (
                          <span className="support-read-state">
                            <Icon name="check-check" size={14} />
                            {t('Прочитано')}
                          </span>
                        ),
                      )}
                    </div>
                  </div>
                  {tx(
                    !item.read_at && (
                      <span className="support-unread-dot" aria-label={t('Непрочитанное')} />
                    ),
                  )}
                </article>
              )),
            )}
          </section>
        ),
      )}
      {tx(
        !loading && !error && hasMore && (
          <div className="support-load-more">
            <button
              className="btn btn-secondary"
              disabled={loadingMore || pending.length > 0}
              onClick={() => void loadMore()}
            >
              {tx(loadingMore ? 'Загружаем…' : 'Показать ещё')}
            </button>
          </div>
        ),
      )}
    </div>
  );
}
