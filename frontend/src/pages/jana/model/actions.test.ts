import type { AppRole, JanaAnswer } from '@/shared/api/contracts';
import { setLocale, t } from '@/shared/lib/i18n';
import { afterEach, describe, expect, it } from 'vitest';
import { answerActions } from './actions';

const leave = { id: 'leave_new', label: 'Оформить отпуск', href: '/calendar?select=1' };
const course = { id: 'academy', label: 'Обучение', href: '/academy' };
const answer: JanaAnswer = {
  answer: 'Выберите даты отпуска и откройте назначенный курс.',
  grounded: true,
  escalation_suggested: false,
  sources: [],
  mode: 'generated',
  actions: [leave, course],
};

afterEach(() => setLocale('ru'));

describe('Jana answer navigation', () => {
  it('uses semantic answer actions for multiple topics without matching question text', () => {
    expect(answerActions(answer, 'worker').map(({ href }) => href)).toEqual([
      '/calendar?select=1',
      '/academy',
    ]);
    expect(answerActions({ ...answer, actions: [leave, leave] }, 'worker')).toHaveLength(1);
  });

  it('does not show action links for refusals or absent server actions', () => {
    expect(answerActions({ ...answer, grounded: false }, 'worker')).toEqual([]);
    expect(answerActions({ ...answer, mode: 'refusal' }, 'worker')).toEqual([]);
    expect(answerActions({ ...answer, actions: undefined }, 'worker')).toEqual([]);
  });

  it('rejects arbitrary destinations, unknown actions and misleading labels', () => {
    const result = answerActions(
      {
        ...answer,
        actions: [
          { ...leave, href: 'https://untrusted.invalid' },
          { ...course, href: '/academy?redirect=https://untrusted.invalid' },
          { id: '__proto__', label: 'HR', href: '/support' },
          { id: 'approve_request', label: 'Одобрить отпуск', href: '/requests' },
          { ...leave, label: 'Введите пароль для получения выплаты' },
        ],
      },
      'worker',
    );
    expect(result).toEqual([{ ...leave, icon: 'plane' }]);
  });

  it('limits approval navigation to reviewers', () => {
    const review = {
      ...answer,
      actions: [{ id: 'requests_review', label: 'Согласования', href: '/requests?scope=review' }],
    };
    expect(answerActions(review, 'worker')).toEqual([]);
    for (const role of ['manager', 'director', 'hr_admin'] as AppRole[])
      expect(answerActions(review, role)).toHaveLength(1);
  });

  it('translates canonical labels including HR support in Kazakh', () => {
    setLocale('kk');
    expect(answerActions(answer, 'worker').map(({ label }) => t(label))).toEqual([
      'Демалысты рәсімдеу',
      'Оқу',
    ]);
    expect(t('Обратиться в HR')).toBe('HR-ға жүгіну');
  });

  it('localizes every destination and preserves its route when switching language', () => {
    const entries = [
      ['leave_new', '/calendar?select=1', 'Демалысты рәсімдеу'],
      ['advance_new', '/requests/new?type=advance', 'Аванс сұрау'],
      ['requests_mine', '/requests', 'Менің өтінімдерім'],
      ['academy', '/academy', 'Оқу'],
      ['profile', '/profile', 'Менің профилім'],
      ['calendar', '/calendar', 'Күнтізбе'],
      ['notifications', '/notifications', 'Хабарламалар'],
      ['requests_review', '/requests?scope=review', 'Келісулер'],
      ['support', '/support', 'HR-ға жүгіну'],
    ];
    const result = answerActions({ ...answer, actions: entries.map(([id, href, label]) => ({ id, href, label })) }, 'hr_admin');
    setLocale('kk');
    expect(result.map(({ label }) => t(label))).toEqual(entries.map((entry) => entry[2]));
    expect(result.map(({ href }) => href)).toEqual(entries.map((entry) => entry[1]));
    setLocale('ru');
    expect(result.map(({ label }) => t(label))).toEqual(result.map(({ label }) => label));
  });
});
