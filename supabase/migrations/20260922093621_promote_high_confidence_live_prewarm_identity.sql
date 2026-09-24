
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
    p_hkjc_event_id,p_source,p_source_match_id,p_confidence,1,
    case when p_confidence>=0.95 then 'CANDIDATE' else 'CANDIDATE' end,
    coalesce(p_evidence,'{}'::jsonb)||jsonb_build_object('method','supabase_native_prewarm'),
    now(),now()
  )
  on conflict(hkjc_event_id,source,source_match_id) do update set
    candidate_confidence=least(public.phase3_live_identity_candidate.candidate_confidence,excluded.candidate_confidence),
    evidence_count=public.phase3_live_identity_candidate.evidence_count+1,
    candidate_state=case
      when public.phase3_live_identity_candidate.candidate_state='REJECTED' then 'REJECTED'
      when least(public.phase3_live_identity_candidate.candidate_confidence,excluded.candidate_confidence)>=0.95
       and public.phase3_live_identity_candidate.evidence_count+1>=3 then 'PROMOTABLE'
      else 'CANDIDATE'
    end,
    evidence=public.phase3_live_identity_candidate.evidence||excluded.evidence,
    last_seen_at=now()
  returning * into v_row;

  return jsonb_build_object(
    'ok',true,
    'state',v_row.candidate_state,
    'confidence',v_row.candidate_confidence,
    'evidence_count',v_row.evidence_count
  );
end;
$$;

revoke all on function public.ft_record_phase3_shadow_identity(text,text,text,numeric,jsonb) from public,anon,authenticated;
grant execute on function public.ft_record_phase3_shadow_identity(text,text,text,numeric,jsonb) to service_role;

create or replace function public.ft_promote_phase3_shadow_candidates()
returns jsonb
language plpgsql
security definer
set search_path=pg_catalog,public
as $$
declare
  v_promoted integer:=0;
begin
  with safe as (
    select c.*
    from public.phase3_live_identity_candidate c
    where c.candidate_state='PROMOTABLE'
      and c.candidate_confidence>=0.95
      and c.evidence_count>=3
      and not exists (
        select 1 from public.phase3_live_identity_map m
        where m.source=c.source
          and m.source_match_id=c.source_match_id
          and m.hkjc_event_id<>c.hkjc_event_id
      )
  ),
  ins as (
    insert into public.phase3_live_identity_map(
      hkjc_event_id,source,source_match_id,confidence,evidence_count,
      first_verified_at,last_verified_at,mapping_state,evidence,updated_at
    )
    select
      hkjc_event_id,source,source_match_id,candidate_confidence,evidence_count,
      first_seen_at,last_seen_at,'VERIFIED',
      evidence||jsonb_build_object('promotion_method','high_confidence_prewarm'),
      now()
    from safe
    on conflict(hkjc_event_id,source) do update set
      confidence=greatest(public.phase3_live_identity_map.confidence,excluded.confidence),
      evidence_count=greatest(public.phase3_live_identity_map.evidence_count,excluded.evidence_count),
      last_verified_at=greatest(public.phase3_live_identity_map.last_verified_at,excluded.last_verified_at),
      evidence=public.phase3_live_identity_map.evidence||excluded.evidence,
      updated_at=now()
    where public.phase3_live_identity_map.source_match_id=excluded.source_match_id
    returning 1
  )
  select count(*) into v_promoted from ins;

  return jsonb_build_object('promoted',v_promoted);
end;
$$;

revoke all on function public.ft_promote_phase3_shadow_candidates() from public,anon,authenticated;
grant execute on function public.ft_promote_phase3_shadow_candidates() to service_role;
