
    create index if not exists team_alias_gap_queue_v2_team_key_idx
      on public.team_alias_gap_queue_v2(team_key);

    create index if not exists team_alias_registry_v2_team_key_idx
      on public.team_alias_registry_v2(team_key);

    create index if not exists team_name_context_master_team_key_idx
      on public.team_name_context_master(team_key);

    create index if not exists team_name_master_team_key_idx
      on public.team_name_master(team_key);
  
