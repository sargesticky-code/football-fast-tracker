create extension if not exists pg_cron;

do $$
declare r record;
begin
  for r in select jobid from cron.job where jobname in ('fast-tracker-current','fast-tracker-live','fast-tracker-archive')
  loop
    perform cron.unschedule(r.jobid);
  end loop;
end $$;

select cron.schedule(
  'fast-tracker-current',
  '*/15 * * * *',
  $job$
  select net.http_post(
    url := 'https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/sync-fast-tracker',
    headers := jsonb_build_object(
      'Content-Type','application/json',
      'x-fast-tracker-cron',(select decrypted_secret from vault.decrypted_secrets where name='fast_tracker_cron_secret' limit 1)
    ),
    body := '{"mode":"current"}'::jsonb,
    timeout_milliseconds := 15000
  );
  $job$
);

select cron.schedule(
  'fast-tracker-live',
  '*/5 * * * *',
  $job$
  select net.http_post(
    url := 'https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/sync-fast-tracker',
    headers := jsonb_build_object(
      'Content-Type','application/json',
      'x-fast-tracker-cron',(select decrypted_secret from vault.decrypted_secrets where name='fast_tracker_cron_secret' limit 1)
    ),
    body := '{"mode":"live"}'::jsonb,
    timeout_milliseconds := 15000
  );
  $job$
);

select cron.schedule(
  'fast-tracker-archive',
  '20 23 * * *',
  $job$
  select net.http_post(
    url := 'https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/sync-fast-tracker',
    headers := jsonb_build_object(
      'Content-Type','application/json',
      'x-fast-tracker-cron',(select decrypted_secret from vault.decrypted_secrets where name='fast_tracker_cron_secret' limit 1)
    ),
    body := '{"mode":"archive"}'::jsonb,
    timeout_milliseconds := 30000
  );
  $job$
);
