import { t, tx } from '../lib/i18n';
import { LanguageSwitch } from '../lib/i18n';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, errorMessage, type LiveApi } from '../lib/api';
import type { AppRole } from '../lib/types';
import { Brand } from '../components/Brand';
import { Icon, Modal } from '../components/ui';
import '../auth.css';

type Stage = 'login' | 'invitation' | 'account' | 'verification' | 'recovery' | 'role' | 'welcome' | 'password-reset' | 'password-reset-confirm' | 'password-reset-success';
type Invitation = { email: string; role: AppRole; department: string; expires_at: string };
const EMAIL_KEY = 'posttech.remembered-email';
const DEMO_INVITE = 'JP-DEMO-2026';
const DEMO_TOKEN = '472916';
const roleOptions: { role: AppRole; title: string; detail: string; icon: string }[] = [
  { role: 'worker', title: 'Сотрудник', detail: 'Мои заявки, календарь, обучение', icon: 'briefcase' },
  { role: 'manager', title: 'Руководитель', detail: 'Согласование, команда, календарь', icon: 'users' },
  { role: 'hr_admin', title: 'HR-администратор', detail: 'Сотрудники, заявки и обучение', icon: 'shield' },
];
function rememberedEmail() { try { return localStorage.getItem(EMAIL_KEY) || ''; } catch { return ''; } }

