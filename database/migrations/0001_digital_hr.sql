create extension if not exists pgcrypto;

create type public.app_role as enum ('worker', 'manager', 'hr_admin');
create type public.hr_request_type as enum ('leave', 'advance');
create type public.hr_request_status as enum ('pending', 'approved', 'rejected', 'cancelled');
create type public.course_status as enum ('not_started', 'in_progress', 'completed');

create table public.employee_profiles (
    id uuid primary key default gen_random_uuid(),
    auth_user_id uuid not null unique references auth.users(id) on delete cascade,
    employee_code text not null unique,
    full_name text not null,
    email text not null,
    company text not null,
    job_title text not null,
    department text not null,
    manager_id uuid references public.employee_profiles(id) on delete set null,
    hired_at date not null,
    vacation_days_remaining numeric(5, 1) not null default 0 check (vacation_days_remaining >= 0),
    role public.app_role not null default 'worker',
    external_source text not null default 'mock-1c-zup',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table public.hr_requests (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid not null references public.employee_profiles(id) on delete cascade,
    request_type public.hr_request_type not null,
    status public.hr_request_status not null default 'pending',
    start_date date,
    end_date date,
    amount numeric(12, 2),
    comment text not null default '',
    reviewer_comment text,
    reviewed_by uuid references public.employee_profiles(id) on delete set null,
    reviewed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint hr_request_payload_valid check (
        (request_type = 'leave' and start_date is not null and end_date is not null and end_date >= start_date and amount is null)
        or (request_type = 'advance' and amount is not null and amount > 0 and start_date is null and end_date is null)
    )
);

create table public.notifications (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid not null references public.employee_profiles(id) on delete cascade,
    request_id uuid references public.hr_requests(id) on delete cascade,
    notification_type text not null,
    title text not null,
    body text not null,
    read_at timestamptz,
    created_at timestamptz not null default now()
);

create table public.courses (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    description text not null,
    duration_minutes integer not null default 0 check (duration_minutes >= 0),
    material_markdown text not null,
    quiz jsonb not null default '[]'::jsonb,
    active boolean not null default true,
    created_at timestamptz not null default now()
);

create table public.course_assignments (
    id uuid primary key default gen_random_uuid(),
    course_id uuid not null references public.courses(id) on delete cascade,
    employee_id uuid not null references public.employee_profiles(id) on delete cascade,
    status public.course_status not null default 'not_started',
    progress_percent integer not null default 0 check (progress_percent between 0 and 100),
    score_percent numeric(5, 2) check (score_percent between 0 and 100),
    assigned_by uuid references public.employee_profiles(id) on delete set null,
    assigned_at timestamptz not null default now(),
    completed_at timestamptz,
    unique (course_id, employee_id)
);

create table public.knowledge_articles (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    content text not null,
    source_title text not null,
    source_url text,
    keywords text[] not null default '{}',
    active boolean not null default true,
    created_at timestamptz not null default now()
);

create index employee_profiles_manager_idx on public.employee_profiles(manager_id);
create index hr_requests_employee_created_idx on public.hr_requests(employee_id, created_at desc);
create index hr_requests_status_idx on public.hr_requests(status);
create index notifications_employee_created_idx on public.notifications(employee_id, created_at desc);
create index course_assignments_employee_idx on public.course_assignments(employee_id, assigned_at desc);
create index knowledge_articles_active_idx on public.knowledge_articles(active);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger employee_profiles_set_updated_at
before update on public.employee_profiles
for each row execute function public.set_updated_at();

create trigger hr_requests_set_updated_at
before update on public.hr_requests
for each row execute function public.set_updated_at();

-- All application data is accessed through the authenticated FastAPI layer.
-- The API uses the Supabase server key and enforces role/ownership checks.
-- Browser clients using the public key are denied by default until explicit
-- least-privilege policies are introduced.
alter table public.employee_profiles enable row level security;
alter table public.hr_requests enable row level security;
alter table public.notifications enable row level security;
alter table public.courses enable row level security;
alter table public.course_assignments enable row level security;
alter table public.knowledge_articles enable row level security;
