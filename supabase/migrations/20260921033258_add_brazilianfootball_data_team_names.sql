
create or replace function public.ft_refresh_brazilianfootball_team_names()
returns jsonb
language plpgsql
security definer
set search_path=public
as $$
declare
  v_rows integer := 0;
begin
  with seeds(source_name,hkjc_name_en,evidence) as (
    values
      ('Criciúma','Criciuma','BrazilianFootball/Data Serie_B_2025 observed source name'),
      ('Operário','Operario Ferroviario','BrazilianFootball/Data Serie_B_2024+2025 observed source name'),
      ('Cuiabá','Cuiaba','BrazilianFootball/Data Serie_B_2025 observed source name'),
      ('Náutico','Nautico Recife','BrazilianFootball/Data Serie_C_2024+2025 observed source name')
  ),
  ins as (
    insert into public.team_name_master(
      source,source_name,source_key,team_key,hkjc_name_en,hkjc_name_zh,
      status,confidence,event_count,first_seen_at,last_seen_at,evidence_sources,updated_at
    )
    select
      'BRAZILIANFOOTBALL_DATA',
      s.source_name,
      public.ft_team_name_key(s.source_name),
      te.team_key,
      te.hkjc_name_en,
      te.hkjc_name_zh,
      'VERIFIED',
      1.0,
      2,
      now(),
      now(),
      jsonb_build_array(s.evidence),
      now()
    from seeds s
    join public.team_entities_v2 te
      on te.name_key=public.ft_team_name_key(s.hkjc_name_en)
    on conflict(source,source_key,team_key) do update set
      source_name=excluded.source_name,
      hkjc_name_en=excluded.hkjc_name_en,
      hkjc_name_zh=excluded.hkjc_name_zh,
      status='VERIFIED',
      confidence=1.0,
      event_count=greatest(public.team_name_master.event_count,excluded.event_count),
      evidence_sources=excluded.evidence_sources,
      last_seen_at=now(),
      updated_at=now()
    returning 1
  )
  select count(*) into v_rows from ins;
  return jsonb_build_object('brazilianfootball_verified',v_rows);
end
$$;

create or replace function public.ft_alias_maintenance_v2()
returns jsonb
language plpgsql
security definer
set search_path=public
as $$
declare
  v_refresh jsonb;
  v_promote jsonb;
  v_master jsonb;
  v_women jsonb;
  v_brazil jsonb;
begin
  v_refresh := public.ft_refresh_team_alias_v2();
  v_promote := public.ft_promote_verified_alias_v2();
  v_master := public.ft_refresh_team_name_master();
  v_women := public.ft_refresh_womens_intl_team_names();
  v_brazil := public.ft_refresh_brazilianfootball_team_names();

  return jsonb_build_object(
    'alias_v2',v_refresh,
    'promotion',v_promote,
    'team_name_master',v_master,
    'womens_intl_names',v_women,
    'brazilianfootball_names',v_brazil
  );
end
$$;

select public.ft_refresh_brazilianfootball_team_names();
