create or replace function public.ft_seed_verified_legacy_names()
returns jsonb
language plpgsql
security definer
set search_path=public
as $$
declare
  v_seeded integer := 0;
begin
  with manual as (
    select
      upper(trim(ta.source)) source,
      trim(ta.alias) source_name,
      public.ft_team_name_key(ta.alias) source_key,
      coalesce(en.team_key,zh.team_key) team_key,
      greatest(coalesce(ta.confidence,0.99),0.99) confidence,
      ta.first_seen_hkt,
      ta.last_seen_hkt,
      greatest(coalesce(ta.match_count,1),1) event_count
    from public.team_aliases ta
    left join public.team_entities_v2 en
      on en.name_key=public.ft_team_name_key(ta.canonical_hkjc_name)
    left join public.team_entities_v2 zh
      on public.ft_team_name_key(zh.hkjc_name_zh)=public.ft_team_name_key(ta.canonical_hkjc_name)
    where ta.status='MANUAL'
       or ta.alias_source in ('MANUAL_OVERRIDE','BOOTSTRAP_VERIFIED','V2_VERIFIED')
  ),
  safe as (
    select m.*
    from manual m
    where m.source_key is not null
      and m.team_key is not null
      and not exists (
        select 1
        from public.team_name_master x
        where x.source=m.source
          and x.source_key=m.source_key
          and x.status='VERIFIED'
          and x.team_key<>m.team_key
      )
  ),
  ins as (
    insert into public.team_name_master(
      source,source_name,source_key,team_key,hkjc_name_en,hkjc_name_zh,
      status,confidence,event_count,first_seen_at,last_seen_at,evidence_sources,updated_at
    )
    select
      s.source,s.source_name,s.source_key,s.team_key,
      te.hkjc_name_en,te.hkjc_name_zh,
      'VERIFIED',s.confidence,s.event_count,
      coalesce(s.first_seen_hkt,now()),coalesce(s.last_seen_hkt,now()),
      '["LEGACY_VERIFIED_SEED"]'::jsonb,now()
    from safe s
    join public.team_entities_v2 te using(team_key)
    on conflict(source,source_key,team_key) do update set
      source_name=excluded.source_name,
      status='VERIFIED',
      confidence=greatest(public.team_name_master.confidence,excluded.confidence),
      event_count=greatest(public.team_name_master.event_count,excluded.event_count),
      first_seen_at=least(public.team_name_master.first_seen_at,excluded.first_seen_at),
      last_seen_at=greatest(public.team_name_master.last_seen_at,excluded.last_seen_at),
      evidence_sources=(
        select jsonb_agg(distinct v)
        from jsonb_array_elements(
          coalesce(public.team_name_master.evidence_sources,'[]'::jsonb)
          || excluded.evidence_sources
        ) v
      ),
      updated_at=now()
    returning 1
  )
  select count(*) into v_seeded from ins;

  return jsonb_build_object('verified_legacy_rows_seeded_or_refreshed',v_seeded);
end
$$;

create or replace function public.ft_alias_maintenance_v2()
returns jsonb
language plpgsql
security definer
set search_path=public
as $$
declare
  v_refresh jsonb;
  v_promote jsonb;
  v_master jsonb;
  v_seed jsonb;
begin
  v_refresh := public.ft_refresh_team_alias_v2();
  v_promote := public.ft_promote_verified_alias_v2();
  v_master := public.ft_refresh_team_name_master();
  v_seed := public.ft_seed_verified_legacy_names();
  return jsonb_build_object(
    'alias_v2',v_refresh,
    'promotion',v_promote,
    'team_name_master',v_master,
    'legacy_verified_seed',v_seed
  );
end
$$;
