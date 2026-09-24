
insert into public.system_config(key,value,updated_at)
values ('live_upstream_expected_build','LIVE-UPSTREAM-20260922-2',now())
on conflict(key) do update set value=excluded.value,updated_at=excluded.updated_at;
