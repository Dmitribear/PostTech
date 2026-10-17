import { fetchAllRequests } from '@/shared/api/api';
import type { HrApi as Api, HrRequest as RequestRecord } from '@/shared/api/contracts';
import { getLocale, localizedDate } from '@/shared/lib/i18n';
import '@/shared/styles/requests.css';
export type { HrRequest as RequestRecord } from '@/shared/api/contracts';
export function dateKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
export function businessDate(): string {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Qyzylorda',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  return `${parts.find((part) => part.type === 'year')?.value}-${parts.find((part) => part.type === 'month')?.value}-${parts.find((part) => part.type === 'day')?.value}`;
}
export function approverNames(approvers: RequestRecord['approvers']): string {
  return approvers?.length
    ? approvers.map((person) => person.full_name).join(', ')
    : 'Маршрут согласования не указан';
}
export function leaveConflicts(
  records: RequestRecord[],
  employeeId: string,
  start: string,
  end: string,
) {
  if (!start || !end || end < start) return [];
  return records.filter(
    (record) =>
      record.employee_id === employeeId &&
      record.request_type === 'leave' &&
      (record.status === 'pending' || record.status === 'approved') &&
      record.start_date &&
      record.end_date &&
      record.start_date <= end &&
      record.end_date >= start,
  );
}
export function parseDay(value: string): Date {
  return new Date(`${value.slice(0, 10)}T12:00:00`);
}
export function dayCount(start: string, end: string): number {
  const from = Date.parse(`${start}T00:00:00Z`);
  const to = Date.parse(`${end}T00:00:00Z`);
  return Number.isNaN(from) || Number.isNaN(to) || to < from
    ? 0
    : Math.round((to - from) / 86400000) + 1;
}
export function dayWord(value: number, calendar = false): string {
  const plural = new Intl.PluralRules(getLocale() === 'kk' ? 'kk-KZ' : 'ru-RU').select(value);
  if (calendar)
    return plural === 'one'
      ? 'календарный день'
      : plural === 'few'
        ? 'календарных дня'
        : 'календарных дней';
  return plural === 'one' ? 'день' : plural === 'few' ? 'дня' : 'дней';
}
export function formatDay(value: string | null | undefined, full = false): string {
  if (!value) return '—';
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const date = dateOnly ? parseDay(value) : new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return localizedDate(date, {
    day: 'numeric',
    month: full ? 'long' : 'short',
    year: 'numeric',
    ...(dateOnly ? {} : { timeZone: 'Asia/Qyzylorda' }),
  });
}
export function requestLabel(request: RequestRecord): string {
  return request.request_type === 'leave' ? 'Заявка на отпуск' : 'Заявка на аванс';
}
export function requestNumber(id: string): string {
  return `REQ-${id.slice(-8).toUpperCase()}`;
}
export function money(value: number): string {
  return `${new Intl.NumberFormat(getLocale() === 'kk' ? 'kk-KZ' : 'ru-RU', { maximumFractionDigits: 2 }).format(value)} ₸`;
}
export async function loadRequests(
  api: Api,
  filters: Parameters<Api['getRequests']>[0] = {},
): Promise<RequestRecord[]> {
  return fetchAllRequests(api, filters);
}
