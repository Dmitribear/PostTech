import { createLiveApi, SESSION_KEY } from '@/shared/api/api';
import type { AuthResponse, AuthSession } from '@/shared/api/contracts';
import { afterEach, describe, expect, it, vi } from 'vitest';

const auth: AuthResponse = {
  user_id: 'user-1',
  email: 'employee@example.test',
  access_token: 'access-1',
  refresh_token: 'refresh-1',
  token_type: 'bearer',
  expires_in: 3600,
};
const session = (): AuthSession => ({
  ...auth,
  expires_at: Date.now() + 3_600_000,
});
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

function storage(initial: AuthSession | null = null) {
  const values = new Map(initial ? [[SESSION_KEY, JSON.stringify(initial)]] : []);
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    removeItem: (key: string) => void values.delete(key),
  };
}

function browser(initial: AuthSession | null = session()) {
  const localStorage = storage(initial);
  const sessionStorage = storage();
  const target = Object.assign(new EventTarget(), {
    localStorage,
    sessionStorage,
  });
  let queue: Promise<unknown> = Promise.resolve();
  const request = vi.fn((_name: string, action: () => Promise<unknown>) => {
    const result = queue.then(action);
    queue = result.catch(() => {});
    return result;
  });
  vi.stubGlobal('window', target);
  vi.stubGlobal('navigator', { locks: { request } });
  const changed = (key: string | null = SESSION_KEY) =>
    target.dispatchEvent(Object.assign(new Event('storage'), { key, storageArea: localStorage }));
  return { localStorage, sessionStorage, target, request, changed };
}

afterEach(() => vi.unstubAllGlobals());

describe('shared browser session', () => {
  it('restores a login in a new tab without logging in again', async () => {
    browser(null);
    const fetch = vi.fn(async () => json(auth));
    await createLiveApi({ fetch }).login(auth.email, 'Password123');
    const second = createLiveApi({ fetch });
    expect(second.getSession()?.user_id).toBe(auth.user_id);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('migrates the old tab session and never restores it after shared logout', () => {
    const env = browser(null);
    env.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session()));
    const first = createLiveApi();
    expect(first.getSession()?.access_token).toBe(auth.access_token);
    expect(env.sessionStorage.getItem(SESSION_KEY)).toBeNull();
    first.logout();
    // An old tab still has a copy from before the application update.
    env.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session()));
    expect(createLiveApi().getSession()).toBeNull();
    expect(env.sessionStorage.getItem(SESSION_KEY)).toBeNull();
  });

  it('notifies already open tabs about login, token rotation and logout', async () => {
    const env = browser(null);
    const listener = vi.fn();
    const first = createLiveApi();
    const unsubscribe = first.subscribeSession(listener);
    const second = createLiveApi({ fetch: vi.fn(async () => json(auth)) });
    await second.login(auth.email, 'Password123');
    env.changed();
    expect(listener).toHaveBeenLastCalledWith(expect.objectContaining({ user_id: auth.user_id }));
    const rotated = {
      ...session(),
      access_token: 'access-2',
      refresh_token: 'refresh-2',
    };
    env.localStorage.setItem(SESSION_KEY, JSON.stringify(rotated));
    env.changed();
    expect(first.getSession()?.refresh_token).toBe('refresh-2');
    second.logout();
    env.changed();
    expect(first.getSession()).toBeNull();
    expect(listener).toHaveBeenLastCalledWith(null);
    unsubscribe();
    const calls = listener.mock.calls.length;
    env.localStorage.setItem(SESSION_KEY, JSON.stringify(session()));
    env.changed();
    expect(listener).toHaveBeenCalledTimes(calls);
  });

  it('handles clearing site storage and ignores unrelated storage events', () => {
    const env = browser();
    const api = createLiveApi();
    const listener = vi.fn();
    api.subscribeSession(listener);
    env.changed('other-setting');
    expect(listener).not.toHaveBeenCalled();
    env.localStorage.removeItem(SESSION_KEY);
    env.changed(null);
    expect(api.getSession()).toBeNull();
    expect(listener).toHaveBeenCalledWith(null);
  });

  it('serializes refresh across tabs and reuses the rotated token', async () => {
    const env = browser();
    const fetch = vi.fn(async () =>
      json({ ...auth, access_token: 'access-2', refresh_token: 'refresh-2' }),
    );
    const first = createLiveApi({ fetch });
    const second = createLiveApi({ fetch });
    const sessions = await Promise.all([first.refreshSession(), second.refreshSession()]);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(env.request).toHaveBeenCalledTimes(2);
    expect(sessions.map((value) => value.refresh_token)).toEqual(['refresh-2', 'refresh-2']);
  });

  it('cannot restore a session after logout in another tab during refresh', async () => {
    browser();
    let resolve!: (response: Response) => void;
    let started!: () => void;
    const ready = new Promise<void>((done) => {
      started = done;
    });
    const first = createLiveApi({
      fetch: vi.fn(
        () =>
          new Promise<Response>((done) => {
            resolve = done;
            started();
          }),
      ),
    });
    const second = createLiveApi();
    const pending = first.refreshSession();
    await ready;
    second.logout();
    resolve(json({ ...auth, access_token: 'late-access' }));
    await expect(pending).rejects.toMatchObject({ status: 401 });
    expect(first.getSession()).toBeNull();
    expect(createLiveApi().getSession()).toBeNull();
  });

  it('never replays a mutation as an account selected in another tab', async () => {
    browser();
    let resolve!: (response: Response) => void;
    const fetch = vi.fn(
      () =>
        new Promise<Response>((done) => {
          resolve = done;
        }),
    );
    const first = createLiveApi({ fetch });
    const second = createLiveApi({
      fetch: vi.fn(async () =>
        json({
          ...auth,
          user_id: 'user-2',
          access_token: 'other-access',
          refresh_token: 'other-refresh',
        }),
      ),
    });
    const pending = first.createRequest({
      request_type: 'advance',
      amount: 5000,
    });
    await second.login('other@example.test', 'Password123');
    // Even if the storage event is delayed, the response must be discarded.
    resolve(json({}, 401));
    await expect(pending).rejects.toMatchObject({ status: 401 });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(first.getSession()?.user_id).toBe('user-2');
  });

  it('falls back to tab storage when shared storage is blocked', () => {
    const env = browser(null);
    env.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session()));
    Object.defineProperty(env.target, 'localStorage', {
      get() {
        throw new Error('Blocked');
      },
    });
    const api = createLiveApi();
    expect(api.getSession()?.access_token).toBe(auth.access_token);
    api.logout();
    expect(env.sessionStorage.getItem(SESSION_KEY)).toBeNull();
  });
});
