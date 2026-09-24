
create or replace function private.ft_phase15_learn_exact_shadow()
returns integer
language plpgsql
security definer
set search_path = 'public','private'
as $$
declare
  v_before bigint;
  v_after bigint;
begin
  select count(*) into v_before from public.team_alias_evidence_v2 where source='FOTMOB';

  insert into public.team_alias_evidence_v2
    (source, alias, alias_key, team_key, hkjc_event_id, team_side, tournament,
     kickoff_hkt, evidence_type, confidence, observed_at, raw)
  select
    'FOTMOB',
    x.alias,
    public.ft_team_name_key(x.alias),
    x.team_key,
    s.matched_hkjc_event_id,
    x.side,
    u.tournament,
    u.kickoff_hkt,
    'PHASE15_EXACT_PAIR',
    0.99,
    s.fetched_at,
    jsonb_build_object('source_event_id',s.external_event_id,'identity_status',s.identity_status)
  from public.phase15_source_shadow_current s
  join public.hkjc_upcoming_current u
    on u.hkjc_event_id=s.matched_hkjc_event_id
  cross join lateral (
    select s.home_name alias, 'H'::text side, mh.team_key
    from public.team_name_master mh
    where mh.source='HKJC_EN'
      and mh.status='VERIFIED'
      and mh.source_key=public.ft_team_name_key(u.home_en)
    union all
    select s.away_name alias, 'A'::text side, ma.team_key
    from public.team_name_master ma
    where ma.source='HKJC_EN'
      and ma.status='VERIFIED'
      and ma.source_key=public.ft_team_name_key(u.away_en)
  ) x
  where s.source_key='FOTMOB'
    and s.identity_status='EXACT_PAIR'
    and s.match_confidence >= 0.99
    and public.ft_team_name_key(s.home_name)=public.ft_team_name_key(u.home_en)
    and public.ft_team_name_key(s.away_name)=public.ft_team_name_key(u.away_en)
  on conflict do nothing;

  select count(*) into v_after from public.team_alias_evidence_v2 where source='FOTMOB';
  return (v_after-v_before)::integer;
end
$$;

revoke all on function private.ft_phase15_learn_exact_shadow() from public;
grant execute on function private.ft_phase15_learn_exact_shadow() to postgres, service_role;
