create or replace function public.ft_resolve_team_name_context(
  p_source text,
  p_name text,
  p_source_competition text default null,
  p_hkjc_event_id text default null,
  p_side text default null
)
returns table(team_key text, hkjc_name_en text, hkjc_name_zh text, confidence numeric, resolution_path text)
language sql
stable
security invoker
set search_path = public
as $function$
with p as (
  select upper(trim(p_source)) source,
         public.ft_team_name_key(p_name) source_key,
         nullif(trim(p_source_competition),'') source_competition,
         nullif(trim(p_hkjc_event_id),'') hkjc_event_id,
         upper(nullif(trim(p_side),'')) side
),
event_hit as (
  select e.team_key,e.hkjc_name_en,te.hkjc_name_zh,e.confidence,1 priority,'EVENT_CONTEXT'::text resolution_path
  from public.team_name_event_context_master e
  left join public.team_entities_v2 te on te.team_key=e.team_key
  cross join p
  where e.status='VERIFIED'
    and upper(e.source)=p.source
    and public.ft_team_name_key(e.source_name)=p.source_key
    and p.hkjc_event_id is not null and e.hkjc_event_id=p.hkjc_event_id
    and (p.source_competition is null or e.source_competition=p.source_competition)
    and (p.side is null or upper(e.side)=p.side)
),
context_hit as (
  select c.team_key,c.hkjc_name_en,c.hkjc_name_zh,c.confidence,2 priority,'LEAGUE_CONTEXT'::text resolution_path
  from public.team_name_context_lookup c cross join p
  where c.source=p.source and c.source_key=p.source_key
    and p.source_competition is not null and c.source_competition=p.source_competition
    and not exists (select 1 from event_hit)
    and (select count(distinct c2.team_key) from public.team_name_context_lookup c2 where c2.source=p.source and c2.source_key=p.source_key and c2.source_competition=p.source_competition)=1
),
source_hit as (
  select l.team_key,l.hkjc_name_en,l.hkjc_name_zh,l.confidence,3 priority,'SOURCE_MASTER'::text resolution_path
  from public.team_name_lookup l cross join p
  where l.source=p.source and l.source_key=p.source_key
    and not exists (select 1 from event_hit)
    and not exists (select 1 from context_hit)
),
global_hit as (
  select g.team_key,g.hkjc_name_en,g.hkjc_name_zh,g.confidence,4 priority,'GLOBAL_UNIQUE'::text resolution_path
  from public.team_name_global_lookup g cross join p
  where g.source_key=p.source_key
    and not exists (select 1 from event_hit)
    and not exists (select 1 from context_hit)
    and not exists (select 1 from source_hit)
    and not exists (select 1 from public.team_name_master m where m.source=p.source and m.source_key=p.source_key and m.status in ('CANDIDATE','AMBIGUOUS'))
)
select x.team_key,x.hkjc_name_en,x.hkjc_name_zh,x.confidence,x.resolution_path
from (select * from event_hit union all select * from context_hit union all select * from source_hit union all select * from global_hit) x
order by x.priority
limit 1;
$function$;
revoke all on function public.ft_resolve_team_name_context(text,text,text,text,text) from public;
grant execute on function public.ft_resolve_team_name_context(text,text,text,text,text) to authenticated, service_role;
