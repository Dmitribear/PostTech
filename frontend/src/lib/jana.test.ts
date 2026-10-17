import { describe, expect, it, vi } from 'vitest';
import { createLiveApi, SESSION_KEY } from './api';
import { createDemoApi } from './demo';
import { LocalDemoJana } from './localJana';

const id = '30000000-0000-4000-8000-000000000001';
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const ics = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n';
const file = () => new Response(ics, { headers: { 'Content-Type': 'text/calendar; charset=utf-8' } });
const auth = { access_token: 'old-access', refresh_token: 'refresh', user_id: 'test-user', email: 'test@example.test', token_type: 'bearer', expires_in: 3600 };
function storage() {
  return { getItem: (key: string) => key === SESSION_KEY ? JSON.stringify({ ...auth, expires_at: Date.now() + 3600_000 }) : null, setItem: vi.fn(), removeItem: vi.fn() };
}

describe('authenticated Jana and calendar', () => {
  it('sends a question and reads its full source through the configured API with Bearer auth', async () => {
    const transport = vi.fn<typeof fetch>(async () => json({ id }));
    const api = createLiveApi({ baseUrl: '/hr/api/v1', fetch: transport, storage: storage() });
    await api.askJana('Хочу отдохнуть, что делать?');
    await api.getJanaSource(id);
    expect(transport.mock.calls[0][0]).toBe('/hr/api/v1/ai/ask');
    expect(JSON.parse(String(transport.mock.calls[0][1]?.body))).toEqual({ question: 'Хочу отдохнуть, что делать?' });
    expect(transport.mock.calls[1][0]).toBe(`/hr/api/v1/ai/sources/${id}`);
    for (const call of transport.mock.calls) expect(new Headers(call[1]?.headers).get('Authorization')).toBe('Bearer old-access');
  });

  it('rejects an untrusted source path without sending credentials', async () => {
    const transport = vi.fn<typeof fetch>(async () => json({}));
    const api = createLiveApi({ fetch: transport, storage: storage() });
    await expect(api.getJanaSource('https://untrusted.example/steal')).rejects.toMatchObject({ status: 502 });
    await expect(api.getJanaSource('../profile')).rejects.toMatchObject({ status: 502 });
    expect(transport).not.toHaveBeenCalled();
  });

  it('refreshes an expired token and downloads an ICS blob with the new token', async () => {
    const transport = vi.fn<typeof fetch>(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/auth/refresh')) return json({ ...auth, access_token: 'new-access' });
      expect(new Headers(init?.headers).get('Accept')).toBe('text/calendar');
      if (new Headers(init?.headers).get('Authorization') === 'Bearer old-access') return json({ detail: 'expired' }, 401);
      expect(String(input)).toBe(`/api/v1/requests/${id}/calendar.ics`);
      return file();
    });
    const api = createLiveApi({ fetch: transport, storage: storage() });
    expect(await (await api.getLeaveCalendar(id)).text()).toBe(ics);
    expect(transport).toHaveBeenCalledTimes(3);
  });

  it.each([403, 409, 503])('does not download a JSON error for status %s', async status => {
    const api = createLiveApi({ storage: storage(), fetch: vi.fn(async () => json({ detail: 'Calendar export requires an approved leave request' }, status)) });
    await expect(api.getLeaveCalendar(id)).rejects.toMatchObject({ status });
  });

  it('does not save the SPA HTML as an ICS file', async () => {
    const api = createLiveApi({ storage: storage(), fetch: vi.fn(async () => new Response('<html/>', { headers: { 'Content-Type': 'text/html' } })) });
    await expect(api.getLeaveCalendar(id)).rejects.toMatchObject({ status: 502 });
  });

  it('rejects a download completed after sign-out', async () => {
    let resolve!: (value: Response) => void;
    const api = createLiveApi({ storage: storage(), fetch: vi.fn(() => new Promise<Response>(done => { resolve = done; })) });
    const pending = api.getLeaveCalendar(id);
    api.logout(); resolve(file());
    await expect(pending).rejects.toMatchObject({ status: 401 });
  });
});

describe('explicit local demonstration bridge', () => {
  it('preserves the actual model refusal and never forwards an HR token', async () => {
    const refusal = { answer: 'В базе нет ответа.', grounded: false, escalation_suggested: true, sources: [], mode: 'refusal' };
    const transport = vi.fn<typeof fetch>(async () => json(refusal));
    const api = createDemoApi('worker', new LocalDemoJana('/jana-demo', transport));
    expect(api.janaAvailable).toBe(true);
    expect(await api.askJana('Какая погода завтра?')).toEqual(refusal);
    expect(transport.mock.calls[0][0]).toBe('/jana-demo/api/v1/ai/ask');
    expect(new Headers(transport.mock.calls[0][1]?.headers).has('Authorization')).toBe(false);
    expect(transport.mock.calls[0][1]?.credentials).toBe('omit');
  });

  it('keeps a model outage as an error without a keyword or paid fallback', async () => {
    const api = createDemoApi('worker', new LocalDemoJana('/jana-demo', vi.fn(async () => json({ detail: 'Jana AI is temporarily unavailable' }, 503))));
    await expect(api.askJana('Как оформить отпуск?')).rejects.toMatchObject({ status: 503 });
  });

  it('exports only approved demo leave with its actual displayed dates', async () => {
    const transport = vi.fn<typeof fetch>(async () => file());
    const api = createDemoApi('worker', new LocalDemoJana('/jana-demo', transport));
    const records = await api.getRequests();
    const approved = records.find(record => record.request_type === 'leave' && record.status === 'approved')!;
    const pending = records.find(record => record.status === 'pending')!;
    await api.getLeaveCalendar(approved.id);
    expect(JSON.parse(String(transport.mock.calls[0][1]?.body))).toEqual({ id: approved.id, start_date: approved.start_date, end_date: approved.end_date });
    await expect(api.getLeaveCalendar(pending.id)).rejects.toMatchObject({ status: 409 });
    expect(transport).toHaveBeenCalledTimes(1);
  });
});
