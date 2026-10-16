import { describe, expect, it, vi } from 'vitest';
import { ApiError, createLiveApi, fetchAllRequests, SESSION_KEY } from './api';
import { createDemoApi } from './demo';
import { daysBetween, formatDate } from './format';
import type { AuthResponse, AuthSession } from './types';

const auth: AuthResponse = { user_id: 'user-1', email: 'employee@example.com', access_token: 'access-1', refresh_token: 'refresh-1', token_type: 'bearer', expires_in: 3600 };
const refreshed: AuthResponse = { ...auth, access_token: 'access-2', refresh_token: 'refresh-2' };
const requestKey = '00000000-0000-4000-8000-000000000001';
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
const storedSession = (): AuthSession => ({ ...auth, expires_at: Date.now() + 3600_000 });
function memoryStorage(session: AuthSession | null = storedSession()) {
  const data = new Map<string, string>(session ? [[SESSION_KEY, JSON.stringify(session)]] : []);
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => { data.set(key, value); },
    removeItem: (key: string) => { data.delete(key); },
  };
}

describe('live API authentication', () => {
  it('shares one token refresh across concurrent unauthorized calls and retries both with the new token', async () => {
    let refreshCount = 0;
    const calls: string[] = [];
    const transport = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const token = new Headers(init?.headers).get('Authorization');
      calls.push(`${path}:${token}`);
      if (path.endsWith('/auth/refresh')) {
        refreshCount++;
        expect(JSON.parse(String(init?.body))).toEqual({ refresh_token: 'refresh-1' });
        await new Promise(resolve => setTimeout(resolve, 5));
        return json(refreshed);
      }
      if (token === 'Bearer access-1') return json({ detail: 'Invalid or expired access token' }, 401);
      return json(path.endsWith('/profile') ? { full_name: 'Employee' } : []);
    });
    const storage = memoryStorage();
    const api = createLiveApi({ fetch: transport, storage });
    const [profile, team] = await Promise.all([api.getProfile(), api.getTeam()]);
    expect(profile.full_name).toBe('Employee');
    expect(team).toEqual([]);
    expect(refreshCount).toBe(1);
    expect(calls.filter(call => call.endsWith(':Bearer access-2'))).toHaveLength(2);
    expect(JSON.parse(storage.getItem(SESSION_KEY)!).refresh_token).toBe('refresh-2');
  });

  it('does not refresh or erase an unlinked HR account on a 403 response', async () => {
    const transport = vi.fn(async () => json({ detail: 'User has no HR profile; contact an administrator' }, 403));
    const api = createLiveApi({ fetch: transport, storage: memoryStorage() });
    await expect(api.getProfile()).rejects.toMatchObject({ status: 403, message: expect.stringContaining('не связан') });
    expect(transport).toHaveBeenCalledTimes(1);
    expect(api.getSession()?.access_token).toBe(auth.access_token);
  });

  it('clears the session after an invalid refresh token, notifying the application', async () => {
    const storage = memoryStorage();
    const onSessionChange = vi.fn();
    const api = createLiveApi({
      storage, onSessionChange,
      fetch: vi.fn(async (input: RequestInfo | URL) => json({ detail: String(input).endsWith('/auth/refresh') ? 'Invalid or expired refresh token' : 'Invalid or expired access token' }, 401)),
    });
    await expect(api.getProfile()).rejects.toMatchObject({ status: 401 });
    expect(api.getSession()).toBeNull();
    expect(storage.getItem(SESSION_KEY)).toBeNull();
    expect(onSessionChange).toHaveBeenCalledWith(null);
  });

  it('does not restore a logged-out session when an in-flight refresh completes', async () => {
    let resolveRefresh!: (response: Response) => void;
    const api = createLiveApi({ storage: memoryStorage(), fetch: vi.fn(() => new Promise<Response>(resolve => { resolveRefresh = resolve; })) });
    const pending = api.refreshSession();
    api.logout();
    resolveRefresh(json(refreshed));
    await expect(pending).rejects.toMatchObject({ status: 401 });
    expect(api.getSession()).toBeNull();
  });

  it('never replays an old mutation as a newly signed-in account', async () => {
    let resolveMutation!: (response: Response) => void;
    let mutationCount = 0;
    const transport = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/auth/login')) return json({ ...auth, user_id: 'another-user', access_token: 'another-access' });
      mutationCount++;
      return new Promise<Response>(resolve => { resolveMutation = resolve; });
    });
    const api = createLiveApi({ storage: memoryStorage(), fetch: transport });
    const mutation = api.createRequest({ request_type: 'advance', amount: 5000 }, requestKey);
    api.logout();
    await api.login('another@example.com', 'another-password');
    resolveMutation(json({}, 401));
    await expect(mutation).rejects.toMatchObject({ status: 401 });
    expect(mutationCount).toBe(1);
    expect(api.getSession()?.user_id).toBe('another-user');
  });

  it('discards authenticated data if logout occurs while the response body is downloading', async () => {
    let resolveBody!: (value: string) => void;
    let bodyStarted!: () => void;
    const started = new Promise<void>(resolve => { bodyStarted = resolve; });
    const response = new Response('');
    vi.spyOn(response, 'text').mockImplementation(() => {
      bodyStarted();
      return new Promise<string>(resolve => { resolveBody = resolve; });
    });
    const api = createLiveApi({ storage: memoryStorage(), fetch: vi.fn(async () => response) });
    const profile = api.getProfile();
    await started;
    api.logout();
    resolveBody(JSON.stringify({ full_name: 'Previous account' }));
    await expect(profile).rejects.toMatchObject({ status: 401 });
  });

  it('removes malformed stored sessions and rejects malformed successful login payloads', async () => {
    const storage = memoryStorage(null);
    storage.setItem(SESSION_KEY, '{broken-json');
    const api = createLiveApi({ storage, fetch: vi.fn(async () => json({ email: auth.email })) });
    expect(api.getSession()).toBeNull();
    expect(storage.getItem(SESSION_KEY)).toBeNull();
    await expect(api.login(auth.email, 'password123')).rejects.toMatchObject({ status: 502 });
    expect(api.getSession()).toBeNull();
  });

  it('handles email confirmation registration without inventing an authenticated session', async () => {
    const transport = vi.fn(async () => json({ user_id: 'user-1', email: auth.email, email_confirmation_required: true, message: 'Confirm email' }, 201));
    const api = createLiveApi({ fetch: transport, storage: memoryStorage(null) });
    const response = await api.register(auth.email, 'password123');
    expect(response.email_confirmation_required).toBe(true);
    expect(api.getSession()).toBeNull();
  });

  it('keeps the current session on a temporary network failure', async () => {
    const api = createLiveApi({ storage: memoryStorage(), fetch: vi.fn(async () => { throw new TypeError('Failed to fetch'); }) });
    await expect(api.getProfile()).rejects.toMatchObject({ status: 0, message: expect.stringContaining('связаться с сервером') });
    expect(api.getSession()).not.toBeNull();
  });
});

