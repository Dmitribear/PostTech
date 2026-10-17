import { t, tx } from './lib/i18n';
import { LanguageSwitch, useLocale } from './lib/i18n';
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { createLiveApi } from './lib/api';
import Auth from './pages/Auth';
import { Brand } from './components/Brand';
import { createDemoApi } from './lib/demo';
import { LocalDemoJana } from './lib/localJana';
import type { AppRole, EmployeeProfile, HrApi } from './lib/types';
import { PortalContext, usePortal } from './context';
import { Avatar, ErrorState, Icon, LoadingState } from './components/ui';
import Dashboard, { Services, ActivityPage } from './pages/Dashboard';
import { Help, HrTools } from './pages/WorkspaceLinks';
const Requests = lazy(() => import('./pages/Requests'));
const Calendar = lazy(() => import('./pages/Calendar'));
const Academy = lazy(() => import('./pages/Academy'));
const Jana = lazy(() => import('./pages/Jana'));
const Profile = lazy(() => import('./pages/Profile'));
const Notifications = lazy(() => import('./pages/Notifications'));
const Team = lazy(() => import('./pages/Team'));
const Support = lazy(() => import('./pages/Workspace'));
const Delegations = lazy(() => import('./pages/Workspace').then(m => ({ default: m.Delegations })));
const Operations = lazy(() => import('./pages/Operations'));
const CourseEditor = lazy(() => import('./pages/CourseEditor'));
const Settings = lazy(() => import('./pages/Settings'));

const live = createLiveApi({ baseUrl: import.meta.env.VITE_API_BASE_URL || '/api/v1' });

const demoJana = import.meta.env.DEV && import.meta.env.VITE_DEMO_JANA_PROXY === '/jana-demo' ? new LocalDemoJana('/jana-demo') : undefined;
function savedDemoRole(): AppRole | null {
  try { const role = sessionStorage.getItem('posttech.demo-role'); return role === 'worker' || role === 'manager' || role === 'director' || role === 'hr_admin' ? role : null; } catch { return null; }
}


