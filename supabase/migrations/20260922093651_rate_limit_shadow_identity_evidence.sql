
create or replace function public.ft_record_phase3_shadow_identity(
  p_hkjc_event_id text,
  p_source text,
  p_source_match_id text,
  p_confidence numeric,
  p_evidence jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path=pg_catalog,public
as $$
declare
  v_row public.phase3_live_identity_candidate%rowtype;
begin
  if p_hkjc_event_id is null or p_hkjc_event_id=''
     or p_source is null or p_source=''
     or p_source_match_id is null or p_source_match_id=''
     or p_confidence is null or p_confidence < 0.85 then
    return jsonb_build_object('ok',false,'reason','insufficient_identity');
  end if;

  insert into public.phase3_live_identity_candidate(
    hkjc_event_id,source,source_match_id,candidate_confidence,evidence_count,
    candidate_state,evidence,first_seen_at,last_seen_at
  )
  values(
    p_hkjc_event_id,p_source,p_source_match_id,p_confidence,1,'CANDIDATE',
    coalesce(p_evidence,'{}'::jsonb)||jsonb_build_object('method','supabase_native_prewarm'),
    now(),now()
  )
  on conflict(hkjc_event_id,source,source_match_id) do update set
    candidate_confidence=case
      when public.phase3_live_identity_candidate.last_seen_at <= now()-interval '60 seconds'
      then least(public.phase3_live_identity_candidate.candidate_confidence,excluded.candidate_confidence)
      else public.phase3_live_identity_candidate.candidate_confidence
    end,
    evidence_count=case
      when public.phase3_live_identity_candidate.last_seen_at <= now()-interval '60 seconds'
      then public.phase3_live_identity_candidate.evidence_count+1
      else public.phase3_live_identity_candidate.evidence_count
    end,
    candidate_state=case
      when public.phase3_live_identity_candidate.candidate_state='REJECTED' then 'REJECTED'
      when public.phase3_live_identity_candidate.last_seen_at <= now()-interval '60 seconds'
       and least(public.phase3_live_identity_candidate.candidate_confidence,excluded.candidate_confidence)>=0.95
       and public.phase3_live_identity_candidate.evidence_count+1>=3 then 'PROMOTABLE'
      else public.phase3_live_identity_candidate.candidate_state
    end,
    evidence=case
      when public.phase3_live_identity_candidate.last_seen_at <= now()-interval '60 seconds'
      then public.phase3_live_identity_candidate.evidence||excluded.evidence
      else public.phase3_live_identity_candidate.evidence
    end,
    last_seen_at=case
      when public.phase3_live_identity_candidate.last_seen_at <= now()-interval '60 seconds'
      then now()
      else public.phase3_live_identity_candidate.last_seen_at
    end
  returning * into v_row;

  return jsonb_build_object(
    'ok',true,
    'state',v_row.candidate_state,
    'confidence',v_row.candidate_confidence,
    'evidence_count',v_row.evidence_count,
    'last_seen_at',v_row.last_seen_at
  );
end;
$$;

revoke all on function public.ft_record_phase3_shadow_identity(text,text,text,numeric,jsonb) from public,anon,authenticated;
grant execute on function public.ft_record_phase3_shadow_identity(text,text,text,numeric,jsonb) to service_role;
