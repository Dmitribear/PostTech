import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { createLiveApi, errorMessage } from './lib/api';
import { createDemoApi } from './lib/demo';
import { LocalDemoJana } from './lib/localJana';
import type { AppRole, EmployeeProfile, HrApi } from './lib/types';
import { PortalContext, usePortal } from './context';
import { Avatar, ErrorState, Icon, LoadingState, Modal } from './components/ui';
import Dashboard, { Services, ActivityPage } from './pages/Dashboard';
import Requests from './pages/Requests';
import Calendar from './pages/Calendar';
import Academy from './pages/Academy';
import Jana from './pages/Jana';
import Profile from './pages/Profile';
import Notifications from './pages/Notifications';
import Team from './pages/Team';
import Settings from './pages/Settings';
import './pages/requests.css';
import './pages/support.css';

const live = createLiveApi({ baseUrl: import.meta.env.VITE_API_BASE_URL || '/api/v1' });
const demoJana = import.meta.env.DEV && import.meta.env.VITE_DEMO_JANA_PROXY ? new LocalDemoJana(import.meta.env.VITE_DEMO_JANA_PROXY) : undefined;
const roleNames: Record<AppRole, string> = { worker: 'Сотрудник', manager: 'Руководитель', hr_admin: 'HR-администратор' };
function savedDemoRole(): AppRole | null {
  try { const role = sessionStorage.getItem('posttech.demo-role'); return role === 'worker' || role === 'manager' || role === 'hr_admin' ? role : null; } catch { return null; }
}
export function Brand() {
  return <div className="brand"><span className="brand-mark"><Icon name="truck" size={23} /></span><span><strong>PostTech</strong><small>Jana Post Portal</small></span></div>;
}

