
insert into storage.buckets (id,name,public,file_size_limit,allowed_mime_types)
values (
  'fast-tracker-ingest',
  'fast-tracker-ingest',
  false,
  5242880,
  array['text/csv','text/plain','application/octet-stream']::text[]
)
on conflict (id) do update
set public=false,
    file_size_limit=excluded.file_size_limit,
    allowed_mime_types=excluded.allowed_mime_types;

do $$
begin
  if exists (select 1 from cron.job where jobname='fast-tracker-current') then
    perform cron.unschedule('fast-tracker-current');
  end if;
end
$$;
