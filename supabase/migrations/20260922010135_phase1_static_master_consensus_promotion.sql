create or replace function public.ft_promote_static_master_consensus()
returns jsonb
language plpgsql
security definer
set search_path to 'pg_catalog','public','pg_temp'
as $function$
declare
  v_promoted integer := 0;
begin
  with candidates as (
    select c.source,c.source_key,c.team_key,
      count(distinct v.source) filter (where v.status='VERIFIED' and v.source<>c.source) as verified_source_support,
      count(distinct x.team_key) filter (where x.status in ('VERIFIED','AMBIGUOUS')) as source_key_targets
    from public.team_name_master c
    left join public.team_name_master v on v.team_key=c.team_key
    left join public.team_name_master x on x.source=c.source and x.source_key=c.source_key
    where c.status='CANDIDATE'
    group by c.source,c.source_key,c.team_key
  ), safe as (
    select source,source_key,team_key
    from candidates
    where verified_source_support>=5 and source_key_targets<=1
  ), upd as (
    update public.team_name_master t
    set status='VERIFIED',
        confidence=greatest(coalesce(t.confidence,0),0.95),
        evidence_sources=(select coalesce(jsonb_agg(distinct e),'[]'::jsonb) from jsonb_array_elements(coalesce(t.evidence_sources,'[]'::jsonb)||'["CROSS_SOURCE_STATIC_CONSENSUS"]'::jsonb) e),
        updated_at=now()
    from safe s
    where t.source=s.source and t.source_key=s.source_key and t.team_key=s.team_key and t.status='CANDIDATE'
    returning 1
  ) select count(*) into v_promoted from upd;
  return jsonb_build_object('promoted',v_promoted);
end
$function$;

create or replace function public.ft_alias_maintenance_v2()
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $function$
declare
  v_refresh jsonb; v_promote jsonb; v_master jsonb; v_registry_merge jsonb; v_static_promote jsonb;
  v_health jsonb; v_one_for_all jsonb; v_women jsonb; v_brazil jsonb; v_context jsonb;
begin
  v_refresh := public.ft_refresh_team_alias_v2();
  v_promote := public.ft_promote_verified_alias_v2();
  v_master := public.ft_refresh_team_name_master();
  v_registry_merge := public.ft_merge_alias_registry_into_team_name_master();
  v_static_promote := public.ft_promote_static_master_consensus();
  v_context := public.ft_refresh_static_identity_context();
  v_health := public.ft_record_team_name_master_health();
  v_one_for_all := public.ft_record_one_for_all_alias_health();
  v_women := public.ft_refresh_womens_intl_team_names();
  v_brazil := public.ft_refresh_brazilianfootball_team_names();
  update public.source_health set notes='Alias evidence registry v2 plus persistent static team/competition context. Phase 1 production identity is master-first; verified source/league mappings are learned once and reused.', observed_at=now() where source='TEAM_ALIAS_V2' and metric='registry';
  return jsonb_build_object('alias_v2',v_refresh,'promotion',v_promote,'team_name_master',v_master,'registry_merge',v_registry_merge,'static_consensus_promotion',v_static_promote,'static_identity_context',v_context,'team_name_master_health',v_health,'one_for_all_health',v_one_for_all,'womens_intl_names',v_women,'brazilianfootball_names',v_brazil);
end
$function$;
