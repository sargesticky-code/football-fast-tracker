create or replace view phase1_app_core_unresolved_v as
select *
from phase1_static_master_unresolved_action_v
where source in ('HKJC','FOREBET','FOOTBALL_DATA','OPTA','FORM','APWIN','FRB','ACC','BCL','FST','PRE','STA');

create or replace view phase1_app_core_identity_coverage_v as
select
  m.source,
  count(*) filter (where m.status='VERIFIED') as verified_master_rows,
  count(*) filter (where m.status='CANDIDATE') as candidate_master_rows,
  count(*) filter (where m.status='AMBIGUOUS') as ambiguous_master_rows,
  coalesce(t.verified_context_rows,0) as verified_context_rows,
  coalesce(t.unresolved_context_rows,0) as unresolved_context_rows
from team_name_master m
left join phase1_identity_direct_context_telemetry_v t on t.source=m.source
where m.source in ('HKJC','FOREBET','FOOTBALL_DATA','OPTA','FORM','APWIN','FRB','ACC','BCL','FST','PRE','STA')
group by m.source,t.verified_context_rows,t.unresolved_context_rows;
