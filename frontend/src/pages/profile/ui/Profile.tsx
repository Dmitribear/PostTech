import { ProfileFields } from '@/entities/employee';
import { usePortal } from '@/entities/session';
import { LeaveBalance } from '@/features/leave-balance';
import { formatDate, roleLabels } from '@/shared/lib/format';
import { t, tx } from '@/shared/lib/i18n';
import '@/shared/styles/support.css';
import { Avatar, Icon, PageHeader } from '@/shared/ui/index';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

export default function Profile() {
  const { profile } = usePortal();
  const [compact, setCompact] = useState(() => window.matchMedia('(max-width: 900px)').matches);
  const [expanded, setExpanded] = useState<'personal' | 'work' | null>(null);
  useEffect(() => {
    const query = window.matchMedia('(max-width: 900px)');
    const update = () => setCompact(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return (
    <div className="support-page support-profile-page">
      <PageHeader
        title={t('Мой профиль')}
        actions={
          <Link className="btn btn-secondary" to="/settings">
            <Icon name="settings" size={17} />
            {t('Настройки')}
          </Link>
        }
      />
      <div className="support-profile-layout">
        <div className="support-profile-side">
          <section className="card support-profile-summary">
            <div className="support-profile-person">
              <Avatar name={profile.full_name} size={72} />
              <div>
                <h2>{profile.full_name}</h2>
                <span className="support-profile-role">{tx(roleLabels[profile.role])}</span>
                <p>{tx(profile.job_title || profile.department)}</p>
              </div>
            </div>
            <div className="support-profile-leave">
              <div>
                <LeaveBalance compact />
              </div>
              <span className="support-profile-leave-icon">
                <Icon name="plane" size={27} />
              </span>
            </div>
            <Link className="btn btn-primary" to="/calendar?select=1">
              {t('Оформить отпуск')}
              <Icon name="arrow-right" size={16} />
            </Link>
          </section>
          <nav className="card support-profile-links" aria-label={t('Личные разделы')}>
            <Link to="/requests?scope=mine">
              <Icon name="clipboard" size={19} />
              <span>{t('Мои заявки')}</span>
              <Icon name="chevron-right" size={16} />
            </Link>
            <Link to="/academy">
              <Icon name="graduation" size={19} />
              <span>{t('Моё обучение')}</span>
              <Icon name="chevron-right" size={16} />
            </Link>
            <Link to="/notifications">
              <Icon name="bell" size={19} />
              <span>{t('Уведомления')}</span>
              <Icon name="chevron-right" size={16} />
            </Link>
          </nav>
        </div>
        <div className="support-profile-data">
          {tx(
            (['personal', 'work'] as const).map((section) => (
              <section className="card support-profile-info" key={section}>
                {tx(
                  compact ? (
                    <h2>
                      <button
                        className="support-profile-section-toggle"
                        aria-expanded={expanded === section}
                        aria-controls={`profile-${section}`}
                        onClick={() => setExpanded((value) => (value === section ? null : section))}
                      >
                        <Icon name={section === 'personal' ? 'user' : 'briefcase'} size={19} />
                        <span>
                          {tx(section === 'personal' ? 'Личные данные' : 'Данные о работе')}
                        </span>
                        <Icon
                          name={expanded === section ? 'chevron-down' : 'chevron-right'}
                          size={17}
                        />
                      </button>
                    </h2>
                  ) : (
                    <h2>
                      <Icon name={section === 'personal' ? 'user' : 'briefcase'} size={19} />
                      {tx(section === 'personal' ? 'Личные данные' : 'Данные о работе')}
                    </h2>
                  ),
                )}
                <div id={`profile-${section}`} hidden={compact && expanded !== section}>
                  <ProfileFields profile={profile} section={section} />
                </div>
              </section>
            )),
          )}
          <nav className="support-profile-mobile-links" aria-label={t('Профиль')}>
            <Link to="/activity">
              <Icon name="clock" size={19} />
              <span>{t('История')}</span>
              <Icon name="chevron-right" size={17} />
            </Link>
            <Link to="/settings">
              <Icon name="settings" size={19} />
              <span>{t('Настройки')}</span>
              <Icon name="chevron-right" size={17} />
            </Link>
          </nav>
          <details className="support-profile-source">
            <summary>
              <Icon name="lock" size={14} />
              {t('Данные обновляет HR')}
              <Icon name="chevron-down" size={14} />
            </summary>
            <p>{t('Если заметили ошибку, обратитесь в HR.')}</p>
            <div className="support-source">
              <span>
                {t('Источник: ')}
                <b>{tx(profile.external_source || 'Не указан')}</b> ·{' '}
                {tx(
                  formatDate(profile.updated_at, {
                    hour: '2-digit',
                    minute: '2-digit',
                    timeZone: 'Asia/Qyzylorda',
                  }),
                )}
              </span>
            </div>
          </details>
        </div>
      </div>
    </div>
  );
}
