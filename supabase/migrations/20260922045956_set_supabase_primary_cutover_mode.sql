
insert into public.system_config(key,value,updated_at) values
  ('platform_primary','SUPABASE',now()),
  ('google_sheet_dashboard','FROZEN_LEGACY',now()),
  ('cutover_state','VALIDATING_BEFORE_DISCONNECT',now())
on conflict (key) do update set value=excluded.value, updated_at=excluded.updated_at;
