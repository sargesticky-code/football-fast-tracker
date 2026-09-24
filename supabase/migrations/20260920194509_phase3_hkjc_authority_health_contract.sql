create or replace view public.phase3_hkjc_live_authority_health_v as
with src as (
  select
    count(*)::integer as source_rows,
    max(fetched_at) as latest_source_fetched_at
  from public.hkjc_live_odds_current
), auth as (
  select
    count(*)::integer as authority_rows,
    count(*) filter (where eligible)::integer as eligible_rows,
    count(*) filter (where authority_state = 'STALE_AUTHORITY')::integer as stale_rows,
    count(*) filter (where authority_state = 'NOT_SELLING')::integer as not_selling_rows,
    count(*) filter (where authority_state = 'NOT_LIVE')::integer as not_live_rows,
    count(*) filter (where hkjc_event_id is null or btrim(hkjc_event_id) = '' or match_id is null or btrim(match_id) = '')::integer as identity_gap_rows,
    max(authority_fetched_at) as authority_fetched_at
  from public.phase3_hkjc_live_authority_v
)
select
  src.source_rows,
  auth.authority_rows,
  auth.eligible_rows,
  auth.stale_rows,
  auth.not_selling_rows,
  auth.not_live_rows,
  auth.identity_gap_rows,
  coalesce(auth.authority_fetched_at, src.latest_source_fetched_at) as authority_fetched_at,
  case when coalesce(auth.authority_fetched_at, src.latest_source_fetched_at) is null then null
       else extract(epoch from (now() - coalesce(auth.authority_fetched_at, src.latest_source_fetched_at)))::integer end as authority_age_seconds,
  case
    when coalesce(auth.authority_fetched_at, src.latest_source_fetched_at) is null then 'NO_SNAPSHOT'
    when extract(epoch from (now() - coalesce(auth.authority_fetched_at, src.latest_source_fetched_at))) > 300 then 'STALE_AUTHORITY'
    when auth.identity_gap_rows > 0 then 'IDENTITY_GAP'
    when auth.eligible_rows = 0 then 'FRESH_NO_LIVE_ROWS'
    else 'FRESH_ELIGIBLE'
  end::text as health_state,
  (coalesce(auth.authority_fetched_at, src.latest_source_fetched_at) is not null
   and extract(epoch from (now() - coalesce(auth.authority_fetched_at, src.latest_source_fetched_at))) <= 300
   and auth.identity_gap_rows = 0) as authority_usable
from src cross join auth;
