import { describe, expect, it } from 'vitest';
import { canReviewRequest, isAwaitingDecision } from './request-workflow';
import type { HrRequest } from './types';
const pending = { employee_id: 'worker', status: 'pending', approvers: [{ id: 'manager', role: 'manager', full_name: 'Manager' }] } as HrRequest;
describe('two-stage approvals', () => {
  it('lets a director act only at the assigned management stage', () => {
    const request = { ...pending, approvers: [{ id: 'director', role: 'director' as const, full_name: 'Director' }] };
    expect(canReviewRequest(request, 'director', 'director')).toBe(true);
    expect(canReviewRequest({ ...request, status: 'pending_hr' }, 'director', 'director')).toBe(false);
  });
  it('shows HR the final stage and respects explicit server denial', () => {
    expect(canReviewRequest(pending, 'hr', 'hr_admin')).toBe(false);
    expect(canReviewRequest({ ...pending, status: 'pending_hr' }, 'hr', 'hr_admin')).toBe(true);
    expect(canReviewRequest({ ...pending, status: 'pending_hr', can_review: false }, 'hr', 'hr_admin')).toBe(false);
  });
  it('blocks self review and terminal requests despite an inconsistent permission flag', () => {
    expect(canReviewRequest({ ...pending, can_review: true }, 'worker', 'hr_admin')).toBe(false);
    expect(canReviewRequest({ ...pending, status: 'approved', can_review: true }, 'hr', 'hr_admin')).toBe(false);
  });
  it('treats both stages as pending for reservations and cancellation', () => {
    expect(['pending', 'pending_hr', 'approved', 'rejected', 'cancelled'].filter(isAwaitingDecision)).toEqual(['pending', 'pending_hr']);
  });
});
