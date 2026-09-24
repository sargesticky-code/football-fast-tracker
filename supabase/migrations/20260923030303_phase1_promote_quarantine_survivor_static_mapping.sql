create or replace function public.ft_apply_team_name_quarantine()
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  v_deleted integer := 0;
  v_promoted integer := 0;
begin
  delete from public.team_name_master m
  using public.team_name_event_context_quarantine q
  where upper(m.source)=upper(q.source)
    and m.source_key=public.ft_team_name_key(q.source_name)
    and m.team_key=q.team_key;
  get diagnostics v_deleted = row_count;

  with survivors as (
    select m.source,m.source_key,min(m.team_key) team_key
    from public.team_name_master m
    where m.status='AMBIGUOUS'
      and exists (
        select 1 from public.team_name_event_context_quarantine q
        where upper(q.source)=upper(m.source)
          and public.ft_team_name_key(q.source_name)=m.source_key
          and q.team_key<>m.team_key
      )
    group by m.source,m.source_key
    having count(distinct m.team_key)=1
  )
  update public.team_name_master m
  set status='VERIFIED',
      confidence=greatest(coalesce(m.confidence,0),0.99),
      evidence_sources=coalesce(m.evidence_sources,'[]'::jsonb) || jsonb_build_array('QUARANTINE_SURVIVOR_VERIFIED'),
      updated_at=now()
  from survivors s
  where m.source=s.source and m.source_key=s.source_key and m.team_key=s.team_key;
  get diagnostics v_promoted = row_count;

  return jsonb_build_object('quarantined_master_rows_deleted',v_deleted,'quarantine_survivors_promoted',v_promoted);
end
$$;
