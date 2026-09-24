
revoke execute on function public.ft_refresh_deferred_identity_state() from public;
revoke execute on function public.ft_refresh_deferred_identity_state() from anon;
revoke execute on function public.ft_refresh_deferred_identity_state() from authenticated;
grant execute on function public.ft_refresh_deferred_identity_state() to service_role;
