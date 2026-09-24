
    alter table public.team_name_event_context_quarantine enable row level security;
    alter table public.phase1_identity_safety_block enable row level security;

    revoke all privileges on table public.team_name_event_context_quarantine from anon, authenticated;
    revoke all privileges on table public.phase1_identity_safety_block from anon, authenticated;

    revoke execute on function public.ft_apply_team_name_quarantine() from public, anon, authenticated;
    grant execute on function public.ft_apply_team_name_quarantine() to service_role;

    comment on table public.team_name_event_context_quarantine is
      'Internal Phase 1 identity quarantine. Backend-only; protected by RLS and no anon/authenticated grants.';
    comment on table public.phase1_identity_safety_block is
      'Internal Phase 1 identity safety block. Backend-only; protected by RLS and no anon/authenticated grants.';
  
