import { describe, expect, it, vi } from 'vitest';
import { createLiveApi, SESSION_KEY, validateTelegramLink } from './api';
import { createDemoApi } from './demo';

const expires_at = () => new Date(Date.now() + 300_000).toISOString();
const link = () => ({ url: 'https://t.me/PostTech_test_bot?start=one_use-token_123', expires_at: expires_at() });
const status = { enabled: true, linked: false, telegram_username: null, notifications_enabled: false, bot_username: 'PostTech_test_bot' };

describe('Telegram integration', () => {
  it('authenticates all operations through the shared session and keeps link creation explicit', async () => {
    const session = { user_id: 'u1', email: 'test@example.test', access_token: 'access', refresh_token: 'refresh', token_type: 'bearer', expires_in: 3600, expires_at: Date.now() + 3_600_000 };
    const transport = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer access');
      if (init?.method === 'POST') return Response.json(link());
      if (init?.method === 'DELETE') return new Response(null, { status: 204 });
      if (init?.method === 'PATCH') return Response.json({ ...status, linked: true, notifications_enabled: true });
      return Response.json(status);
    });
    const api = createLiveApi({ fetch: transport, storage: { getItem: key => key === SESSION_KEY ? JSON.stringify(session) : null, setItem: () => {}, removeItem: () => {} } });
    expect(transport).not.toHaveBeenCalled();
    await expect(api.getTelegramStatus()).resolves.toEqual(status);
    expect(transport.mock.calls[0][0]).toBe('/api/v1/telegram/status');
    expect(transport.mock.calls[0][1]?.method).toBeUndefined();
    await expect(api.createTelegramLink()).resolves.toMatchObject({ url: link().url });
    expect(transport.mock.calls[1][0]).toBe('/api/v1/telegram/link');
    await expect(api.setTelegramNotifications(true)).resolves.toMatchObject({ notifications_enabled: true });
    expect(transport.mock.calls[2][0]).toBe('/api/v1/telegram/settings');
    expect(JSON.parse(String(transport.mock.calls[2][1]?.body))).toEqual({ notifications_enabled: true });
    await expect(api.unlinkTelegram()).resolves.toBeUndefined();
    expect(transport.mock.calls[3][1]?.method).toBe('DELETE');
  });

  it.each([
    'https://evil.example/PostTech_test_bot?start=secret',
    'javascript:alert(1)',
    'http://t.me/PostTech_test_bot?start=secret',
    'https://person:password@t.me/PostTech_test_bot?start=secret',
    'https://t.me/PostTech_test_bot?start=secret&start=other',
    'https://t.me/PostTech_test_bot?start=secret#fragment',
    'https://t.me/PostTech_test_bot?start=secret&redirect=evil',
  ])('never opens a malformed linking destination: %s', url => {
    expect(() => validateTelegramLink({ url, expires_at: expires_at() })).toThrow('некорректную ссылку');
  });

  it('does not show expired or invalid linking secrets', () => {
    expect(() => validateTelegramLink({ ...link(), expires_at: 'invalid' })).toThrow();
    expect(() => validateTelegramLink({ ...link(), expires_at: '2000-01-01T00:00:00Z' })).toThrow();
    expect(validateTelegramLink(link()).url).toBe(link().url);
  });

  it('never pretends to connect a demo account', async () => {
    const demo = createDemoApi();
    await expect(demo.getTelegramStatus()).resolves.toMatchObject({ enabled: false, linked: false });
    await expect(demo.createTelegramLink()).rejects.toMatchObject({ status: 403 });
    await expect(demo.unlinkTelegram()).rejects.toMatchObject({ status: 403 });
    await expect(demo.setTelegramNotifications(true)).rejects.toMatchObject({ status: 403 });
  });
});
