
    revoke execute on function public.ft_promote_static_master_consensus() from public, anon, authenticated;
    grant execute on function public.ft_promote_static_master_consensus() to service_role;

    revoke execute on function public.ft_refresh_brazilianfootball_team_names() from public, anon, authenticated;
    grant execute on function public.ft_refresh_brazilianfootball_team_names() to service_role;

    revoke execute on function public.ft_refresh_womens_intl_team_names() from public, anon, authenticated;
    grant execute on function public.ft_refresh_womens_intl_team_names() to service_role;

    revoke execute on function public.ft_seed_verified_legacy_names() from public, anon, authenticated;
    grant execute on function public.ft_seed_verified_legacy_names() to service_role;
  
