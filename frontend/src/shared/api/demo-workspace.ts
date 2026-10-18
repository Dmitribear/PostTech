import { ApiError } from './api';
import type { AppRole, HrApi } from './contracts';
import { DemoApi, type DemoSnapshot } from './demo';

const storageKey = 'posttech.demo-workspace.v1';
const mutations = new Set([
  'createRequest',
  'reviewRequest',
  'cancelRequest',
  'markNotificationRead',
  'assignEmployeeRole',
  'assignCourse',
  'updateCourseProgress',
  'enrollExternalCourse',
  'createPersonalCourse',
  'completeCourse',
]);
let pending: Promise<unknown> = Promise.resolve();

function serialized<T>(run: () => Promise<T>): Promise<T> {
  if (typeof navigator !== 'undefined' && navigator.locks)
    return navigator.locks.request(storageKey, run);
  const next = pending.then(run, run);
  pending = next.catch(() => undefined);
  return next;
}

function read(storage: Pick<Storage, 'getItem' | 'setItem'>): DemoSnapshot {
  const saved = storage.getItem(storageKey);
  if (saved) {
    const data = JSON.parse(saved) as DemoSnapshot;
    if (
      [
        'employees',
        'assignments',
        'requests',
        'history',
        'notifications',
        'attempts',
        'idempotency',
        'quizKeys',
      ].every((key) => Array.isArray(data[key as keyof DemoSnapshot]))
    )
      return data;
    throw new Error('Invalid demo snapshot');
  }
  const initial = new DemoApi('worker').snapshot();
  storage.setItem(storageKey, JSON.stringify(initial));
  return initial;
}

export function createSharedDemoApi(
  role: AppRole,
  storage?: Pick<Storage, 'getItem' | 'setItem'>,
): HrApi {
  const target = new DemoApi(role);
  return new Proxy(target, {
    get(api, key, receiver) {
      const method = Reflect.get(api, key, receiver);
      if (typeof method !== 'function') return method;
      if (key === 'askJana' || key === 'getKnowledgeSource') return method.bind(api);
      return (...args: unknown[]) =>
        serialized(async () => {
          let store: Pick<Storage, 'getItem' | 'setItem'>;
          try {
            store = storage ?? localStorage;
            api.restore(read(store));
          } catch {
            throw new ApiError(
              503,
              'Не удалось открыть данные демоверсии. Проверьте доступ к хранилищу браузера.',
            );
          }
          const result = await method.apply(api, args);
          if (mutations.has(String(key))) {
            try {
              store.setItem(storageKey, JSON.stringify(api.snapshot()));
            } catch {
              throw new ApiError(
                503,
                'Не удалось сохранить изменения демоверсии. Проверьте доступ к хранилищу браузера.',
              );
            }
          }
          return result;
        });
    },
  });
}
