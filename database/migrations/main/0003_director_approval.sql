-- Add the director role and the intermediate approval stage.
alter type public.app_role add value if not exists 'director' after 'manager';
alter type public.hr_request_status add value if not exists 'pending_director' after 'pending';

alter table public.hr_requests
    add column if not exists director_reviewed_by uuid
        references public.employee_profiles(id) on delete set null,
    add column if not exists director_reviewed_at timestamptz,
    add column if not exists director_reviewer_comment text;
