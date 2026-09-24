create or replace function phase1_event_context_anchor_guard(p_source text,p_source_name text,p_source_competition text,p_hkjc_event_id text,p_side text,p_team_key text)
returns table(ok boolean, reason text, anchor_name text, resolved_team_key text)
language sql stable as $$
with a as (
 select case when upper(p_side)='HOME' then home_en when upper(p_side)='AWAY' then away_en end as anchor_name
 from hkjc_upcoming_current where hkjc_event_id=p_hkjc_event_id limit 1
), r as (
 select x.team_key from a cross join lateral ft_resolve_team_name_context('HKJC',a.anchor_name,p_source_competition,null) x limit 1
)
select case when a.anchor_name is null then false when r.team_key is null then false when r.team_key=p_team_key then true else false end,
 case when a.anchor_name is null then 'HKJC_EVENT_OR_SIDE_NOT_FOUND' when r.team_key is null then 'HKJC_ANCHOR_UNRESOLVED' when r.team_key<>p_team_key then 'TEAM_KEY_CONTRADICTS_HKJC_ANCHOR' else 'ANCHOR_CONFIRMED' end,
 a.anchor_name,r.team_key from a left join r on true
$$;

create or replace view phase1_event_context_guard_health_v as
select e.source,e.source_name,e.source_competition,e.hkjc_event_id,e.side,e.team_key,g.ok,g.reason,g.anchor_name,g.resolved_team_key
from team_name_event_context_master e
cross join lateral phase1_event_context_anchor_guard(e.source,e.source_name,e.source_competition,e.hkjc_event_id,e.side,e.team_key) g;
