
    revoke execute on function public.ft_resolve_team_name(text,text) from public, anon, authenticated;
    grant execute on function public.ft_resolve_team_name(text,text) to service_role;

    alter function public.ft_team_name_key(text)
      set search_path = pg_catalog, public, pg_temp;

    alter function public.phase1_event_context_anchor_guard(text,text,text,text,text,text)
      set search_path = pg_catalog, public, pg_temp;
  
