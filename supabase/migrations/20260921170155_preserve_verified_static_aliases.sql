
create or replace function public.ft_preserve_verified_alias_v2()
returns trigger
language plpgsql
set search_path='pg_catalog','public','pg_temp'
as $$
begin
  if old.status='VERIFIED' and new.status='CANDIDATE' then
    new.status := 'VERIFIED';
    new.confidence := greatest(coalesce(old.confidence,0),coalesce(new.confidence,0));
    new.verification_method := coalesce(nullif(old.verification_method,''),new.verification_method);
    new.first_seen_at := least(old.first_seen_at,new.first_seen_at);
  end if;
  return new;
end
$$;

drop trigger if exists team_alias_registry_preserve_verified on public.team_alias_registry_v2;
create trigger team_alias_registry_preserve_verified
before update on public.team_alias_registry_v2
for each row execute function public.ft_preserve_verified_alias_v2();

insert into public.team_alias_registry_v2(
  source,alias_key,team_key,alias,status,confidence,evidence_count,distinct_event_count,
  verification_method,first_seen_at,last_seen_at,updated_at
)
values
  ('FOREBET',public.ft_team_name_key('Inter Milano W'),'HKJC:intermilanwomen','Inter Milano W','VERIFIED',1.0,1,1,'MANUAL_SOURCE_FIXTURE',now(),now(),now()),
  ('FOREBET',public.ft_team_name_key('Hacken W'),'HKJC:hackenwomen','Hacken W','VERIFIED',1.0,1,1,'MANUAL_SOURCE_FIXTURE',now(),now(),now()),
  ('FOREBET',public.ft_team_name_key('Bayern Munich W'),'HKJC:bayernmunichwomen','Bayern Munich W','VERIFIED',1.0,1,1,'MANUAL_SOURCE_FIXTURE',now(),now(),now()),
  ('FOREBET',public.ft_team_name_key('Man City W'),'HKJC:manchestercitywomen','Man City W','VERIFIED',1.0,1,1,'MANUAL_SOURCE_FIXTURE',now(),now(),now())
on conflict(source,alias_key,team_key) do update set
  alias=excluded.alias,
  status='VERIFIED',
  confidence=1.0,
  evidence_count=greatest(public.team_alias_registry_v2.evidence_count,1),
  distinct_event_count=greatest(public.team_alias_registry_v2.distinct_event_count,1),
  verification_method='MANUAL_SOURCE_FIXTURE',
  last_seen_at=now(),
  updated_at=now();