export default function App() {
  const [api, setApi] = useState<HrApi | null>(() => { const role = savedDemoRole(); return role ? createDemoApi(role, demoJana) : live.getSession() ? live : null; });
  const [profile, setProfile] = useState<EmployeeProfile | null>(null);
  const [loading, setLoading] = useState(Boolean(api));
  const [error, setError] = useState<unknown>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [profileAttempt, setProfileAttempt] = useState(0);
  const [toast, setToast] = useState('');
  const navigate = useNavigate();
  const location = useLocation();
  const logout = useCallback(() => { live.logout(); try { sessionStorage.removeItem('posttech.demo-role'); } catch {} setApi(null); setProfile(null); setError(null); navigate('/login', { replace: true }); }, [navigate]);
  useEffect(() => live.subscribeSession(session => { if (!session && api?.mode === 'live') { setApi(null); setProfile(null); setToast('Сессия завершена. Войдите снова.'); } }), [api]);
  useEffect(() => {
    if (!api) { setLoading(false); return; }
    let cancelled = false; setLoading(true); setError(null);
    api.getProfile().then(result => { if (!cancelled) setProfile(result); }).catch(err => { if (!cancelled) setError(err); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [api, profileAttempt]);
  useEffect(() => { if (!toast) return; const timer = window.setTimeout(() => setToast(''), 5000); return () => clearTimeout(timer); }, [toast]);
  const loginDone = () => { setApi(live); if (location.pathname === '/login') navigate('/', { replace: true }); };
  const enterDemo = (role: AppRole) => { try { sessionStorage.setItem('posttech.demo-role', role); } catch {} setProfile(null); setApi(createDemoApi(role, demoJana)); navigate('/', { replace: true }); };
  if (!api) return <><Auth onLogin={loginDone} onDemo={enterDemo} />{toast && <div className="toast" role="status">{toast}</div>}</>;
  if (loading) return <div className="boot-screen"><Brand /><LoadingState /></div>;
  if (error || !profile) return <div className="boot-screen"><Brand /><div className="card boot-error"><ErrorState error={error || 'Профиль не найден'} retry={() => setProfileAttempt(v => v + 1)} /><p>Для доступа к порталу HR должен связать вашу учётную запись с профилем сотрудника.</p><button className="btn btn-secondary" onClick={logout}>Вернуться ко входу</button></div></div>;
  return <PortalContext.Provider value={{ api, profile, mode: api.mode, refreshKey, refresh: () => setRefreshKey(v => v + 1), notify: setToast, logout }}><Shell />{toast && <div className="toast" role="status"><Icon name="check-circle" size={18} />{toast}<button aria-label="Закрыть уведомление" onClick={() => setToast('')}><Icon name="x" size={16} /></button></div>}</PortalContext.Provider>;
}

function Auth({ onLogin, onDemo }: { onLogin: () => void; onDemo: (role: AppRole) => void }) {
  const [register, setRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [demoPicker, setDemoPicker] = useState(false);
  const [help, setHelp] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      if (register) { const result = await live.register(email.trim(), password); setNotice(result.email_confirmation_required ? 'Аккаунт создан. Подтвердите почту по ссылке из письма. HR должен связать аккаунт с вашим профилем сотрудника.' : 'Аккаунт создан. Обратитесь в HR для подключения профиля, затем войдите в портал.'); live.logout(); setPassword(''); setRegister(false); }
      else { await live.login(email.trim(), password); onLogin(); }
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  }
  return <div className="auth-page"><header className="auth-header"><Brand /><span className="auth-header-note"><Icon name="shield" size={16} />Корпоративное пространство</span></header><main className="auth-main"><div className="auth-kicker"><span><span className="dot" />JANA POST · DIGITAL HR</span><span>PORTAL 1.0</span></div><section className="auth-card"><Brand /><h1>{register ? 'Активация аккаунта' : 'Добро пожаловать'}</h1><p className="auth-description">{register ? 'Создайте учётную запись для вашего рабочего профиля.' : 'Войдите в ваше рабочее пространство PostTech.'}</p><form onSubmit={submit}><label className="field"><span className="field-label">Корпоративная почта</span><span className="input-wrap"><Icon name="mail" size={18} /><input className="input" type="email" autoComplete="email" placeholder="name@janapost.kz" required maxLength={320} value={email} onChange={e => setEmail(e.target.value)} /></span></label><label className="field"><span className="field-label">Пароль{!register && <button type="button" className="text-link" onClick={() => setHelp(true)}>Забыли пароль?</button>}</span><span className="input-wrap"><Icon name="lock" size={18} /><input className="input" type={showPassword ? 'text' : 'password'} autoComplete={register ? 'new-password' : 'current-password'} placeholder="Не менее 8 символов" required minLength={8} maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /><button type="button" className="password-toggle" aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'} onClick={() => setShowPassword(v => !v)}><Icon name={showPassword ? 'eye-off' : 'eye'} size={18} /></button></span></label>{error && <div className="inline-error" role="alert"><Icon name="alert" size={18} />{error}</div>}{notice && <div className="inline-success" role="status"><Icon name="check-circle" size={18} />{notice}</div>}<button className="btn btn-primary auth-submit" disabled={busy}>{busy ? <span className="spinner" /> : null}{busy ? 'Подождите…' : register ? 'Создать аккаунт' : 'Войти в систему'}{!busy && <Icon name="arrow-right" size={18} />}</button></form><div className="auth-divider"><span>или познакомьтесь с порталом</span></div><button className="btn btn-secondary auth-demo" disabled={busy} onClick={() => setDemoPicker(true)}><Icon name="grid" size={18} />Открыть демоверсию<Icon name="arrow-right" size={16} /></button><div className="auth-bottom"><span>{register ? 'Уже есть аккаунт?' : 'Впервые в PostTech?'}</span><button className="text-link" disabled={busy} onClick={() => { setRegister(v => !v); setError(''); setNotice(''); }}>{register ? 'Войти' : 'Активировать аккаунт'}<Icon name="arrow-right" size={14} /></button></div></section><p className="auth-security"><Icon name="lock" size={13} />Доступ к данным определяется вашим рабочим профилем</p></main><footer className="auth-footer"><span>© {new Date().getFullYear()} PostTech · Jana Post</span><span>Люди. Возможности. Движение вперёд.</span></footer>{help && <Modal title="Восстановление доступа" onClose={() => setHelp(false)}><p>Обратитесь к вашему HR-администратору для сброса пароля. После получения письма восстановления следуйте инструкциям администратора.</p><p className="muted">Самостоятельный сброс пароля и SSO ещё не подключены к порталу.</p><button className="btn btn-primary" onClick={() => setHelp(false)}>Понятно</button></Modal>}{demoPicker && <Modal title="Познакомьтесь с PostTech" onClose={() => setDemoPicker(false)}><p className="muted">Выберите роль для просмотра. Это вымышленные данные: изменения остаются только в демоверсии.</p><div className="demo-roles">{(['worker', 'manager', 'hr_admin'] as AppRole[]).map((role, i) => <button className="demo-role" key={role} onClick={() => onDemo(role)}><span className="action-icon"><Icon name={['user', 'users', 'shield'][i]} /></span><span><strong>{roleNames[role]}</strong><small>{['Заявки, календарь и обучение', 'Команда и согласование заявок', 'Сотрудники, заявки и назначение курсов'][i]}</small></span><Icon name="chevron-right" /></button>)}</div></Modal>}</div>;
}

const nav = [
  ['/', 'home', 'Главная'], ['/requests', 'clipboard', 'Мои заявки'], ['/calendar', 'calendar', 'Календарь'], ['/academy', 'graduation', 'Jana Academy'], ['/jana', 'bot', 'AI Jana'], ['/notifications', 'bell', 'Уведомления'], ['/profile', 'user', 'Мой профиль'], ['/settings', 'settings', 'Настройки'],
];
function Shell() {
  const { profile, api, mode, logout, refreshKey } = usePortal();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [search, setSearch] = useState('');
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => { setOpen(false); window.scrollTo(0, 0); }, [location.pathname]);
  useEffect(() => { let active = true; api.getNotifications({ unread_only: true, limit: 100 }).then(n => { if (active) setUnread(n.length); }).catch(() => {}); return () => { active = false; }; }, [api, refreshKey, location.pathname]);
  const current = nav.find(([path]) => path === '/' ? location.pathname === '/' : location.pathname.startsWith(path))?.[2] || (location.pathname === '/team' ? 'Моя команда' : 'Рабочее пространство');
  return <div className="portal"><a className="skip-link" href="#main-content">Перейти к содержимому</a>{open && <button className="sidebar-overlay" aria-label="Закрыть меню" onClick={() => setOpen(false)} />}<aside className={`sidebar ${open ? 'is-open' : ''}`}><Link to="/" className="brand-link"><Brand /></Link><div className="nav-label">ОПЕРАЦИОННЫЙ ХАБ</div><nav aria-label="Главная навигация">{nav.map(([path, icon, label]) => <NavLink key={path} to={path} end={path === '/'} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}><Icon name={icon} /><span>{label}</span>{path === '/notifications' && unread > 0 && <span className="nav-count">{unread === 100 ? '99+' : unread}</span>}</NavLink>)}{profile.role !== 'worker' && <><div className="nav-label team-nav-label">УПРАВЛЕНИЕ</div><NavLink to="/team" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}><Icon name="users" /><span>{profile.role === 'hr_admin' ? 'Сотрудники' : 'Моя команда'}</span></NavLink></>}</nav><div className="sidebar-bottom"><div className="connection-status"><span className={`dot ${mode === 'demo' ? 'dot-amber' : ''}`} />{mode === 'demo' ? 'Демонстрационный режим' : 'PostTech API · Подключено'}</div><div className="sidebar-meta"><span>Язык интерфейса</span><span className="locale-pill">RU</span></div><button className="logout-button" onClick={logout}><Icon name="logout" size={17} />Выйти{mode === 'demo' ? ' / Сменить роль' : ''}</button></div></aside><div className="main-shell"><header className="topbar"><div className="topbar-left"><button className="icon-btn menu-toggle" aria-label="Открыть меню" aria-expanded={open} onClick={() => setOpen(v => !v)}><Icon name="menu" /></button><div className="breadcrumbs"><Link to="/">Портал</Link><Icon name="chevron-right" size={14} /><span>{current}</span></div><span className="role-pill">{roleNames[profile.role]}</span></div><div className="topbar-right"><form className="global-search" onSubmit={e => { e.preventDefault(); navigate(`/requests?q=${encodeURIComponent(search.trim())}`); setSearch(''); }}><Icon name="search" size={17} /><input aria-label="Поиск по заявкам" placeholder="Поиск по заявкам…" value={search} onChange={e => setSearch(e.target.value)} /><kbd>↵</kbd></form><Link className="icon-btn notification-button" aria-label={`Уведомления: ${unread} непрочитанных`} to="/notifications"><Icon name="bell" size={21} />{unread > 0 && <span>{unread > 9 ? '9+' : unread}</span>}</Link><Link to="/profile" className="user-menu"><span><strong>{profile.full_name}</strong><small>{profile.department}</small></span><Avatar name={profile.full_name} size={36} /></Link></div></header>{mode === 'demo' && <div className="demo-banner"><span><Icon name="info" size={15} />Демоверсия · вымышленные данные</span><button onClick={logout}>Перейти к рабочему входу<Icon name="arrow-right" size={14} /></button></div>}<main id="main-content" className="main-content"><Routes><Route path="/" element={<Dashboard />} /><Route path="/services" element={<Services />} /><Route path="/activity" element={<ActivityPage />} /><Route path="/requests/*" element={<Requests />} /><Route path="/calendar" element={<Calendar />} /><Route path="/academy/*" element={<Academy />} /><Route path="/jana" element={<Jana />} /><Route path="/profile/*" element={<Profile />} /><Route path="/notifications" element={<Notifications />} /><Route path="/team/*" element={profile.role === 'worker' ? <Navigate to="/" replace /> : <Team />} /><Route path="/settings" element={<Settings />} /><Route path="/login" element={<Navigate to="/" replace />} /><Route path="*" element={<div className="empty-state"><h1>Страница не найдена</h1><Link to="/" className="btn btn-primary">На главную</Link></div>} /></Routes></main><footer className="portal-footer"><span>PostTech · Jana Post</span><span>Ваше рабочее пространство</span></footer></div></div>;
}
