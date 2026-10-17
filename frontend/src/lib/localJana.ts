import { ApiError, calendarBlob, janaSourcePath } from './api';
import { getLocale } from './i18n';
import type { HrRequest, JanaAnswer, KnowledgeSource } from './types';

/** Explicit loopback demo bridge. Never reads or forwards a working HR session. */
export class LocalDemoJana {
  constructor(private readonly baseUrl: string, private readonly transport: typeof fetch = globalThis.fetch.bind(globalThis)) {
    if (!/^\/(?!\/)[a-zA-Z0-9/_-]+$/.test(baseUrl)) throw new Error('Demo Jana must use a same-origin development proxy path');
  }

  private async send<T>(path: string, body?: unknown, calendar = false): Promise<T> {
    let response: Response;
    try {
      response = await this.transport(`${this.baseUrl}${path}`, {
        method: body === undefined ? 'GET' : 'POST', credentials: 'omit',
        headers: { Accept: calendar ? 'text/calendar' : 'application/json', 'Accept-Language': getLocale(), ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch { throw new ApiError(503, 'Локальная Jana недоступна. Запустите сервер демонстрации и попробуйте снова.'); }
    if (response.ok && calendar) return await calendarBlob(response) as T;
    let payload;
    try { payload = await response.json(); }
    catch { throw new ApiError(503, 'Локальная Jana недоступна. Проверьте сервер демонстрации.'); }
    if (!response.ok) throw new ApiError(response.status, payload?.detail);
    return payload as T;
  }

  askJana(question: string): Promise<JanaAnswer> { return this.send('/api/v1/ai/ask', { question }); }
  async getKnowledgeSource(id: string, version?: string | null): Promise<KnowledgeSource> { return this.send(`/api/v1${janaSourcePath(id)}${version ? `?version=${encodeURIComponent(version)}` : ''}`); }
  getLeaveCalendar(record: HrRequest): Promise<Blob> {
    return this.send('/demo/leave.ics', { id: record.id, start_date: record.start_date, end_date: record.end_date }, true);
  }
}
