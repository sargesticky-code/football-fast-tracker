create or replace function public.ft_refresh_deferred_identity_state()
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $function$
declare
  v_waiting_before integer;
  v_reactivated integer;
  v_waiting_after integer;
begin
  select count(*) into v_waiting_before
  from public.phase1_identity_deferred_queue
  where reactivated_at is null;

  update public.phase1_identity_deferred_queue d
  set last_checked_at = now()
  where d.reactivated_at is null;

  with ready as (
    select source, source_name, source_competition, newly_available_team_key
    from public.phase1_identity_deferred_reactivation_v
  )
  update public.phase1_identity_deferred_queue d
  set reactivated_at = now(),
      last_checked_at = now(),
      candidate_team_key = coalesce(d.candidate_team_key, r.newly_available_team_key)
  from ready r
  where d.source = r.source
    and d.source_name = r.source_name
    and d.source_competition is not distinct from r.source_competition
    and d.reactivated_at is null;

  get diagnostics v_reactivated = row_count;

  select count(*) into v_waiting_after
  from public.phase1_identity_deferred_queue
  where reactivated_at is null;

  return jsonb_build_object(
    'waiting_before', v_waiting_before,
    'reactivated', v_reactivated,
    'waiting_after', v_waiting_after
  );
end
$function$;

create or replace view public.team_alias_actionable_queue_v2 as
select q.*
from public.team_alias_candidate_queue_v2 q
where not exists (
  select 1
  from public.phase1_identity_deferred_queue d
  where d.reactivated_at is null
    and upper(d.source) = upper(q.source)
    and regexp_replace(lower(d.source_name), '[^a-z0-9]+', '', 'g') = q.alias_key
);

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
  v_quarantine jsonb;
  v_registry_harden jsonb;
  v_registry_merge jsonb;
  v_static_consensus jsonb;
  v_health jsonb;
  v_one_for_all jsonb;
  v_women jsonb;
  v_brazil jsonb;
  v_context jsonb;
  v_forebet_queue jsonb;
  v_deferred jsonb;
begin
  v_deferred := public.ft_refresh_deferred_identity_state();
  v_refresh := public.ft_refresh_team_alias_v2();
  v_promote := public.ft_promote_verified_alias_v2();
  v_master := public.ft_refresh_team_name_master();
  v_quarantine := public.ft_apply_team_name_quarantine();
  v_registry_harden := public.ft_promote_registry_from_verified_master();
  v_registry_merge := public.ft_merge_alias_registry_into_team_name_master();
  v_quarantine := v_quarantine || public.ft_apply_team_name_quarantine();
  v_context := public.ft_refresh_static_identity_context();
  v_static_consensus := public.ft_promote_static_master_consensus();
  v_quarantine := v_quarantine || public.ft_apply_team_name_quarantine();
  v_health := public.ft_record_team_name_master_health();
  v_one_for_all := public.ft_record_one_for_all_alias_health();
  v_women := public.ft_refresh_womens_intl_team_names();
  v_brazil := public.ft_refresh_brazilianfootball_team_names();
  v_forebet_queue := public.ft_record_forebet_identity_queue_health();

  update public.source_health
  set notes='Alias evidence registry v2 plus persistent static team/competition context. Phase 1 production identity is master-first; deferred unresolved identities are excluded from the actionable queue until canonical evidence reactivates them; quarantined cross-event mappings are re-applied after every master/registry promotion stage.',
      observed_at=now()
  where source='TEAM_ALIAS_V2' and metric='registry';

  return jsonb_build_object(
    'deferred_identity_state',v_deferred,
    'alias_v2',v_refresh,
    'promotion',v_promote,
    'team_name_master',v_master,
    'quarantine_enforcement',v_quarantine,
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