describe('HTTP request contract', () => {
  it('loads every page for request totals while preserving employee and status filters', async () => {
    const transport = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      expect(url.searchParams.get('employee_id')).toBe('employee-1');
      expect(url.searchParams.get('status')).toBe('pending');
      expect(url.searchParams.get('limit')).toBe('100');
      const offset = Number(url.searchParams.get('offset'));
      return json(Array.from({ length: offset === 0 ? 100 : 5 }, (_, index) => ({ id: String(offset + index) })));
    });
    const api = createLiveApi({ storage: memoryStorage(), fetch: transport });
    const requests = await fetchAllRequests(api, { employee_id: 'employee-1', status: 'pending' });
    expect(requests).toHaveLength(105);
    expect(requests[104].id).toBe('104');
    expect(transport).toHaveBeenCalledTimes(2);
  });

  it('preserves the exact request body and idempotency key through token refresh', async () => {
    const bodies: string[] = [];
    const keys: (string | null)[] = [];
    const transport = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/auth/refresh')) return json(refreshed);
      const headers = new Headers(init?.headers);
      bodies.push(String(init?.body));
      keys.push(headers.get('Idempotency-Key'));
      return headers.get('Authorization') === 'Bearer access-1' ? json({}, 401) : json({ id: 'request-1' }, 201);
    });
    const api = createLiveApi({ storage: memoryStorage(), fetch: transport });
    const body = { request_type: 'advance' as const, amount: 50000, comment: 'Аванс' };
    await api.createRequest(body, requestKey);
    expect(keys).toEqual([requestKey, requestKey]);
    expect(bodies).toEqual([JSON.stringify(body), JSON.stringify(body)]);
  });

  it('uses the backend status alias and preserves pagination values in filters', async () => {
    const transport = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json([]));
    const api = createLiveApi({ storage: memoryStorage(), fetch: transport, baseUrl: '/api/v1/' });
    await api.getRequests({ status: 'pending', request_type: 'leave', offset: 0, limit: 100 });
    expect(transport.mock.calls[0][0]).toBe('/api/v1/requests?status=pending&request_type=leave&offset=0&limit=100');
  });

  it('reports server validation details and malformed API responses', async () => {
    const badFields = createLiveApi({ storage: memoryStorage(), fetch: vi.fn(async () => json({ detail: [{ loc: ['body', 'amount'], msg: 'Input should be greater than 0' }] }, 422)) });
    await expect(badFields.createRequest({ request_type: 'advance', amount: -1 })).rejects.toMatchObject({ status: 422, message: expect.stringContaining('greater than 0') });
    const html = createLiveApi({ storage: memoryStorage(), fetch: vi.fn(async () => new Response('<html>App fallback</html>')) });
    await expect(html.getProfile()).rejects.toMatchObject({ status: 502 });
  });
});

