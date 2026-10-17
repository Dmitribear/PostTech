-- A manager approval is an intermediate decision; HR makes the final decision.
alter type public.hr_request_status
    add value if not exists 'pending_hr' after 'pending';

alter table public.hr_requests
    add column if not exists manager_reviewed_by uuid
        references public.employee_profiles(id) on delete set null,
    add column if not exists manager_reviewed_at timestamptz,
    add column if not exists manager_reviewer_comment text,
    add column if not exists hr_reviewed_by uuid
        references public.employee_profiles(id) on delete set null,
    add column if not exists hr_reviewed_at timestamptz,
    add column if not exists hr_reviewer_comment text;