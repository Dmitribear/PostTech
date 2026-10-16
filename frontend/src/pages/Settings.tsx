import { useState } from 'react';
import { Link } from 'react-router-dom';
import { usePortal } from '../context';
import { Icon, PageHeader } from '../components/ui';
import { roleLabels } from '../lib/format';
import './support.css';

export default function Settings() {
  const { profile, mode, logout, notify } = usePortal();
  const [compact, setCompact] = useState(() => { try { return localStorage.getItem('posttech.density') === 'compact'; } catch { return document.body.dataset.density === 'compact'; } });
  function changeDensity(value: boolean) {
    setCompact(value); document.body.dataset.density = value ? 'compact' : 'comfortable';
    try { localStorage.setItem('posttech.density', value ? 'compact' : 'comfortable'); notify('Вид интерфейса сохранён на этом устройстве.'); }
    catch { notify('Вид изменён для текущей сессии. Браузер не разрешил сохранить настройку.'); }
  }
  return <div className="support-page support-settings"><PageHeader title="Настройки" description="Настройте рабочее пространство под себя" eyebrow="Личный кабинет" />
    <section className="card support-settings-section"><h2>Внешний вид</h2><p>Настройки отображения сохраняются только в этом браузере.</p><div className="support-setting-row"><div><h3 id="density-label">Компактный интерфейс</h3><p id="density-description">Уменьшить отступы в карточках и списках, чтобы видеть больше информации.</p></div><input className="support-switch" type="checkbox" role="switch" aria-labelledby="density-label" aria-describedby="density-description" checked={compact} onChange={event => changeDensity(event.target.checked)} /></div><div className="support-setting-row"><div><h3>Язык интерфейса</h3><p>Русский</p></div><span className="support-profile-role">RU</span></div></section>
    <section className="card support-settings-section"><h2>Учётная запись</h2><p>Информация о вашем доступе к порталу.</p><div className="support-setting-row"><div><h3>Рабочая почта</h3><p>{profile.email}</p></div><Icon name="mail" size={19} /></div><div className="support-setting-row"><div><h3>Роль</h3><p>{roleLabels[profile.role]}</p></div><Icon name="shield" size={19} /></div><div className="support-setting-row"><div><h3>Кадровые данные</h3><p>Имя, должность и подразделение обновляются через HR-отдел.</p></div><Link className="btn btn-secondary" to="/profile">Мой профиль<Icon name="arrow-right" size={14} /></Link></div></section>
    <section className="card support-settings-section"><h2>Сеанс работы</h2><p>{mode === 'demo' ? 'Открыта демонстрационная версия с примером данных.' : 'Вы вошли в рабочий портал PostTech.'}</p><div className="support-setting-row"><div><h3>{mode === 'demo' ? 'Завершить демонстрацию' : 'Выйти из аккаунта'}</h3><p>{mode === 'demo' ? 'Вернуться на страницу входа и выбрать другой режим.' : 'Для следующего входа понадобятся email и пароль.'}</p></div><button className="btn btn-secondary" onClick={logout}><Icon name="logout" size={16} />Выйти</button></div></section>
    <div className="support-note"><Icon name="lock" size={18} /><p>Управление ролями и официальными кадровыми сведениями выполняется в учётной системе компании. Портал показывает данные в пределах вашего доступа.</p></div>
  </div>;
}
