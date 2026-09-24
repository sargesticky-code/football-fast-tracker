create or replace function public.ft_alias_maintenance_v2()
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $function$
declare
  v_refresh jsonb;
  v_promote jsonb;
  v_master jsonb;
  v_registry_harden jsonb;
  v_registry_merge jsonb;
  v_static_consensus jsonb;
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
  v_static_consensus := public.ft_promote_static_master_consensus();
  v_health := public.ft_record_team_name_master_health();
  v_one_for_all := public.ft_record_one_for_all_alias_health();
  v_women := public.ft_refresh_womens_intl_team_names();
  v_brazil := public.ft_refresh_brazilianfootball_team_names();
  v_forebet_queue := public.ft_record_forebet_identity_queue_health();

  update public.source_health
  set notes='Alias evidence registry v2 plus persistent static team/competition context. Phase 1 production identity is master-first; verified source/league mappings are learned once and reused. Static consensus promotion runs after registry merge/context refresh.',
      observed_at=now()
  where source='TEAM_ALIAS_V2' and metric='registry';

  return jsonb_build_object(
    'alias_v2',v_refresh,
    'promotion',v_promote,
    'team_name_master',v_master,
    'registry_hardening',v_registry_harden,
    'registry_merge',v_registry_merge,
    'static_identity_context',v_context,
    'static_consensus',v_static_consensus,
    'team_name_master_health',v_health,
    'one_for_all_health',v_one_for_all,
    'forebet_identity_queue',v_forebet_queue,
    'womens_intl_names',v_women,
    'brazilianfootball_names',v_brazil
  );
end
$function$;
