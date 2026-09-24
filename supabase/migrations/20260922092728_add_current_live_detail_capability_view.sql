
create or replace view public.live_detail_state_current_v
with (security_invoker=true)
as
select distinct on (h.hkjc_event_id)
  h.hkjc_event_id,
  h.captured_at_hkt,
  h.source,
  h.source_match_id,
  h.match_confidence,
  h.match_minute,
  h.match_status,
  h.detail_status as raw_detail_status,
  case when jsonb_typeof(h.team_stats)='array' then jsonb_array_length(h.team_stats) else 0 end as team_stats_count,
  case when jsonb_typeof(h.events)='array' then jsonb_array_length(h.events) else 0 end as events_count,
  case when jsonb_typeof(h.momentum)='array' then jsonb_array_length(h.momentum) else 0 end as momentum_count,
  case
    when h.detail_status='CAPTURED'
     and (case when jsonb_typeof(h.team_stats)='array' then jsonb_array_length(h.team_stats) else 0 end)=0
     and (case when jsonb_typeof(h.events)='array' then jsonb_array_length(h.events) else 0 end)=0
     and (case when jsonb_typeof(h.momentum)='array' then jsonb_array_length(h.momentum) else 0 end)=0
      then 'CAPTURED_NO_METRICS'
    else coalesce(h.detail_status,'UNKNOWN')
  end as effective_detail_status
from public.live_stats_history h
order by h.hkjc_event_id,h.captured_at_hkt desc;

revoke all on public.live_detail_state_current_v from anon,authenticated;
grant select on public.live_detail_state_current_v to service_role;
