create table if not exists public.phase3_live_fast_snapshot (
    id integer primary key default 1 check (id=1),
    fetched_at timestamptz,
    source text,
    ok boolean not null default false,
    lease_until timestamptz,
    payload jsonb not null default '[]'::jsonb,
    raw jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
  );

  insert into public.phase3_live_fast_snapshot(id)
  values(1)
  on conflict(id) do nothing;

  create table if not exists public.phase3_live_fast_current (
    hkjc_event_id text primary key,
    source text not null,
    source_match_id text,
    match_confidence numeric,
    score_home integer,
    score_away integer,
    live_score text,
    minute integer,
    match_status text,
    source_status jsonb not null default '{}'::jsonb,
    fetched_at timestamptz not null,
    updated_at timestamptz not null default now()
  );

  alter table public.phase3_live_fast_snapshot enable row level security;
  alter table public.phase3_live_fast_current enable row level security;

  create or replace function public.phase3_claim_fast_refresh()
  returns boolean
  language plpgsql
  security definer
  set search_path=public,pg_catalog
  as $$
  declare claimed boolean;
  begin
    update public.phase3_live_fast_snapshot
       set lease_until = now()+interval '8 seconds',
           updated_at = now()
     where id=1
       and (lease_until is null or lease_until < now())
       and (fetched_at is null or fetched_at < now()-interval '4 seconds');
    get diagnostics claimed = row_count;
    return claimed;
  end;
  $$;

  revoke all on function public.phase3_claim_fast_refresh() from public, anon, authenticated;
