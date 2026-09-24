update public.team_name_master
set status='VERIFIED', confidence=greatest(coalesce(confidence,0),0.99), updated_at=now(),
    evidence_sources=coalesce(evidence_sources,'[]'::jsonb) || '["QUARANTINE_CLEANUP_CONFIRMED"]'::jsonb
where source='FOOTBALL_DATA' and source_name='Dundee' and team_key='HKJC:dundee' and status<>'VERIFIED';

update public.team_name_master
set status='VERIFIED', confidence=greatest(coalesce(confidence,0),0.99), updated_at=now(),
    evidence_sources=coalesce(evidence_sources,'[]'::jsonb) || '["QUARANTINE_CLEANUP_CONFIRMED"]'::jsonb
where source='FOOTBALL_DATA' and source_name='Man City' and team_key='HKJC:manchestercity' and status<>'VERIFIED';

delete from public.team_name_master t
where t.source='FOOTBALL_DATA'
  and ((t.source_name='Dundee' and t.team_key='HKJC:dundeeutd')
    or (t.source_name='Man City' and t.team_key='HKJC:manchesterutd'))
  and t.status='AMBIGUOUS'
  and exists (
    select 1 from public.team_name_event_context_quarantine q
    where q.source=t.source and q.source_name=t.source_name and q.team_key=t.team_key
      and q.quarantine_reason ilike '%cross-event alias leakage%'
  );
