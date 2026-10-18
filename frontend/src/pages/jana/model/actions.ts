import type { AppRole, JanaAction, JanaAnswer } from '@/shared/api/contracts';

const destinations = {
  leave_new: { href: '/calendar?select=1', label: 'Оформить отпуск', icon: 'plane' },
  advance_new: { href: '/requests/new?type=advance', label: 'Запросить аванс', icon: 'wallet' },
  requests_mine: { href: '/requests', label: 'Мои заявки', icon: 'clipboard' },
  academy: { href: '/academy', label: 'Обучение', icon: 'graduation' },
  profile: { href: '/profile', label: 'Мой профиль', icon: 'user' },
  calendar: { href: '/calendar', label: 'Календарь', icon: 'calendar' },
  notifications: { href: '/notifications', label: 'Уведомления', icon: 'bell' },
  requests_review: { href: '/requests?scope=review', label: 'Согласования', icon: 'check-circle' },
  support: { href: '/support', label: 'Обратиться в HR', icon: 'message' },
} as const;

type DestinationId = keyof typeof destinations;
export type AnswerAction = JanaAction & { icon: string };

export function answerActions(answer: JanaAnswer, role: AppRole): AnswerAction[] {
  if (!answer.grounded || answer.mode === 'refusal' || !Array.isArray(answer.actions)) return [];

  const selected = new Map<string, AnswerAction>();
  for (const action of answer.actions) {
    if (!action || typeof action.id !== 'string' || !Object.hasOwn(destinations, action.id))
      continue;
    const destination = destinations[action.id as DestinationId];
    if (action.href !== destination.href) continue;
    if (action.id === 'requests_review' && !['manager', 'director', 'hr_admin'].includes(role))
      continue;
    selected.set(action.id, { id: action.id, ...destination });
  }
  return [...selected.values()];
}
