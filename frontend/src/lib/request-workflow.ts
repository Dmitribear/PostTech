import type { AppRole, HrRequest } from './types';

export function isAwaitingDecision(status: string | undefined): boolean {
  return status === 'pending' || status === 'pending_hr';
}

/** The server is authoritative; the fallback is only for older response fixtures. */
export function canReviewRequest(record: HrRequest, actorId: string, role: AppRole): boolean {
  if (record.employee_id === actorId || !isAwaitingDecision(record.status) || role === 'worker') return false;
  if (record.can_review !== undefined) return record.can_review;
  if (record.status === 'pending_hr') return role === 'hr_admin';
  return record.approvers?.some(person => person.id === actorId) === true;
}
