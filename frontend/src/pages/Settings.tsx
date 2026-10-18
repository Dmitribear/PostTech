import { t, tx } from '../lib/i18n';
import { LanguageSwitch } from '../lib/i18n';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { usePortal } from '../context';
import { Icon, PageHeader } from '../components/ui';
import { roleLabels } from '../lib/format';
import TelegramSettings from '../components/TelegramSettings';
import './support.css';

export default function Settings() {
  const { profile, mode, logout, notify } = usePortal();
  const [compact, setCompact] = useState(() => { try { return localStorage.getItem('posttech.density') === 'compact'; } catch { return document.body.dataset.density === 'compact'; } });
  function changeDensity(value: boolean) {
    setCompact(value); document.body.dataset.density = value ? 'compact' : 'comfortable';
    try { localStorage.setItem('posttech.density', value ? 'compact' : 'comfortable'); notify('Вид интерфейса сохранён на этом устройстве.'); }
    catch { notify('Вид изменён для текущей сессии. Браузер не разрешил сохранить настройку.'); }
  }
  return <div className="support-page support-settings"><PageHeader title={t("Настройки")} description=""  />
    <section className="card support-settings-section"><h2>{t("Внешний вид")}</h2><p>{t("Для этого устройства.")}</p><div className="support-setting-row"><div><h3 id="density-label">{t("Компактный интерфейс")}</h3><p id="density-description">{t("Меньше отступов, больше информации.")}</p></div><input className="support-switch" type="checkbox" role="switch" aria-labelledby="density-label" aria-describedby="density-description" checked={compact} onChange={event => changeDensity(event.target.checked)} /></div><div className="support-setting-row"><div><h3>{t("Язык интерфейса")}</h3></div><LanguageSwitch /></div></section>
    <section className="card support-settings-section"><h2>{t("Учётная запись")}</h2><div className="support-setting-row"><div><h3>{t("Рабочая почта")}</h3><p>{profile.email}</p></div><Icon name="mail" size={19} /></div><div className="support-setting-row"><div><h3>{t("Роль")}</h3><p>{tx(roleLabels[profile.role])}</p></div><Icon name="shield" size={19} /></div><div className="support-setting-row"><div><h3>{t("Кадровые данные")}</h3><p>{t("Изменение данных — через HR.")}</p></div><Link className="btn btn-secondary" to="/profile">{t("Мой профиль")}<Icon name="arrow-right" size={14} /></Link></div></section>
    <TelegramSettings />
    <section className="card support-settings-section"><h2>{t("Сеанс работы")}</h2><p>{tx(mode === 'demo' ? 'Открыта демонстрационная версия с примером данных.' : 'Вы вошли в рабочий портал PostTech.')}</p><div className="support-setting-row"><div><h3>{tx(mode === 'demo' ? 'Завершить демонстрацию' : 'Выйти из аккаунта')}</h3><p>{tx(mode === 'demo' ? 'Вернуться на страницу входа и выбрать другой режим.' : 'Следующий вход — по почте и паролю.')}</p></div><button className="btn btn-secondary" onClick={logout}><Icon name="logout" size={16} />{t("Выйти")}</button></div></section>
    <div className="support-note"><Icon name="lock" size={18} /><p>{t("Права и рабочие данные обновляет HR.")}</p></div>
  </div>;
}
