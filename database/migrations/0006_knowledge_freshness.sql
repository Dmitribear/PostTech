-- Knowledge review metadata. This does not certify existing material as approved.
begin;
alter table public.knowledge_articles
    add column if not exists updated_at timestamptz,
    add column if not exists reviewed_at timestamptz,
    add column if not exists review_due_at timestamptz,
    add column if not exists version text not null default '1';
update public.knowledge_articles set updated_at = created_at where updated_at is null;
alter table public.knowledge_articles alter column updated_at set default now();
alter table public.knowledge_articles alter column updated_at set not null;

create or replace function public.invalidate_knowledge_review()
returns trigger language plpgsql set search_path = public as $$
begin
    if (new.title, new.content, new.source_title, new.source_url, new.keywords)
        is distinct from (old.title, old.content, old.source_title, old.source_url, old.keywords) then
        new.updated_at := now();
        -- A content change always requires a separate subsequent review.
        new.reviewed_at := null;
        new.review_due_at := null;
    end if;
    return new;
end;
$$;
create or replace trigger knowledge_review_invalidated
before update on public.knowledge_articles
for each row execute function public.invalidate_knowledge_review();
commit;
