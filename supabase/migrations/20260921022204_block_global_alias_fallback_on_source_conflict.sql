create or replace function public.ft_resolve_team_name(p_source text,p_name text)
returns table(
  team_key text,
  hkjc_name_en text,
  hkjc_name_zh text,
  confidence numeric
)
language sql
stable
security definer
set search_path=public
as $$
  with params as (
    select upper(trim(p_source)) source, public.ft_team_name_key(p_name) source_key
  ),
  candidates as (
    select
      l.team_key,l.hkjc_name_en,l.hkjc_name_zh,l.confidence,1 priority
    from public.team_name_lookup l, params p
    where l.source=p.source
      and l.source_key=p.source_key

    union all

    select
      g.team_key,g.hkjc_name_en,g.hkjc_name_zh,g.confidence,2
    from public.team_name_global_lookup g, params p
    where g.source_key=p.source_key
      and not exists (
        select 1
        from public.team_name_master m
        where m.source=p.source
          and m.source_key=p.source_key
      )
  )
  select c.team_key,c.hkjc_name_en,c.hkjc_name_zh,c.confidence
  from candidates c
  order by priority
  limit 1
$$;
