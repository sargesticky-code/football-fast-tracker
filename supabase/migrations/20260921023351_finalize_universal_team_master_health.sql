create or replace function public.ft_record_team_name_master_health()
returns jsonb
language plpgsql
security definer
set search_path=public
as $$
declare
  v_total integer;
  v_verified integer;
  v_candidate integer;
  v_ambiguous integer;
  v_global integer;
begin
  select
    count(*),
    count(*) filter(where status='VERIFIED'),
    count(*) filter(where status='CANDIDATE'),
    count(*) filter(where status='AMBIGUOUS')
  into v_total,v_verified,v_candidate,v_ambiguous
  from public.team_name_master;

  select count(*) into v_global from public.team_name_global_lookup;

  insert into public.source_health(source,metric,value_text,status,notes,observed_at,raw)
  values(
    'TEAM_NAME_MASTER','registry',
    v_verified::text,
    case when v_ambiguous>0 then 'WARN' else 'OK' end,
    'Universal source-team dictionary; runtime lookup before discovery matching.',
    now(),
    jsonb_build_object(
      'total_rows',v_total,
      'verified_rows',v_verified,
      'candidate_rows',v_candidate,
      'ambiguous_rows',v_ambiguous,
      'global_unique_names',v_global
    )
  )
  on conflict(source,metric) do update set
    value_text=excluded.value_text,
    status=excluded.status,
    notes=excluded.notes,
    observed_at=excluded.observed_at,
    raw=excluded.raw;

  return jsonb_build_object(
    'total_rows',v_total,
    'verified_rows',v_verified,
    'candidate_rows',v_candidate,
    'ambiguous_rows',v_ambiguous,
    'global_unique_names',v_global
  );
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
  v_health jsonb;
begin
  v_refresh := public.ft_refresh_team_alias_v2();
  v_promote := public.ft_promote_verified_alias_v2();
  v_master := public.ft_refresh_team_name_master();
  v_seed := public.ft_seed_verified_legacy_names();
  v_health := public.ft_record_team_name_master_health();
  return jsonb_build_object(
    'alias_v2',v_refresh,
    'promotion',v_promote,
    'team_name_master',v_master,
    'legacy_verified_seed',v_seed,
    'final_health',v_health
  );
end
$$;
