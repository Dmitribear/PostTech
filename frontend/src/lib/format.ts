import { getLocale, localizedDate } from './i18n';
import type { AppRole, CourseStatus, RequestStatus, RequestType, Notification } from './types';

export function notificationHref(item: Notification): string {
  if (item.ticket_id) return `/support?ticket=${encodeURIComponent(item.ticket_id)}`;
  if (item.notification_type === 'delegation_assigned') return '/requests?scope=review';
  if (item.request_id) return `/requests/${item.request_id}`;
  if (item.notification_type === 'team_course_completed') return `/academy?tab=team${item.course_id ? `&courseFilter=${item.course_id}` : ''}`;
  if (item.course_id) return `/academy?course=${item.course_id}`;
  return item.notification_type.includes('course') || item.notification_type.includes('training') ? '/academy' : '/notifications';
}

export const roleLabels: Record<AppRole, string> = { worker: 'Сотрудник', manager: 'Руководитель', director: 'Директор', hr_admin: 'HR-администратор' };
export const requestTypeLabels: Record<RequestType, string> = { leave: 'Отпуск', advance: 'Аванс' };
export const requestStatusLabels: Record<RequestStatus, string> = { pending: 'На рассмотрении', pending_hr: 'На согласовании HR', approved: 'Одобрено', rejected: 'Отклонено', cancelled: 'Отменено' };
export const courseStatusLabels: Record<CourseStatus, string> = { not_started: 'Не начат', in_progress: 'В процессе', completed: 'Завершён' };

export function initials(name: string): string { return name.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join('').toUpperCase(); }
export function firstName(name: string): string { return name.trim().split(/\s+/)[0] || 'коллега'; }

/** Date-only fields are calendar dates and must not shift with the browser timezone. */
export function formatDate(value: string | null | undefined, options: Intl.DateTimeFormatOptions = {}): string {
  if (!value) return '—';
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const date = new Date(dateOnly ? `${value}T12:00:00` : value);
  if (Number.isNaN(date.getTime())) return '—';
  return localizedDate(date, { day: 'numeric', month: 'short', year: 'numeric', ...options });
}

export function formatMoney(value: number | null | undefined): string {
  return value == null ? '—' : new Intl.NumberFormat(getLocale() === 'kk' ? 'kk-KZ' : 'ru-KZ', { style: 'currency', currency: 'KZT', maximumFractionDigits: Number.isInteger(value) ? 0 : 2 }).format(value);
}

export function daysBetween(start: string, end: string): number {
  const from = Date.parse(`${start}T00:00:00Z`);
  const to = Date.parse(`${end}T00:00:00Z`);
  return Number.isNaN(from) || Number.isNaN(to) || to < from ? 0 : Math.round((to - from) / 86_400_000) + 1;
}

export function pluralDays(count: number): string {
  if (getLocale() === 'kk') return `${count} күн`;
  const plural = new Intl.PluralRules('ru-RU').select(count);
  return `${count} ${plural === 'one' ? 'день' : plural === 'few' ? 'дня' : 'дней'}`;
}