describe('explicit demo mode', () => {
  it('creates one request and one event for repeated submissions with the same key', async () => {
    const api = createDemoApi();
    const payload = { request_type: 'advance' as const, amount: 35000, comment: 'Test' };
    const first = await api.createRequest(payload, requestKey);
    const retry = await api.createRequest(payload, requestKey);
    expect(api.mode).toBe('demo');
    expect(retry.id).toBe(first.id);
    expect(await api.getRequestHistory(first.id)).toHaveLength(1);
    await expect(api.createRequest({ ...payload, amount: 36000 }, requestKey)).rejects.toMatchObject({ status: 409 });
  });

  it('enforces review permissions and makes identical review retries safe', async () => {
    const worker = createDemoApi('worker');
    await expect(worker.getTeam()).rejects.toBeInstanceOf(ApiError);
    const ownRequest = (await worker.getRequests({ status: 'pending' }))[0];
    await expect(worker.reviewRequest(ownRequest.id, { status: 'approved' })).rejects.toMatchObject({ status: 403 });

    const manager = createDemoApi('manager');
    const me = await manager.getProfile();
    const teammateRequest = (await manager.getRequests({ status: 'pending' })).find(request => request.employee_id !== me.id)!;
    const approved = await manager.reviewRequest(teammateRequest.id, { status: 'approved', reviewer_comment: 'Согласовано' });
    const retry = await manager.reviewRequest(teammateRequest.id, { status: 'approved', reviewer_comment: 'Согласовано' });
    expect(retry).toEqual(approved);
    expect(await manager.getRequestHistory(teammateRequest.id)).toHaveLength(2);
    await expect(manager.reviewRequest(teammateRequest.id, { status: 'rejected' })).rejects.toMatchObject({ status: 409 });
  });

  it('does not disclose quiz answers and only completes after a full valid submission', async () => {
    const api = createDemoApi();
    const course = (await api.getCourses()).find(item => item.assignment?.status === 'in_progress')!;
    const details = await api.getCourse(course.id);
    expect(details).not.toHaveProperty('correctAnswers');
    expect(details.quiz[0]).not.toHaveProperty('answer_index');
    await expect(api.completeCourse(course.id, {})).rejects.toMatchObject({ status: 422 });
    const advanced = await api.updateCourseProgress(course.id, 80);
    const unchanged = await api.updateCourseProgress(course.id, 20);
    expect(unchanged.progress_percent).toBe(advanced.progress_percent);
    const result = await api.completeCourse(course.id, Object.fromEntries(details.quiz.map(question => [question.id, 1])));
    expect(result.status).toBe('completed');
    expect(result.score_percent).toBe(100);
    await expect(api.updateCourseProgress(course.id, 99)).rejects.toMatchObject({ status: 409 });
  });

  it('marks notifications read idempotently and refuses to fake AI answers without a local bridge', async () => {
    const api = createDemoApi();
    const notification = (await api.getNotifications({ unread_only: true }))[0];
    const first = await api.markNotificationRead(notification.id);
    expect((await api.markNotificationRead(notification.id)).read_at).toBe(first.read_at);
    expect((await api.getNotifications({ unread_only: true })).some(item => item.id === notification.id)).toBe(false);
    expect(api.janaAvailable).toBe(false);
    await expect(api.askJana('Как оформить отпуск?')).rejects.toMatchObject({ status: 503 });
  });
});

describe('calendar date formatting', () => {
  it('counts both calendar endpoints including daylight-saving transitions', () => {
    expect(daysBetween('2026-03-28', '2026-03-30')).toBe(3);
    expect(daysBetween('2026-10-16', '2026-10-16')).toBe(1);
    expect(daysBetween('2026-10-17', '2026-10-16')).toBe(0);
    expect(formatDate('2026-10-16')).toContain('16');
  });
});
