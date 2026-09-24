update public.team_alias_registry_v2
set status='VERIFIED', confidence=1.0,
    verification_method='STATIC_CANONICAL_WOMEN_VARIANT', updated_at=now()
where (source,alias_key,team_key) in (
 ('ACC','barcelonaw','HKJC:barcelonawomen'),('ACC','chelseaw','HKJC:chelseawomen'),('ACC','fkaustriaviennaw','HKJC:austriaviennawomen'),('ACC','parisfcw','HKJC:parisfcwomen'),
 ('BCL','barcelonaw','HKJC:barcelonawomen'),('BCL','chelseaw','HKJC:chelseawomen'),('BCL','fkaustriaviennaw','HKJC:austriaviennawomen'),('BCL','parisfcw','HKJC:parisfcwomen'),
 ('FRB','austriawienw','HKJC:austriaviennawomen'),('FRB','barcelonaw','HKJC:barcelonawomen'),('FRB','chelseaw','HKJC:chelseawomen'),('FRB','parisw','HKJC:parisfcwomen'),
 ('STA','barcelonaw','HKJC:barcelonawomen'),('STA','parisfcw','HKJC:parisfcwomen')
) and status='CANDIDATE';
select public.ft_alias_maintenance_v2();
