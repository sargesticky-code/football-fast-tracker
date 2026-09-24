
create index if not exists live_stats_history_recent_identity_idx
on public.live_stats_history (captured_at_hkt desc, hkjc_event_id, source)
where source_match_id is not null and source_match_id <> '';

alter table public.phase3_live_identity_map enable row level security;
alter table public.phase3_live_identity_candidate enable row level security;

revoke all on table public.phase3_live_identity_map from anon, authenticated;
revoke all on table public.phase3_live_identity_candidate from anon, authenticated;

grant select,insert,update,delete on table public.phase3_live_identity_map to service_role;
grant select,insert,update,delete on table public.phase3_live_identity_candidate to service_role;