export default function Auth({ api, onLogin, onDemo }: { api: LiveApi; onLogin: () => void; onDemo: (role: AppRole) => void }) {
  const [stage, setStage] = useState<Stage>('login');
  const [recoveryFrom, setRecoveryFrom] = useState<'account' | 'verification'>('account');
  const [passwordResetFrom, setPasswordResetFrom] = useState<'login' | 'recovery'>('login');
  const [passwordResetEmail, setPasswordResetEmail] = useState('');
  const [passwordResendAt, setPasswordResendAt] = useState(0);
  const [passwordConfirmRetryAt, setPasswordConfirmRetryAt] = useState(0);
  const [demo, setDemo] = useState(false);
  const [email, setEmail] = useState(rememberedEmail);
  const [rememberEmail, setRememberEmail] = useState(() => Boolean(rememberedEmail()));
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [inviteCode, setInviteCode] = useState('');
  const [invitation, setInvitation] = useState<Invitation | null>(null);
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [otp, setOtpValue] = useState('');
  const otpValue = useRef('');
  const attemptedOtp = useRef('');
  const [resendAt, setResendAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [role, setRole] = useState<AppRole>('worker');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [modal, setModal] = useState<'privacy' | null>(null);
  const submitting = useRef(false);
  const title = useRef<HTMLHeadingElement>(null);
  const otpInput = useRef<HTMLInputElement>(null);
  const remaining = Math.max(0, Math.ceil((resendAt - now) / 1000));
  const passwordRemaining = Math.max(0, Math.ceil((passwordResendAt - now) / 1000));
  const passwordConfirmRemaining = Math.max(0, Math.ceil((passwordConfirmRetryAt - now) / 1000));
  const requirements = [
    { label: 'Минимум 8 символов', valid: password.length >= 8 },
    { label: 'Одна заглавная буква', valid: /\p{Lu}/u.test(password) },
    { label: 'Одна цифра', valid: /[0-9]/.test(password) },
  ];

  useEffect(() => {
    setError(''); setNotice(''); setShowPassword(false);
    const frame = requestAnimationFrame(() => {
      if (stage === 'verification' || stage === 'password-reset-confirm') otpInput.current?.focus();
      else title.current?.focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: 'instant' });
    });
    return () => cancelAnimationFrame(frame);
  }, [stage]);
  useEffect(() => {
    if (!resendAt && !passwordResendAt && !passwordConfirmRetryAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [resendAt, passwordResendAt, passwordConfirmRetryAt]);

  function go(next: Stage) { if (!submitting.current) { setError(''); setNotice(''); setStage(next); } }
  function start(demoMode: boolean) {
    setDemo(demoMode); setInvitation(null); setError(''); setNotice(''); setPassword(demoMode ? 'Posttech2026' : '');
    setInviteCode(demoMode ? DEMO_INVITE : ''); setFirstName(demoMode ? 'Алексей' : ''); setLastName(demoMode ? 'Ким' : '');
    setRole('worker'); updateOtp(''); attemptedOtp.current = ''; setResendAt(0); setStage('invitation');
  }
  function returnToLogin() {
    if (submitting.current) return;
    setDemo(false); setPassword(''); setInvitation(null); setInviteCode(''); updateOtp(''); setResendAt(0); setStage('login');
  }
  function beginCountdown(seconds = 60) { const current = Date.now(); setNow(current); setResendAt(current + Math.max(1, seconds) * 1000); }
  function beginPasswordCountdown(seconds = 60) { const current = Date.now(); setNow(current); setPasswordResendAt(current + Math.max(1, seconds) * 1000); }
  function startPasswordReset(from: 'login' | 'recovery') {
    if (submitting.current) return;
    setPasswordResetFrom(from); setPasswordResetEmail(from === 'recovery' ? invitation?.email || '' : email.trim());
    setPassword(''); updateOtp(''); setDemo(false); go('password-reset');
  }
  async function sendPasswordReset() {
    try {
      const result = await api.requestPasswordReset(passwordResetEmail.trim());
      beginPasswordCountdown(result.retry_after || 60);
      updateOtp('');
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) beginPasswordCountdown(err.retryAfterSeconds || 60);
      throw err;
    }
  }
  async function submitPasswordReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const button = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    if (button?.value === 'existing-code') { setPassword(''); updateOtp(''); go('password-reset-confirm'); return; }
    if (passwordRemaining) return;
    await run(async () => {
      await sendPasswordReset();
      setPasswordResetEmail(value => value.trim()); setPassword(''); setStage('password-reset-confirm');
    });
  }
  async function resendPasswordReset() {
    if (passwordRemaining) return;
    await run(async () => {
      await sendPasswordReset();
      setNotice('Если аккаунт существует, инструкция придёт на эту почту.');
      otpInput.current?.focus();
    });
  }
  async function submitPasswordResetConfirm(event: FormEvent) {
    event.preventDefault();
    if (passwordConfirmRemaining) return;
    if (!/^(?:[0-9]{6}|[0-9]{8})$/.test(otpValue.current)) { setError('Введите код из письма целиком.'); otpInput.current?.focus(); return; }
    if (!requirements.every(item => item.valid)) { setError('Пароль должен соответствовать всем трём условиям.'); return; }
    await run(async () => {
      try {
        await api.confirmPasswordReset({ email: passwordResetEmail.trim(), token: otpValue.current, password });
      } catch (err) {
        if (err instanceof ApiError && err.status === 429) { const current = Date.now(); setNow(current); setPasswordConfirmRetryAt(current + (err.retryAfterSeconds || 60) * 1000); }
        throw err;
      }
      setEmail(passwordResetEmail.trim()); setPassword(''); updateOtp(''); setPasswordResendAt(0); setStage('password-reset-success');
    });
  }
  function finishPasswordReset() {
    setPassword(''); updateOtp('');
    if (passwordResetFrom === 'recovery') go('recovery');
    else returnToLogin();
  }
  async function run(action: () => Promise<void>, isCurrent = () => true) {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setError(''); setNotice('');
    try { await action(); }
    catch (err) { if (isCurrent()) setError(errorMessage(err)); }
    finally { submitting.current = false; setBusy(false); }
  }
  async function submitLogin(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      await api.login(email.trim(), password);
      try { if (rememberEmail) localStorage.setItem(EMAIL_KEY, email.trim()); else localStorage.removeItem(EMAIL_KEY); } catch { /* Storage is optional. */ }
      setPassword(''); onLogin();
    });
  }
  async function submitInvitation(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      if (demo) {
        if (inviteCode.trim().toUpperCase() !== DEMO_INVITE) throw new Error(`Для демоверсии используйте ${DEMO_INVITE}.`);
        setInvitation({ email: 'demo@posttech.demo', role: 'worker', department: 'Демонстрационная команда', expires_at: '' });
      } else setInvitation(await api.checkInvitation(inviteCode.trim()));
      setStage('account');
    });
  }
  async function submitAccount(event: FormEvent) {
    event.preventDefault();
    if (!firstName.trim() || !lastName.trim()) { setError('Укажите имя и фамилию.'); return; }
    if (!requirements.every(item => item.valid)) { setError('Пароль должен соответствовать всем трём условиям.'); return; }
    await run(async () => {
      if (demo) { setPassword(''); beginCountdown(); setStage('verification'); return; }
      const result = await api.register({ invitation_code: inviteCode.trim(), first_name: firstName.trim(), last_name: lastName.trim(), password });
      setPassword('');
      if (result.email_confirmation_required) { beginCountdown(); setStage('verification'); }
      else setStage('welcome');
    });
  }
  async function verifyCode(token: string) {
    if (submitting.current) return;
    if (!/^(?:[0-9]{6}|[0-9]{8})$/.test(token)) { setError('Введите код из письма целиком.'); otpInput.current?.focus(); return; }
    attemptedOtp.current = token;
    await run(async () => {
      if (demo) {
        if (token !== DEMO_TOKEN) throw new Error('Неверный код. Код для демо: 472916.');
        setStage('role');
      } else {
        await api.verifyRegistration({ invitation_code: inviteCode.trim(), token });
        setStage('welcome');
      }
      updateOtp(''); setResendAt(0);
    }, () => otpValue.current === token);
  }
  function submitVerification(event: FormEvent) { event.preventDefault(); void verifyCode(otpValue.current); }
  useEffect(() => {
    // A live code may contain eight digits: never submit its six-digit prefix.
    if (!demo || stage !== 'verification' || busy || otp.length !== DEMO_TOKEN.length || attemptedOtp.current === otp) return;
    const timer = window.setTimeout(() => { void verifyCode(otp); }, 750);
    return () => clearTimeout(timer);
  }, [demo, otp, stage, busy]);
  async function resendCode() {
    if (remaining) return;
    await run(async () => {
      if (demo) { beginCountdown(); setNotice(`Код для демо: ${DEMO_TOKEN}.`); }
      else { const result = await api.resendRegistration(inviteCode.trim()); beginCountdown(result.retry_after || 60); setNotice('Новое письмо запрошено. Проверьте входящие и папку «Спам».'); }
      updateOtp(''); otpInput.current?.focus();
    });
  }
  async function submitRecovery(event: FormEvent) {
    event.preventDefault();
    if (!firstName.trim() || !lastName.trim()) { setError('Укажите имя и фамилию для рабочего профиля.'); return; }
    await run(async () => {
      await api.completeInvitation({ invitation_code: inviteCode.trim(), email: invitation?.email || '', password, first_name: firstName.trim(), last_name: lastName.trim() });
      setPassword(''); setStage('welcome');
    });
  }
  function updateOtp(value: string) {
    const clean = value.replace(/\D/g, '').slice(0, 8);
    if (clean !== otpValue.current) attemptedOtp.current = '';
    otpValue.current = clean;
    setOtpValue(clean); setError('');
  }
  function back() {
    if (stage === 'password-reset') { setPassword(''); updateOtp(''); go(passwordResetFrom); }
    else if (stage === 'password-reset-confirm') { setPassword(''); updateOtp(''); go('password-reset'); }
    else if (stage === 'password-reset-success') finishPasswordReset();
    else if (stage === 'invitation') returnToLogin();
    else if (stage === 'account') go('invitation');
    else if (stage === 'recovery') { setPassword(''); go(recoveryFrom); }
    else if (stage === 'verification') { setPassword(''); go('account'); }
    else if (stage === 'role') go('invitation');
    else if (stage === 'welcome') { if (demo) go('role'); else onLogin(); }
  }
  const headings: Record<Stage, string> = {
    login: 'Вход в PostTech', invitation: 'Активация приглашения', account: 'Создайте аккаунт',
    verification: 'Проверьте почту', recovery: 'Завершите активацию', role: 'Выберите роль', welcome: 'Добро пожаловать\nв PostTech!',
    'password-reset': 'Восстановить пароль', 'password-reset-confirm': 'Новый пароль', 'password-reset-success': 'Пароль изменён',
  };
  const branded = ['login', 'role', 'welcome'].includes(stage);
  const otpLength = demo ? DEMO_TOKEN.length : 8;
  const passwordField = (creating = false, hideLabel = false, label = 'Пароль') => <label className="onboarding-field"><span className={hideLabel ? 'onboarding-login-field-label' : ''}>{tx(label)}</span><span className={`onboarding-input-wrap ${creating ? 'onboarding-password-create' : ''}`}>{tx(!creating && <Icon name="lock" size={16} />)}<input id="onboarding-password" type={showPassword ? 'text' : 'password'} autoComplete={creating ? 'new-password' : 'current-password'} value={password} onChange={event => setPassword(event.target.value)} placeholder={label} required minLength={8} maxLength={128} disabled={busy} /><button type="button" className="onboarding-eye" aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'} aria-pressed={showPassword} disabled={busy} onClick={() => setShowPassword(value => !value)}><Icon name={showPassword ? 'eye-off' : 'eye'} size={16} /></button></span></label>;
  const passwordChecks = <ul className="onboarding-password-checks" aria-label={t("Требования к паролю")}>{tx(requirements.map(item => <li key={item.label} className={item.valid ? 'is-valid' : ''}><Icon name="check-circle" size={12} /><span>{tx(item.label)}</span><span className="sr-only">{tx(item.valid ? ' — выполнено' : ' — не выполнено')}</span></li>))}</ul>;
  const codeField = (disabled = false) => <div className={`onboarding-otp-shell ${error ? 'is-invalid' : ''}`}><div className={`onboarding-otp onboarding-otp-${otpLength}`} aria-hidden="true">{tx(Array.from({ length: otpLength }, (_, i) => <span className={`onboarding-otp-cell ${i === otp.length ? 'is-current' : ''}`} key={i}>{tx(otp[i] || '')}</span>))}</div><input ref={otpInput} className="onboarding-otp-input" type="text" inputMode="numeric" autoComplete="one-time-code" aria-label={t("Код подтверждения")} aria-invalid={Boolean(error)} maxLength={8} value={otp} disabled={disabled} onChange={event => updateOtp(event.target.value)} onPaste={event => { event.preventDefault(); updateOtp(event.clipboardData.getData('text')); }} /></div>;
  const countdown = (seconds: number) => seconds > 0 && <span className="onboarding-countdown">({tx(Math.floor(seconds / 60))}:{tx(String(seconds % 60).padStart(2, '0'))})</span>;
  const status = <>{tx(error && <div className="onboarding-message onboarding-message-error" role="alert"><Icon name="alert-circle" size={16} /><span>{tx(error)}</span></div>)}{tx(notice && <div className="onboarding-message onboarding-message-success" role="status"><span>{tx(notice)}</span></div>)}</>;
  const submitButton = (label: string, loadingLabel: string) => <button className="onboarding-primary" type="submit" disabled={busy}>{tx(busy ? <><span className="spinner" />{tx(loadingLabel)}</> : label)}</button>;
  const backButton = (mobileOnly = false) => <button type="button" className={`onboarding-back ${mobileOnly ? 'onboarding-mobile-back' : ''}`} onClick={back} disabled={busy} aria-label={t("Назад")}><Icon name="chevron-left" size={19} /><span className="onboarding-back-label">{t("Назад")}</span></button>;
  function recovery(from: 'account' | 'verification') { setPassword(''); setRecoveryFrom(from); go('recovery'); }

  return <div className="onboarding-page"><main className="onboarding-main">
    <section className={`onboarding-card onboarding-stage-${stage}`} aria-labelledby="onboarding-title" aria-busy={busy}>
      <header className="onboarding-header">
        {tx(branded ? <><span className="onboarding-brand"><Brand /></span>{tx(stage !== 'login' && backButton(true))}</> : backButton())}
        <span className="onboarding-header-end">{tx(demo && <span className={`onboarding-demo-tag ${stage === 'role' ? 'onboarding-mobile-only' : ''}`}>{t("Демо")}</span>)}<LanguageSwitch /></span>
      </header>
      {tx(stage === 'welcome' && <div className="onboarding-celebration" aria-hidden="true">🎉</div>)}
      {tx(stage === 'password-reset-success' && <div className="onboarding-reset-success-icon" aria-hidden="true"><Icon name="check" size={34} /></div>)}
      <h1 id="onboarding-title" ref={title} tabIndex={-1}>{tx(stage === 'login' ? <><span className="onboarding-desktop-only">{t("Вход в PostTech")}</span><span className="onboarding-mobile-only">{t("Вход")}</span></> : headings[stage])}</h1>

      {tx(stage === 'login' && <>
        <p className="onboarding-description onboarding-login-description">{t("Единая платформа для сотрудников Jana Post")}</p>
        <form className="onboarding-form onboarding-login-form" onSubmit={submitLogin}>
          <label className="onboarding-field"><span className="onboarding-login-field-label">{t("Рабочая почта")}</span><span className="onboarding-input-wrap"><Icon name="user" size={16} /><input type="email" autoComplete="username" placeholder="work@janapost.kz" value={email} onChange={event => setEmail(event.target.value)} required maxLength={320} disabled={busy} /></span></label>
          {tx(passwordField(false, true))}
          <div className="onboarding-login-options"><label className="onboarding-checkbox"><input type="checkbox" checked={rememberEmail} disabled={busy} onChange={event => { setRememberEmail(event.target.checked); if (!event.target.checked) { try { localStorage.removeItem(EMAIL_KEY); } catch {} } }} /><span>{t("Запомнить почту")}</span></label><button className="onboarding-link" type="button" disabled={busy} onClick={() => startPasswordReset('login')}>{t("Забыли пароль?")}</button></div>
          {tx(status)}{tx(submitButton('Войти', 'Входим…'))}
        </form>
        <div className="onboarding-divider"><span>{t("или")}</span></div>
        <button className="onboarding-secondary" onClick={() => start(true)} disabled={busy}><Icon name="user" size={17} />{t("Демо-вход")}</button>
        <div className="onboarding-bottom"><span>{t("Нужен доступ?")}</span><button className="onboarding-link" onClick={() => start(false)} disabled={busy}>{t("Активировать приглашение")}</button></div>
      </>)}

      {tx(stage === 'password-reset' && <>
        <p className="onboarding-description">{t("Укажите рабочую почту. Если аккаунт существует, вы получите инструкцию.")}</p>
        <form className="onboarding-form" onSubmit={submitPasswordReset}>
          <label className="onboarding-field"><span>{t("Рабочая почта")}</span><input type="email" autoComplete="email" placeholder="work@janapost.kz" value={passwordResetEmail} onChange={event => { setPasswordResetEmail(event.target.value); setError(''); }} readOnly={passwordResetFrom === 'recovery'} required maxLength={320} disabled={busy} /></label>
          {tx(status)}
          <button type="submit" className="onboarding-primary" disabled={busy || passwordRemaining > 0}>{tx(busy ? <><span className="spinner" />{t("Отправляем…")}</> : <>{t("Отправить код ")}{tx(countdown(passwordRemaining))}</>)}</button>
          <button type="submit" className="onboarding-link onboarding-reset-existing" value="existing-code" disabled={busy}>{t("У меня уже есть код")}</button>
        </form>
      </>)}

      {tx(stage === 'password-reset-confirm' && <>
        <p className="onboarding-description">{t("Введите код из письма")}<strong className="onboarding-email">{tx(passwordResetEmail.trim())}</strong></p>
        <form className="onboarding-form onboarding-reset-form" onSubmit={submitPasswordResetConfirm}>
          {tx(codeField(busy))}
          {tx(passwordField(true, false, 'Новый пароль'))}
          {tx(passwordChecks)}
          {tx(status)}<button type="submit" className="onboarding-primary" disabled={busy || passwordConfirmRemaining > 0}>{tx(busy ? <><span className="spinner" />{t("Сохраняем…")}</> : <>{t("Сохранить пароль ")}{tx(countdown(passwordConfirmRemaining))}</>)}</button>
        </form>
        <div className="onboarding-resend"><span>{t("Не получили письмо?")}</span><button className="onboarding-link" disabled={busy || passwordRemaining > 0} onClick={resendPasswordReset}>{t("Отправить снова")}{tx(countdown(passwordRemaining))}</button></div>
        <div className="onboarding-note onboarding-note-blue"><Icon name="info" size={19} /><p>{t("Проверьте папку «Спам», если письмо не пришло.")}</p></div>
        {tx(error && <button type="button" className="onboarding-link onboarding-centered-link" disabled={busy} onClick={finishPasswordReset}>{t("Вернуться ко входу")}</button>)}
      </>)}

      {tx(stage === 'password-reset-success' && <>
        <p className="onboarding-description">{t("Теперь войдите с новым паролем.")}</p>
        <button type="button" className="onboarding-primary onboarding-push-bottom" onClick={finishPasswordReset}>{tx(passwordResetFrom === 'recovery' ? 'Продолжить активацию' : 'Войти')}</button>
      </>)}

      {tx(stage === 'invitation' && <>
        <div className="onboarding-invitation-intro"><p className="onboarding-description">{t("Введите код из письма, чтобы создать аккаунт")}</p><div className="onboarding-envelope" aria-hidden="true"><svg viewBox="0 0 100 85" fill="none"><rect x="10" y="22" width="74" height="52" rx="5" fill="#e7edfc"/><path d="m12 25 35 27 35-27" fill="#c6d5f4"/><path d="m12 72 25-22m45 22L57 50" stroke="#e0e8fa" strokeWidth="2"/><circle cx="78" cy="24" r="14" fill="#009b4e"/><path d="m72 24 4 4 8-9" stroke="white" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/></svg></div></div>
        <form className="onboarding-form" onSubmit={submitInvitation}><label className="onboarding-field"><span>{t("Код приглашения")}</span><input className="onboarding-code-input" autoComplete="off" autoCapitalize="none" spellCheck={false} placeholder="JP-7F3K-9L2M" value={inviteCode} onChange={event => setInviteCode(event.target.value)} maxLength={128} required disabled={busy} /></label>{tx(status)}{tx(submitButton('Продолжить', 'Проверяем…'))}</form>
        <div className="onboarding-note"><span className="onboarding-note-icon"><Icon name="help" size={18} /></span><div><strong>{t("Нет кода?")}</strong><span>{t("Обратитесь к HR-отделу")}</span></div></div>
      </>)}

      {stage === 'account' && invitation && <>
        <p className="onboarding-description onboarding-account-description">{t("Заполните основные данные")}</p>
        <form className="onboarding-form onboarding-account-form" onSubmit={submitAccount}>
          <div className="onboarding-name-row"><label className="onboarding-field"><span>{t("Имя")}</span><input autoComplete="given-name" placeholder={t("Имя")} value={firstName} onChange={event => setFirstName(event.target.value)} maxLength={80} required disabled={busy} /></label><label className="onboarding-field"><span>{t("Фамилия")}</span><input autoComplete="family-name" placeholder={t("Фамилия")} value={lastName} onChange={event => setLastName(event.target.value)} maxLength={80} required disabled={busy} /></label></div>
          <label className="onboarding-field"><span>Email</span><input type="email" autoComplete="email" value={invitation.email} readOnly /></label>
          {tx(passwordField(true))}
          {tx(passwordChecks)}
          {tx(status)}{tx(submitButton('Создать аккаунт', 'Создаём…'))}
        </form>
        {tx(!demo && <button type="button" className="onboarding-link onboarding-centered-link" disabled={busy} onClick={() => { setPassword(''); updateOtp(''); go('verification'); }}>{t("Уже есть код из письма")}</button>)}
        <p className="onboarding-privacy"><button className="onboarding-link" onClick={() => setModal('privacy')}>{t("Политика конфиденциальности")}</button></p>
        {tx(!demo && error && <button className="onboarding-link onboarding-centered-link" disabled={busy} onClick={() => recovery('account')}>{t("Уже есть аккаунт? Войти")}</button>)}
      </>}

      {stage === 'verification' && <>
        <p className="onboarding-description">{tx(demo ? 'Введите код подтверждения' : 'Подтвердите почту кодом из письма')}<strong className="onboarding-email">{invitation?.email}</strong></p>
        <form className="onboarding-verification-form" onSubmit={submitVerification}>
          {tx(codeField(busy))}
          {tx(demo && <p className="onboarding-demo-code">{t("Код для демо: ")}<button type="button" className="onboarding-link" onClick={() => updateOtp(DEMO_TOKEN)}>{tx(DEMO_TOKEN)}</button></p>)}
          {tx(status)}
          {tx(!demo && <button type="submit" className="onboarding-primary onboarding-verify-button" disabled={busy || !/^(?:[0-9]{6}|[0-9]{8})$/.test(otp)}>{tx(busy ? <><span className="spinner" />{t("Проверяем…")}</> : 'Подтвердить')}</button>)}
          {tx(demo && busy && <p className="onboarding-otp-status" role="status">{t("Проверяем…")}</p>)}
          {tx(demo && error && <button type="submit" className="onboarding-link onboarding-centered-link" disabled={busy}>{t("Проверить ещё раз")}</button>)}
        </form>
        <div className="onboarding-resend"><span>{t("Не получили письмо?")}</span><button className="onboarding-link" disabled={busy || remaining > 0} onClick={resendCode}>{t("Отправить снова")}{tx(countdown(remaining))}</button></div>
        <div className="onboarding-note onboarding-note-blue"><Icon name="info" size={19} /><p>{t("Проверьте папку «Спам», если письмо не пришло.")}</p></div>
        {tx(!demo && <details className="onboarding-help-details"><summary>{t("В письме только ссылка?")}</summary><p>{t("Подтвердите почту по ссылке, затем завершите вход.")}</p><button type="button" className="onboarding-link" disabled={busy} onClick={() => recovery('verification')}>{t("Продолжить с паролем")}</button></details>)}
      </>}

      {stage === 'recovery' && <>
        <p className="onboarding-description">{t("Войдите, чтобы активировать приглашение.")}</p>
        <form className="onboarding-form onboarding-account-form" onSubmit={submitRecovery}><div className="onboarding-name-row"><label className="onboarding-field"><span>{t("Имя")}</span><input autoComplete="given-name" value={firstName} onChange={event => setFirstName(event.target.value)} maxLength={80} required disabled={busy} /></label><label className="onboarding-field"><span>{t("Фамилия")}</span><input autoComplete="family-name" value={lastName} onChange={event => setLastName(event.target.value)} maxLength={80} required disabled={busy} /></label></div><label className="onboarding-field"><span>Email</span><input value={invitation?.email || ''} type="email" autoComplete="username" readOnly /></label>{tx(passwordField())}{tx(status)}{tx(submitButton('Продолжить', 'Входим…'))}</form>
        <button className="onboarding-link onboarding-centered-link" disabled={busy} onClick={() => startPasswordReset('recovery')}>{t("Забыли пароль?")}</button>
      </>}

      {tx(stage === 'role' && demo && <>
        <p className="onboarding-description onboarding-role-description">{t("Это демо-версия. Вы можете выбрать роль для знакомства с системой.")}</p>
        <fieldset className="onboarding-roles"><legend className="sr-only">{t("Роль в демоверсии")}</legend>{tx(roleOptions.map(option => <label key={option.role} className={`onboarding-role ${role === option.role ? 'is-selected' : ''}`}><input type="radio" name="demo-role" value={option.role} checked={role === option.role} onChange={() => setRole(option.role)} /><span className={`onboarding-role-icon onboarding-role-icon-${option.role}`}><Icon name={option.icon} size={23} /></span><span className="onboarding-role-copy"><strong>{tx(option.title)}</strong><span>{tx(option.detail)}</span></span><span className="onboarding-role-check">{tx(role === option.role && <Icon name="check" size={12} />)}</span></label>))}</fieldset>
        <button className="onboarding-primary onboarding-push-bottom" onClick={() => go('welcome')}>{t("Продолжить")}</button>
      </>)}

      {tx(stage === 'welcome' && <>
        <p className="onboarding-description">{tx(demo ? 'Теперь вы можете познакомиться со всеми возможностями платформы.' : 'Ваш аккаунт активирован. Теперь вы можете использовать все возможности платформы.')}</p>
        <button className="onboarding-primary onboarding-push-bottom" onClick={() => { setPassword(''); if (demo) onDemo(role); else onLogin(); }}>{t("Перейти на главную")}</button>
      </>)}
    </section>
  </main>
    {tx(modal === 'privacy' && <Modal title={t("Конфиденциальность")} onClose={() => setModal(null)}><p>{t("Имя и рабочая почта связывают аккаунт с кадровым профилем. Роль и доступ к данным определяет HR.")}</p><p>{t("Пароль не сохраняется в браузере. «Запомнить почту» сохраняет только адрес на этом устройстве.")}</p><p className="muted">{t("Полные условия обработки данных доступны у HR-отдела Jana Post.")}</p><button className="btn btn-primary" onClick={() => setModal(null)}>{t("Понятно")}</button></Modal>)}
  </div>;
}