export default function App() {
  const locale = useLocale();
  const [api, setApi] = useState<HrApi | null>(() => { const role = savedDemoRole(); return role ? createDemoApi(role, demoJana) : live.getSession() ? live : null; });
  const [profile, setProfile] = useState<EmployeeProfile | null>(null);
  const [loading, setLoading] = useState(Boolean(api));
  const [error, setError] = useState<unknown>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [profileAttempt, setProfileAttempt] = useState(0);
  const [toast, setToast] = useState('');
  const signingOut = useRef(false);
  const navigate = useNavigate();
  const location = useLocation();
  const logout = useCallback(() => { signingOut.current = true; live.logout(); try { sessionStorage.removeItem('posttech.demo-role'); } catch {} setApi(null); setProfile(null); setError(null); setToast(''); navigate('/login', { replace: true }); signingOut.current = false; }, [navigate]);
  useEffect(() => live.subscribeSession(session => { if (!session && api?.mode === 'live' && !signingOut.current) { setApi(null); setProfile(null); setToast('Сессия завершена. Войдите снова.'); } }), [api]);
  useEffect(() => {
    if (!api) { setLoading(false); return; }
    let cancelled = false; setLoading(true); setError(null);
    api.getProfile().then(result => { if (!cancelled) setProfile(result); }).catch(err => { if (!cancelled) setError(err); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [api, profileAttempt]);
  useEffect(() => { if (!toast) return; const timer = window.setTimeout(() => setToast(''), 5000); return () => clearTimeout(timer); }, [toast]);
  useEffect(() => {
    if (!api) return;
    const update = () => { if (document.visibilityState === 'visible') setRefreshKey(value => value + 1); };
    window.addEventListener('focus', update);
    document.addEventListener('visibilitychange', update);
    return () => { window.removeEventListener('focus', update); document.removeEventListener('visibilitychange', update); };
  }, [api]);
  useEffect(() => {
    if (!api || refreshKey === 0) return;
    let active = true;
    api.getProfile().then(value => { if (active) setProfile(value); }).catch(() => { if (active) setToast('Не удалось обновить профиль. Обновите страницу, чтобы проверить остаток отпуска.'); });
    return () => { active = false; };
  }, [api, refreshKey]);
  const loginDone = () => { setApi(live); if (location.pathname === '/login') navigate('/', { replace: true }); };
  const enterDemo = (role: AppRole) => { try { sessionStorage.setItem('posttech.demo-role', role); } catch {} setProfile(null); setApi(createDemoApi(role, demoJana)); navigate('/', { replace: true }); };
  if (!api) return <><Auth api={live} onLogin={loginDone} onDemo={enterDemo} />{tx(toast && <div className="toast" role="status">{tx(toast)}</div>)}</>;
  if (loading) return <div className="boot-screen"><Brand /><LoadingState /></div>;
  if (error || !profile) return <div className="boot-screen"><Brand /><div className="card boot-error"><ErrorState error={error || 'Профиль не найден'} retry={() => setProfileAttempt(v => v + 1)} /><p>{t("Для доступа к порталу HR должен связать вашу учётную запись с профилем сотрудника.")}</p><button className="btn btn-secondary" onClick={logout}>{t("Вернуться ко входу")}</button></div></div>;
  return <PortalContext.Provider value={{ api, profile, mode: api.mode, refreshKey, refresh: () => setRefreshKey(v => v + 1), notify: setToast, logout }}><Shell key={locale} />{tx(toast && <div className="toast" role="status"><Icon name="check-circle" size={18} />{tx(toast)}<button aria-label={t("Закрыть уведомление")} onClick={() => setToast('')}><Icon name="x" size={16} /></button></div>)}</PortalContext.Provider>;
}


const personalNav = [['/', 'home', 'Главная'], ['/requests', 'clipboard', 'Заявки'], ['/academy', 'graduation', 'Обучение']];
const helpNav = ['/help', 'help', 'Помощь'];
function Shell() {
  const { profile, api, mode, logout, refreshKey } = usePortal();
  const [open, setOpen] = useState(false);
  const [janaOpen, setJanaOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [workspace, setWorkspace] = useState<'personal' | 'team'>(() => { try { return sessionStorage.getItem(`posttech.workspace:${profile.id}`) === 'team' ? 'team' : 'personal'; } catch { return 'personal'; } });
  const account = useRef<HTMLDetailsElement>(null);
  const sidebar = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const janaLauncher = useRef<HTMLButtonElement>(null);
  const location = useLocation();
  const navigate = useNavigate();
  useLayoutEffect(() => { setOpen(false); setJanaOpen(false); if (account.current) account.current.open = false; window.scrollTo(0, 0); }, [location.pathname, location.search]);
  useEffect(() => {
    const dismiss = (event: PointerEvent) => { if (account.current && !account.current.contains(event.target as Node)) account.current.open = false; };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape' && account.current?.open) { account.current.open = false; account.current.querySelector('summary')?.focus(); } };
    document.addEventListener('pointerdown', dismiss); document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', dismiss); document.removeEventListener('keydown', escape); };
  }, []);
  useEffect(() => {
    if (!open) return;
    const before = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const items = () => Array.from(sidebar.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled])') || []).filter(el => el.getClientRects().length);
    items()[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); menuButton.current?.focus(); }
      if (event.key !== 'Tab') return;
      const targets = items(); const first = targets[0]; const last = targets[targets.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    const desktop = window.matchMedia('(min-width: 901px)');
    const closeOnDesktop = () => { if (desktop.matches) setOpen(false); };
    document.addEventListener('keydown', onKey); desktop.addEventListener('change', closeOnDesktop);
    return () => { document.body.style.overflow = before; document.removeEventListener('keydown', onKey); desktop.removeEventListener('change', closeOnDesktop); };
  }, [open]);
  useEffect(() => {
    if (!janaOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setJanaOpen(false);
        janaLauncher.current?.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [janaOpen]);
  useEffect(() => { let active = true; api.getNotifications({ unread_only: true, limit: 100 }).then(n => { if (active) setUnread(n.length); }).catch(() => {}); return () => { active = false; }; }, [api, refreshKey, location.pathname]);
  const review = location.pathname === '/requests' && location.search.includes('scope=review');
  const teamLearning = location.pathname === '/academy' && location.search.includes('tab=team');
  const teamRoute = review || teamLearning || ['/team', '/operations', '/hr-tools', '/delegations', '/course-editor'].some(path => location.pathname.startsWith(path));
  const personalRoute = ['/', '/requests', '/requests/new', '/academy', '/calendar', '/profile'].includes(location.pathname) && !teamRoute;
  const inTeam = profile.role !== 'worker' && (teamRoute || (!personalRoute && workspace === 'team'));
  useEffect(() => { if (teamRoute) setWorkspace('team'); else if (personalRoute) setWorkspace('personal'); }, [teamRoute, personalRoute]);
  useEffect(() => { try { sessionStorage.setItem(`posttech.workspace:${profile.id}`, inTeam ? 'team' : 'personal'); } catch {} }, [inTeam, profile.id]);
  const teamNav = profile.role === 'hr_admin'
    ? [['/team', 'users', 'Сотрудники'], ['/requests?scope=review', 'clipboard', 'Заявки'], ['/academy?tab=team', 'graduation', 'Обучение']]
    : [['/requests?scope=review', 'check-circle', 'Согласования'], ['/team', 'users', 'Команда'], ['/academy?tab=team', 'graduation', 'Обучение']];
  const nav = inTeam ? teamNav : personalNav;
  const mobileNav = [...nav, helpNav];
  const activePath = (path: string) => path === '/help' ? ['/help', '/jana', '/support'].includes(location.pathname)
    : path.includes('scope=review') ? review || (inTeam && location.pathname.startsWith('/requests/'))
    : path.includes('tab=team') ? teamLearning
    : path === '/' ? location.pathname === '/' : location.pathname.startsWith(path);
  const workspaceSwitch = (className: string) => profile.role !== 'worker' && <div className={`workspace-switch ${className}`} role="group" aria-label={t('Рабочее пространство')}><button aria-pressed={!inTeam} onClick={() => { setWorkspace('personal'); navigate('/'); }}>{t('Личное')}</button><button aria-pressed={inTeam} onClick={() => { setWorkspace('team'); navigate(profile.role === 'hr_admin' ? '/team' : '/requests?scope=review'); }}>{t(profile.role === 'hr_admin' ? 'HR' : 'Команда')}</button></div>;
  const closeMenu = () => { setOpen(false); menuButton.current?.focus(); };
  return <div className="portal quiet-workspace">
    <a className="skip-link" href="#main-content">{t("Перейти к содержимому")}</a>
    {tx(open && <button className="sidebar-overlay" aria-label={t("Закрыть меню")} onClick={closeMenu} tabIndex={-1} />)}
    <aside id="workspace-navigation" ref={sidebar} className={`sidebar ${open ? 'is-open' : ''}`}>
      <div className="sidebar-heading"><Link to="/" className="brand-link" aria-label={t("PostTech — главная")}><Brand /></Link><button className="icon-btn sidebar-close" aria-label={t("Закрыть меню")} onClick={closeMenu}><Icon name="x" /></button></div>
      {workspaceSwitch('workspace-switch-desktop')}
      <nav aria-label={t("Главная навигация")}>{nav.map(([path, icon, label]) => <Link key={path} to={path} aria-current={activePath(path) ? 'page' : undefined} className={`nav-item ${activePath(path) ? 'active' : ''}`}><Icon name={icon} /><span>{t(label)}</span></Link>)}</nav>
      <div className="sidebar-bottom">{inTeam && profile.role === 'hr_admin' && <Link className={`nav-item ${location.pathname === '/hr-tools' ? 'active' : ''}`} to="/hr-tools"><Icon name="settings" /><span>{t('Инструменты HR')}</span></Link>}<Link className={`nav-item ${activePath('/help') ? 'active' : ''}`} to="/help"><Icon name="help" /><span>{t('Помощь')}</span></Link></div>
    </aside>
    <div className="main-shell">
      <header className="topbar">
        <div className="topbar-left"><button ref={menuButton} className="icon-btn menu-toggle" aria-label={t("Открыть меню")} aria-controls="workspace-navigation" aria-expanded={open} onClick={() => setOpen(v => !v)}><Icon name="menu" /></button><Link to="/" className="mobile-brand" aria-label={t("PostTech — главная")}><Brand /></Link><span className="workspace-label">{t(inTeam ? profile.role === 'hr_admin' ? 'HR' : 'Моя команда' : 'Личный кабинет')}</span></div>
        <div className="topbar-right"><Link className="icon-btn notification-button" aria-label={`Уведомления: ${unread} непрочитанных`} to="/notifications"><Icon name="bell" size={22} />{unread > 0 && <span className="unread-dot" />}</Link><details ref={account} className="account-menu"><summary className="user-menu" aria-label={t('Меню профиля')}><Avatar name={profile.full_name} size={36} /><span className="user-copy"><strong>{profile.full_name}</strong></span><Icon name="chevron-down" size={16} /></summary><div className="account-popover"><p>{profile.full_name}</p><Link to="/profile"><Icon name="user" size={18} />{t('Мой профиль')}</Link><Link to="/calendar"><Icon name="calendar" size={18} />{t('Календарь')}</Link><Link to="/settings"><Icon name="settings" size={18} />{t('Настройки')}</Link>{profile.role === 'hr_admin' && <Link to="/hr-tools"><Icon name="briefcase" size={18} />{t('Инструменты HR')}</Link>}<div className="account-language"><span>{t('Язык')}</span><LanguageSwitch /></div><button onClick={logout}><Icon name="logout" size={18} />{t(mode === 'demo' ? 'Сменить роль' : 'Выйти')}</button></div></details></div>
      </header>
      {tx(mode === 'demo' && <div className="demo-banner"><span><span className="dot dot-amber" />{t("Демоверсия")}</span><button onClick={logout}>{t("Сменить роль")}<Icon name="arrow-right" size={14} /></button></div>)}
      {workspaceSwitch('workspace-switch-mobile')}
      <main id="main-content" className="main-content"><Suspense fallback={<LoadingState />}><Routes>
        <Route path="/" element={<Dashboard />} /><Route path="/help" element={<Help />} /><Route path="/hr-tools" element={profile.role === 'hr_admin' ? <HrTools /> : <Navigate to="/" replace />} /><Route path="/services" element={<Services />} /><Route path="/activity" element={<ActivityPage />} />
        <Route path="/requests/*" element={<Requests />} /><Route path="/calendar" element={<Calendar />} /><Route path="/academy/*" element={<Academy />} /><Route path="/jana" element={<Jana />} /><Route path="/profile/*" element={<Profile />} /><Route path="/notifications" element={<Notifications />} />
        <Route path="/team/*" element={profile.role === 'worker' ? <Navigate to="/" replace /> : <Team />} /><Route path="/settings" element={<Settings />} /><Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="/operations" element={profile.role === 'hr_admin' ? <Operations /> : <Navigate to="/" />} /><Route path="/support" element={<Support />} /><Route path="/delegations" element={profile.role === 'hr_admin' ? <Delegations /> : <Navigate to="/" />} /><Route path="/course-editor" element={profile.role === 'hr_admin' ? <CourseEditor /> : <Navigate to="/" />} />
        <Route path="*" element={<div className="empty-state"><h1>{t("Страница не найдена")}</h1><Link to="/" className="btn btn-primary">{t("На главную")}</Link></div>} />
      </Routes></Suspense></main>
      <nav className="mobile-bottom-nav" aria-label={t("Быстрая навигация")}>{mobileNav.map(([path, icon, label]) => <Link key={path} to={path} aria-current={activePath(path) ? 'page' : undefined} className={activePath(path) ? 'active' : ''}><Icon name={icon} size={21} /><span>{t(label)}</span></Link>)}</nav>
    </div>
    {!location.pathname.startsWith('/jana') && <>
      {janaOpen && <div id="jana-floating-chat" className="jana-widget" role="dialog" aria-label={t("Чат с AI Jana")}>
        <Suspense fallback={<div className="jana-widget-loading"><LoadingState /></div>}>
          <Jana embedded onClose={() => { setJanaOpen(false); janaLauncher.current?.focus(); }} />
        </Suspense>
      </div>}
      <button ref={janaLauncher} type="button" className="jana-launcher" onClick={() => setJanaOpen(value => !value)} aria-label={t(janaOpen ? "Закрыть AI Jana" : "Открыть AI Jana")} title={t(janaOpen ? "Закрыть AI Jana" : "Открыть AI Jana")} aria-expanded={janaOpen} aria-controls="jana-floating-chat">
        <Icon name={janaOpen ? 'x' : 'bot'} size={25} />
      </button>
    </>}
  </div>;
}
