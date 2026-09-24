create or replace view public.phase1_generic_alias_context_resolution_v as
select
  m.source,
  m.source_name,
  m.team_key,
  m.status as global_status,
  count(c.*) filter (where c.status='VERIFIED') as verified_context_hits,
  array_remove(array_agg(distinct c.source_competition) filter (where c.status='VERIFIED'), null) as verified_competitions,
  case
    when count(c.*) filter (where c.status='VERIFIED') > 0 then 'DIRECT_CONTEXT_MASTER'
    when exists (
      select 1 from public.phase1_identity_deferred_queue d
      where d.source=m.source
        and lower(trim(d.source_name))=lower(trim(m.source_name))
        and d.reactivated_at is null
    ) then 'DEFERRED_BLOCKED'
    else 'DISCOVERY_REQUIRED'
  end as runtime_path
from public.team_name_master m
left join public.team_name_context_master c
  on c.source=m.source and c.source_name=m.source_name and c.team_key=m.team_key
where m.status in ('CANDIDATE','AMBIGUOUS')
group by m.source,m.source_name,m.team_key,m.status;
