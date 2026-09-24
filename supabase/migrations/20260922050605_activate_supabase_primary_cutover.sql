
insert into public.system_config(key,value,updated_at) values
  ('platform_primary','SUPABASE',now()),
  ('google_sheet_dashboard','FROZEN_NO_PRODUCTION_DEPENDENCY',now()),
  ('cutover_state','SUPABASE_PRIMARY_ACTIVE',now())
on conflict (key) do update set value=excluded.value, updated_at=excluded.updated_at;
