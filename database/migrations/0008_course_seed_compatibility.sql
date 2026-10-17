-- Legacy seed/import clients do not supply family_id. Each imported course is
-- its own version family; the editor explicitly preserves it when cloning.
begin;
alter table public.courses alter column family_id set default gen_random_uuid();
notify pgrst,'reload schema';
commit;
