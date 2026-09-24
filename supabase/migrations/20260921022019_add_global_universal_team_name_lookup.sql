create or replace view public.team_name_global_lookup as
with verified as (
  select *
  from public.team_name_master
  where status='VERIFIED'
),
unique_keys as (
  select source_key
  from verified
  group by source_key
  having count(distinct team_key)=1
),
ranked as (
  select
    v.*,
    row_number() over(
      partition by v.source_key
      order by coalesce(v.confidence,0) desc,
               v.event_count desc,
               v.last_seen_at desc nulls last,
               v.source asc
    ) rn
  from verified v
  join unique_keys u using(source_key)
)
select
  source_name,source_key,team_key,hkjc_name_en,hkjc_name_zh,
  confidence,event_count,last_seen_at
from ranked
where rn=1;

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
  with candidates as (
    select
      l.team_key,l.hkjc_name_en,l.hkjc_name_zh,l.confidence,1 priority
    from public.team_name_lookup l
    where l.source=upper(trim(p_source))
      and l.source_key=public.ft_team_name_key(p_name)

    union all

    select
      g.team_key,g.hkjc_name_en,g.hkjc_name_zh,g.confidence,2
    from public.team_name_global_lookup g
    where g.source_key=public.ft_team_name_key(p_name)
  )
  select c.team_key,c.hkjc_name_en,c.hkjc_name_zh,c.confidence
  from candidates c
  order by priority
  limit 1
$$;
