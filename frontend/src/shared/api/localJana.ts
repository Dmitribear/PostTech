import { ApiError, calendarBlob, janaSourcePath } from '@/shared/api/api';
import type { HrRequest, JanaAnswer, JanaArticle } from '@/shared/api/contracts';

/** Explicit loopback demo bridge. Never reads or forwards a working HR session. */
export class LocalDemoJana {
  constructor(
    private readonly baseUrl: string,
    private readonly transport: typeof fetch = globalThis.fetch.bind(globalThis),
  ) {
    if (!/^\/(?!\/)[a-zA-Z0-9/_-]+$/.test(baseUrl))
      throw new Error('Demo Jana must use a same-origin development proxy path');
  }

  private async send<T>(path: string, body?: unknown, calendar = false): Promise<T> {
    let response: Response;
    try {
      response = await this.transport(`${this.baseUrl}${path}`, {
        method: body === undefined ? 'GET' : 'POST',
        credentials: 'omit',
        headers: {
          Accept: calendar ? 'text/calendar' : 'application/json',
          ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch {
      throw new ApiError(
        503,
        'Локальная Jana недоступна. Запустите сервер демонстрации и попробуйте снова.',
      );
    }
    if (response.ok && calendar) return (await calendarBlob(response)) as T;
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new ApiError(503, 'Локальная Jana недоступна. Проверьте сервер демонстрации.');
    }
    if (!response.ok) throw new ApiError(response.status, payload?.detail);
    return payload as T;
  }

  askJana(question: string): Promise<JanaAnswer> {
    return this.send('/api/v1/ai/ask', { question });
  }
  async getJanaSource(id: string): Promise<JanaArticle> {
    return this.send(`/api/v1${janaSourcePath(id)}`);
  }
  getLeaveCalendar(record: HrRequest): Promise<Blob> {
    return this.send(
      '/demo/leave.ics',
      {
        id: record.id,
        start_date: record.start_date,
        end_date: record.end_date,
      },
      true,
    );
  }
}

export function demoLeaveCalendar(record: HrRequest): Blob {
  if (
    record.request_type !== 'leave' ||
    record.status !== 'approved' ||
    !record.start_date ||
    !record.end_date
  )
    throw new ApiError(409);
  const end = new Date(record.end_date + 'T00:00:00Z');
  end.setUTCDate(end.getUTCDate() + 1);
  const compact = (value: string) => value.replaceAll('-', '');
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//PostTech//Demo//RU',
    'BEGIN:VEVENT',
    `UID:leave-${record.id}@posttech.demo`,
    `DTSTAMP:${new Date()
      .toISOString()
      .replace(/[-:]/g, '')
      .replace(/\.\d{3}/, '')}`,
    `DTSTART;VALUE=DATE:${compact(record.start_date)}`,
    `DTEND;VALUE=DATE:${compact(end.toISOString().slice(0, 10))}`,
    'SUMMARY:Демо — отпуск',
    'CLASS:PRIVATE',
    'END:VEVENT',
    'END:VCALENDAR',
    '',
  ];
  return new Blob([lines.join('\r\n')], { type: 'text/calendar' });
}
