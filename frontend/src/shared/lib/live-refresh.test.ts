import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { watchVisible } from './live-refresh';

let documentTarget: EventTarget & { visibilityState: string };
beforeEach(() => {
  vi.useFakeTimers();
  documentTarget = Object.assign(new EventTarget(), { visibilityState: 'visible' });
  vi.stubGlobal('document', documentTarget);
  vi.stubGlobal('window', new EventTarget());
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test('refreshes serially and ignores overlapping focus events', async () => {
  let finish!: () => void;
  const load = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const stop = watchVisible(load);
  window.dispatchEvent(new Event('focus'));
  await vi.advanceTimersByTimeAsync(3000);
  expect(load).toHaveBeenCalledTimes(1);
  finish();
  await vi.advanceTimersByTimeAsync(1000);
  expect(load).toHaveBeenCalledTimes(2);
  stop();
  finish();
  await vi.advanceTimersByTimeAsync(3000);
  expect(load).toHaveBeenCalledTimes(2);
});

test('pauses hidden tabs, resumes on visibility and aborts stale callbacks', async () => {
  documentTarget.visibilityState = 'hidden';
  const load = vi.fn(async (_signal: AbortSignal) => {});
  const stop = watchVisible(load);
  await vi.advanceTimersByTimeAsync(3000);
  expect(load).not.toHaveBeenCalled();
  documentTarget.visibilityState = 'visible';
  documentTarget.dispatchEvent(new Event('visibilitychange'));
  await vi.advanceTimersByTimeAsync(0);
  expect(load).toHaveBeenCalledTimes(1);
  const signal = load.mock.calls[0][0];
  stop();
  expect(signal.aborted).toBe(true);
  window.dispatchEvent(new Event('focus'));
  await vi.advanceTimersByTimeAsync(3000);
  expect(load).toHaveBeenCalledTimes(1);
});

test('a failed request does not stop subsequent refreshes', async () => {
  const load = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(undefined);
  const stop = watchVisible(load);
  await vi.advanceTimersByTimeAsync(1000);
  expect(load).toHaveBeenCalledTimes(2);
  stop();
});
