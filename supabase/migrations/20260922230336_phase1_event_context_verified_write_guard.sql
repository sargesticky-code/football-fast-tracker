create or replace function public.phase1_guard_verified_event_context_write()
returns trigger
language plpgsql
set search_path=public
as $$
declare
  v_anchor text;
  v_anchor_team_key text;
begin
  if new.status is distinct from 'VERIFIED' then
    return new;
  end if;

  select case upper(new.side)
           when 'HOME' then h.home_en
           when 'AWAY' then h.away_en
         end
    into v_anchor
  from public.hkjc_upcoming_current h
  where h.hkjc_event_id = new.hkjc_event_id
  limit 1;

  -- Historical anchors may no longer be on the current HKJC surface. Those remain
  -- eligible for separate evidence workflows; current anchors must fail closed.
  if v_anchor is null then
    return new;
  end if;

  select r.team_key into v_anchor_team_key
  from public.ft_resolve_team_name_context('HKJC', v_anchor, new.source_competition, null, null) r
  limit 1;

  if v_anchor_team_key is null then
    raise exception 'PHASE1_EVENT_CONTEXT_GUARD: HKJC anchor unresolved for event %, side %, anchor %', new.hkjc_event_id, new.side, v_anchor;
  end if;

  if v_anchor_team_key is distinct from new.team_key then
    raise exception 'PHASE1_EVENT_CONTEXT_GUARD: team_key % contradicts HKJC anchor % (%) for event %, side %', new.team_key, v_anchor_team_key, v_anchor, new.hkjc_event_id, new.side;
  end if;

  return new;
end;
$$;

drop trigger if exists trg_phase1_verified_event_context_guard on public.team_name_event_context_master;
create trigger trg_phase1_verified_event_context_guard
before insert or update of status,team_key,hkjc_event_id,side,source_competition
on public.team_name_event_context_master
for each row execute function public.phase1_guard_verified_event_context_write();

comment on function public.phase1_guard_verified_event_context_write() is
'Phase 1 fail-closed write guard: VERIFIED event-context evidence for current HKJC anchors must resolve to the canonical HKJC team_key before persistence.';
