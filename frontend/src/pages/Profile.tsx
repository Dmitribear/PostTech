import { Link } from 'react-router-dom';
import { usePortal } from '../context';
import { Avatar, Icon, PageHeader } from '../components/ui';
import { formatDate, roleLabels } from '../lib/format';
import type { EmployeeProfile } from '../lib/types';
import './support.css';

export function ProfileFields({ profile }: { profile: EmployeeProfile }) {
  const fields = [
    ['ФИО', profile.full_name], ['Табельный номер', profile.employee_code],
    ['Рабочая почта', profile.email], ['Компания', profile.company],
    ['Должность', profile.job_title], ['Подразделение', profile.department],
    ['Дата приёма', formatDate(profile.hired_at)], ['Роль в портале', roleLabels[profile.role]],
  ];
  return <dl className="support-details-grid">{fields.map(([title, value]) => <div key={title}><dt>{title}</dt><dd>{value || 'Не указано'}</dd></div>)}</dl>;
}

export default function Profile() {
  const { profile, mode } = usePortal();
  return <div className="support-page">
    <PageHeader title="Мой профиль" description="Ваши кадровые данные и информация о работе" eyebrow="Личный кабинет" actions={<span className="support-profile-role"><Icon name="lock" size={13} />Только для чтения</span>} />
    <div className="support-profile-layout"><section className="card support-profile-summary"><Avatar name={profile.full_name} size={76} /><h2>{profile.full_name}</h2><p>{profile.job_title}<br />{profile.department}</p><span className="support-profile-role"><Icon name="user" size={13} />{roleLabels[profile.role]}</span><div className="support-profile-divider" /><span className="support-profile-stat">{Number(profile.vacation_days_remaining).toLocaleString('ru-RU')}</span><p>дней отпуска доступно</p><Link className="btn btn-primary" to="/requests/new?type=leave"><Icon name="plane" size={16} />Оформить отпуск</Link><div className="support-profile-divider" /><p style={{ marginBottom: 0 }}>В команде {profile.company}<br />с {formatDate(profile.hired_at)}</p></section>
      <div className="stack"><section className="card support-profile-info"><h2>Кадровая информация</h2><p>Сведения из учётной системы компании</p><ProfileFields profile={profile} /><div className="support-source" style={{ marginTop: 20 }}><Icon name="activity" size={14} /><span>Источник: <b>{profile.external_source || 'Не указан'}</b> · обновлено {formatDate(profile.updated_at, { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Qyzylorda' })}</span></div></section><div className="support-note"><Icon name="lock" size={18} /><p>Официальные кадровые сведения доступны для просмотра. Если вы заметили неточность в имени, должности или подразделении, обратитесь в HR-отдел для исправления в учётной системе.</p></div>{mode === 'demo' && <div className="support-note warning"><Icon name="info" size={17} /><p>Вы просматриваете демонстрационный профиль. Эти данные не связаны с кадровой системой компании.</p></div>}</div>
    </div>
  </div>;
}
