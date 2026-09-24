create table if not exists public.system_config (
  key text primary key,
  value text not null,
  updated_at timestamptz not null default now()
);

alter table public.system_config enable row level security;
revoke all on public.system_config from anon, authenticated;
grant select, insert, update, delete on public.system_config to service_role;
