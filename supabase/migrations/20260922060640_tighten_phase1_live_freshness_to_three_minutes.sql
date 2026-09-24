
do $$
declare
  ddl text;
  patched text;
begin
  select pg_get_functiondef(p.oid)
    into ddl
  from pg_proc p
  join pg_namespace n on n.oid=p.pronamespace
  where n.nspname='public'
    and p.proname='ft_internal_app_phase1_feed'
  limit 1;

  if ddl is null then
    raise exception 'ft_internal_app_phase1_feed not found';
  end if;

  patched := replace(
    ddl,
    'fetched_at >= now()-interval ''10 minutes''',
    'fetched_at >= now()-interval ''3 minutes'''
  );
  patched := replace(
    patched,
    'updated_at_source >= now()-interval ''10 minutes''',
    'updated_at_source >= now()-interval ''3 minutes'''
  );

  if patched = ddl then
    raise exception 'live freshness anchors not found';
  end if;

  execute patched;
end
$$;
