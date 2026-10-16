import { useEffect, useRef, type ReactNode } from 'react';
import { Activity, ArrowDownToLine, ArrowLeft, ArrowRight, Bell, BookOpen, Bot, BriefcaseBusiness, CalendarDays, CalendarCheck, Check, CheckCheck, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, CircleHelp, ClipboardList, Clock3, CreditCard, FileText, GraduationCap, LayoutDashboard, LayoutGrid, LockKeyhole, LogOut, Mail, Menu, MessageSquare, MoreHorizontal, PlaneTakeoff, Plus, RefreshCw, Search, Send, Settings, ShieldCheck, Sparkles, Truck, UserRound, UsersRound, Wallet, X, AlertCircle, Eye, EyeOff, Info, Filter, Play, Upload, type LucideIcon } from 'lucide-react';
import { errorMessage } from '../lib/api';

const icons: Record<string, LucideIcon> = {
  activity: Activity, 'arrow-down': ArrowDownToLine, download: ArrowDownToLine, 'arrow-left': ArrowLeft, 'arrow-right': ArrowRight,
  bell: Bell, book: BookOpen, 'book-open': BookOpen, bot: Bot, briefcase: BriefcaseBusiness, calendar: CalendarDays, 'calendar-check': CalendarCheck,
  check: Check, 'check-check': CheckCheck, 'check-circle': CheckCircle2, 'chevron-down': ChevronDown, 'chevron-left': ChevronLeft, 'chevron-right': ChevronRight,
  clock: Clock3, clipboard: ClipboardList, requests: ClipboardList, 'credit-card': CreditCard, file: FileText, 'file-text': FileText,
  school: GraduationCap, building: BriefcaseBusiness, graduation: GraduationCap, 'graduation-cap': GraduationCap, home: LayoutDashboard, grid: LayoutGrid, help: CircleHelp,
  lock: LockKeyhole, logout: LogOut, mail: Mail, menu: Menu, message: MessageSquare, more: MoreHorizontal,
  plane: PlaneTakeoff, plus: Plus, refresh: RefreshCw, search: Search, send: Send, settings: Settings,
  shield: ShieldCheck, sparkles: Sparkles, truck: Truck, user: UserRound, users: UsersRound, wallet: Wallet, x: X,
  alert: AlertCircle, 'alert-circle': AlertCircle, eye: Eye, 'eye-off': EyeOff, info: Info, filter: Filter, play: Play, upload: Upload,
};
export function Icon({ name, size = 20, className = '' }: { name: string; size?: number; className?: string }) {
  const Component = icons[name] || FileText;
  return <Component size={size} strokeWidth={1.7} className={className} aria-hidden="true" />;
}
export function Avatar({ name, size = 40 }: { name: string; size?: number }) {
  return <span className="avatar" style={{ width: size, height: size, fontSize: size * .34 }} aria-hidden="true">{name.split(' ').filter(Boolean).slice(0, 2).map(n => n[0]).join('')}</span>;
}
export function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = { pending: 'На согласовании', approved: 'Одобрено', rejected: 'Отклонено', cancelled: 'Отменено', not_started: 'Не начат', in_progress: 'В процессе', completed: 'Завершён' };
  return <span className={`badge badge-${status}`}><span className="badge-dot" />{labels[status] || status}</span>;
}
export function PageHeader({ title, description, actions, eyebrow }: { title: string; description?: string; actions?: ReactNode; eyebrow?: string }) {
  return <div className="page-header"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h1 className="page-title">{title}</h1>{description && <p className="page-description">{description}</p>}</div>{actions && <div className="page-actions">{actions}</div>}</div>;
}
export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><Icon name="clipboard" size={28} /></span><h3>{title}</h3>{description && <p>{description}</p>}{action}</div>;
}
export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return <div className="error-state" role="alert"><Icon name="alert" /><div><strong>Не удалось загрузить данные</strong><p>{errorMessage(error)}</p>{retry && <button className="btn btn-secondary" onClick={retry}><Icon name="refresh" size={16} />Повторить</button>}</div></div>;
}
export function LoadingState() {
  return <div className="loading-state" role="status"><span className="spinner" />Загружаем данные…</div>;
}
export function Modal({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => { const node = dialog.current; node?.showModal(); const before = document.body.style.overflow; document.body.style.overflow = 'hidden'; return () => { node?.close(); document.body.style.overflow = before; }; }, []);
  return <dialog ref={dialog} className={`modal ${wide ? 'modal-wide' : ''}`} aria-label={title} onCancel={e => { e.preventDefault(); close.current(); }} onClick={e => { if (e.target === dialog.current) close.current(); }}><div className="modal-inner"><div className="modal-heading"><h2>{title}</h2><button className="icon-btn" aria-label="Закрыть" onClick={onClose}><Icon name="x" /></button></div>{children}</div></dialog>;
}
