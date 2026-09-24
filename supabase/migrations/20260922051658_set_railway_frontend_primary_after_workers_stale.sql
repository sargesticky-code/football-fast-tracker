
insert into public.system_config(key,value,updated_at) values
  ('dashboard_primary_url','https://fast-tracker-public-production.up.railway.app/',now()),
  ('frontend_primary_host','RAILWAY',now()),
  ('cloudflare_workers_state','STALE_DEPLOY_CREDENTIALS_MISSING',now())
on conflict (key) do update set value=excluded.value, updated_at=excluded.updated_at;
