import { afterEach, describe, expect, it } from 'vitest';
import { getLocale, setLocale, t, tx, localizedDate } from './i18n';
import { notificationHref, pluralDays } from './format';
import type { Notification } from './types';

afterEach(()=>setLocale('ru'));
describe('Russian and Kazakh user journeys',()=>{
 it('translates authentication, requests, learning and helpdesk',()=>{
  setLocale('kk');
  for(const label of ['Войти','Создать аккаунт','Восстановить пароль','Оформить отпуск','Отправить заявку','На согласовании','Уведомления','Моё обучение','Замещение','Редактор курсов','Передать вопрос в HR'])expect(t(label)).not.toBe(label);
  expect(pluralDays(24)).toBe('24 күн');
  expect(localizedDate(new Date('2026-10-17T12:00:00Z'),{day:'numeric',month:'long',year:'numeric'})).toBe('17 қазан 2026');
  expect(t('Порог 80%')).toBe('Өту балы 80%');
  setLocale('ru');expect(t('Войти')).toBe('Войти');expect(getLocale()).toBe('ru');
 });
 it('preserves authored content and non-text React values',()=>{
  setLocale('kk');expect(tx('Планирую отпуск с семьёй в декабре')).toBe('Планирую отпуск с семьёй в декабре');expect(tx(24)).toBe(24);expect(tx(null)).toBe(null);
 });
 it('opens HR answers from notifications',()=>{expect(notificationHref({ticket_id:'ticket',notification_type:'hr_ticket_answered'} as Notification)).toBe('/support?ticket=ticket');});
});
