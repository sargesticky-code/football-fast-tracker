create or replace view public.phase1_current_anchor_source_coverage_v as
with anchors as (
  select h.hkjc_event_id,h.kickoff_hkt,h.tournament,h.home_en,h.away_en
  from public.hkjc_upcoming_current h
), provider as (
  select 'FOREBET'::text source, f.hkjc_event_id, f.forebet_home_team source_home, f.forebet_away_team source_away, f.forebet_league_short source_competition from public.forebet_predictions f
  union all select 'FORM', f.hkjc_event_id, f.home, f.away, null::text from public.form_predictions f
  union all select 'INTERNAL_MODEL', m.hkjc_event_id, coalesce(m.model_home_name,m.home), coalesce(m.model_away_name,m.away), m.model_league from public.model_predictions m
), expanded as (
 select a.*,p.source,p.source_home,p.source_away,p.source_competition
 from anchors a cross join (values ('FOREBET'::text),('FORM'),('INTERNAL_MODEL')) s(source)
 left join provider p on p.source=s.source and p.hkjc_event_id=a.hkjc_event_id
), classified as (
 select e.*,
 case when e.source_home is null or e.source_away is null then 'FETCHED_SURFACE_ABSENT_NOT_PROVEN_SOURCE_ABSENT'
      when exists(select 1 from public.team_name_master tm where tm.source=e.source and tm.status='VERIFIED' and tm.source_key=public.ft_team_name_key(e.source_home))
       and exists(select 1 from public.team_name_master tm where tm.source=e.source and tm.status='VERIFIED' and tm.source_key=public.ft_team_name_key(e.source_away)) then 'DIRECT_MASTER'
      else 'NAME_LEAGUE_MATCH_GAP' end identity_class
 from expanded e
)
select * from classified;
comment on view public.phase1_current_anchor_source_coverage_v is 'Phase 1 current HKJC anchor coverage telemetry. Distinguishes direct static-master identity, provider-present identity gaps, and fetched-surface absence without claiming true provider absence.';
