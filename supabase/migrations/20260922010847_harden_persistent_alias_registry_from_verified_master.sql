
create or replace function public.ft_promote_registry_from_verified_master()
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_before integer := 0;
  v_promoted integer := 0;
  v_after integer := 0;
begin
  select count(*)::int into v_before
  from public.team_alias_registry_v2
  where status='CANDIDATE';

  with safe as (
    select
      r.source,r.alias_key,r.team_key,
      greatest(coalesce(r.confidence,0),coalesce(m.confidence,0)) as confidence
    from public.team_alias_registry_v2 r
    join public.team_name_master m
      on m.source=r.source
     and m.source_key=r.alias_key
     and m.team_key=r.team_key
    where r.status='CANDIDATE'
      and m.status='VERIFIED'
      and not exists (
        select 1
        from public.team_alias_registry_v2 x
        where x.source=r.source
          and x.alias_key=r.alias_key
          and x.team_key<>r.team_key
      )
      and not exists (
        select 1
        from public.team_name_master x
        where x.source=r.source
          and x.source_key=r.alias_key
          and x.team_key<>r.team_key
      )
  )
  update public.team_alias_registry_v2 r
  set status='VERIFIED',
      confidence=s.confidence,
      verification_method=case
        when coalesce(r.verification_method,'') like '%MANUAL%'
          then r.verification_method
        else 'VERIFIED_TEAM_NAME_MASTER'
      end,
      updated_at=now()
  from safe s
  where r.source=s.source
    and r.alias_key=s.alias_key
    and r.team_key=s.team_key;

  get diagnostics v_promoted = row_count;

  select count(*)::int into v_after
  from public.team_alias_registry_v2
  where status='CANDIDATE';

  insert into public.source_health(
    source,metric,value_text,status,notes,observed_at,raw
  )
  values(
    'TEAM_ALIAS_REGISTRY_HARDEN','phase1',
    v_after::text,
    case when v_after=0 then 'PASS' else 'WARN' end,
    'Promotes persistent alias candidates only when the rebuilt universal team_name_master independently verifies the exact same source alias/team and no collision exists.',
    now(),
    jsonb_build_object(
      'candidate_before',v_before,
      'promoted',v_promoted,
      'candidate_after',v_after
    )
  )
  on conflict(source,metric) do update
  set value_text=excluded.value_text,
      status=excluded.status,
      notes=excluded.notes,
      observed_at=excluded.observed_at,
      raw=excluded.raw;

  return jsonb_build_object(
    'candidate_before',v_before,
    'promoted',v_promoted,
    'candidate_after',v_after
  );
end
$$;

revoke all on function public.ft_promote_registry_from_verified_master() from public;
revoke all on function public.ft_promote_registry_from_verified_master() from anon;
revoke all on function public.ft_promote_registry_from_verified_master() from authenticated;
grant execute on function public.ft_promote_registry_from_verified_master() to service_role;

create or replace function public.ft_alias_maintenance_v2()
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_refresh jsonb;
  v_promote jsonb;
  v_master jsonb;
  v_registry_harden jsonb;
  v_registry_merge jsonb;
  v_health jsonb;
  v_one_for_all jsonb;
  v_women jsonb;
  v_brazil jsonb;
  v_context jsonb;
  v_forebet_queue jsonb;
begin
  v_refresh := public.ft_refresh_team_alias_v2();
  v_promote := public.ft_promote_verified_alias_v2();
  v_master := public.ft_refresh_team_name_master();
  v_registry_harden := public.ft_promote_registry_from_verified_master();
  v_registry_merge := public.ft_merge_alias_registry_into_team_name_master();
  v_context := public.ft_refresh_static_identity_context();
  v_health := public.ft_record_team_name_master_health();
  v_one_for_all := public.ft_record_one_for_all_alias_health();
  v_women := public.ft_refresh_womens_intl_team_names();
  v_brazil := public.ft_refresh_brazilianfootball_team_names();
  v_forebet_queue := public.ft_record_forebet_identity_queue_health();

  update public.source_health
  set notes='Alias evidence registry v2 plus persistent static team/competition context. Phase 1 production identity is master-first; verified source/league mappings are learned once and reused.',
      observed_at=now()
  where source='TEAM_ALIAS_V2' and metric='registry';

  return jsonb_build_object(
    'alias_v2',v_refresh,
    'promotion',v_promote,
    'team_name_master',v_master,
    'registry_hardening',v_registry_harden,
    'registry_merge',v_registry_merge,
    'static_identity_context',v_context,
    'team_name_master_health',v_health,
    'one_for_all_health',v_one_for_all,
    'forebet_identity_queue',v_forebet_queue,
    'womens_intl_names',v_women,
    'brazilianfootball_names',v_brazil
  );
end
$$;

select public.ft_promote_registry_from_verified_master();
select public.ft_merge_alias_registry_into_team_name_master();
select public.ft_record_team_name_master_health();
