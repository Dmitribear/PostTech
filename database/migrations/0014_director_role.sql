-- The enum change must commit before functions use the new value.
alter type public.app_role add value if not exists 'director';
