begin;
alter table public.knowledge_articles add column revision integer not null default 1;
alter table public.knowledge_articles add column draft jsonb;
alter table public.knowledge_articles add column editorial_state text not null default 'legacy'
 check(editorial_state in ('legacy','draft','published','archived'));
create table public.knowledge_events (
 id uuid primary key default gen_random_uuid(), article_id uuid not null references public.knowledge_articles(id),
 actor_id uuid not null references public.employee_profiles(id), action text not null,
 revision integer not null, snapshot jsonb not null, created_at timestamptz not null default now()
);
alter table public.knowledge_events enable row level security;
revoke all on public.knowledge_events from anon,authenticated;
grant all on public.knowledge_events to service_role;
grant insert,update,select on public.knowledge_articles to service_role;
create function public.edit_knowledge_article(p_actor_id uuid,p_id uuid,p_action text,p_revision integer,p_data jsonb,p_due date default null)
returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare article knowledge_articles; content_value jsonb;
begin
 if not exists(select 1 from employee_profiles where id=p_actor_id and role='hr_admin') then raise exception using errcode='PT403',message='HR role required'; end if;
 perform pg_advisory_xact_lock(hashtextextended('knowledge:'||p_id::text,0));
 select * into article from knowledge_articles where id=p_id for update;
 if p_action='create' and article.id is not null then return to_jsonb(article); end if;
 if p_action<>'create' then
  if article.id is null then raise exception using errcode='PT404',message='Source not found'; end if;
  if article.revision<>p_revision then raise exception using errcode='PT409',message='Источник изменён другим HR. Обновите страницу'; end if;
 end if;
 if p_action in ('create','save') then
  if length(btrim(coalesce(p_data->>'title','')))<3 or length(btrim(coalesce(p_data->>'content','')))<3 or length(btrim(coalesce(p_data->>'source_title','')))<3 then raise exception using errcode='PT422',message='Title, text and source required'; end if;
  if p_action='create' then
   insert into knowledge_articles(id,title,content,source_title,active,draft,editorial_state)
    values(p_id,p_data->>'title',p_data->>'content',p_data->>'source_title',false,p_data,'draft');
  else update knowledge_articles set draft=p_data,revision=revision+1 where id=p_id; end if;
 elsif p_action='approve' then
  if p_due is null or p_due<=(now() at time zone 'Asia/Almaty')::date then raise exception using errcode='PT422',message='Future review date required'; end if;
  content_value:=coalesce(article.draft,to_jsonb(article));
  update knowledge_articles set title=content_value->>'title',content=content_value->>'content',source_title=content_value->>'source_title',
   source_url=nullif(content_value->>'source_url',''),keywords=array(select jsonb_array_elements_text(coalesce(content_value->'keywords','[]'))),
   active=true,editorial_state='published',draft=null,revision=revision+1,version=(revision+1)::text where id=p_id;
  -- Separate statement: the existing content-change trigger invalidates old review dates.
  update knowledge_articles set reviewed_at=now(),review_due_at=p_due where id=p_id;
 elsif p_action='archive' then
  update knowledge_articles set active=false,editorial_state='archived',revision=revision+1 where id=p_id;
 else raise exception using errcode='PT422',message='Unknown action'; end if;
 select * into article from knowledge_articles where id=p_id;
 insert into knowledge_events(article_id,actor_id,action,revision,snapshot) values(p_id,p_actor_id,p_action,article.revision,to_jsonb(article));
 return to_jsonb(article);
end $$;
revoke execute on function public.edit_knowledge_article(uuid,uuid,text,integer,jsonb,date) from public,anon,authenticated;
grant execute on function public.edit_knowledge_article(uuid,uuid,text,integer,jsonb,date) to service_role;
notify pgrst,'reload schema';
commit;
