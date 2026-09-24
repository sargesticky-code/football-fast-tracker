
do $$
declare j record;
begin
  for j in select jobid from cron.job where jobname='frontend-route-guard-5min'
  loop
    perform cron.unschedule(j.jobid);
  end loop;
end $$;

select cron.schedule(
  'frontend-route-guard-5min',
  '*/5 * * * *',
  $cron$
    select net.http_post(
      url := 'https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/frontend-route-guard',
      headers := jsonb_build_object(
        'Content-Type','application/json',
        'x-fast-tracker-cron',(select decrypted_secret from vault.decrypted_secrets where name='fast_tracker_cron_secret' limit 1)
      ),
      body := '{}'::jsonb,
      timeout_milliseconds := 30000
    );
  $cron$
);

select net.http_post(
  url := 'https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/frontend-route-guard',
  headers := jsonb_build_object(
    'Content-Type','application/json',
    'x-fast-tracker-cron',(select decrypted_secret from vault.decrypted_secrets where name='fast_tracker_cron_secret' limit 1)
  ),
  body := '{}'::jsonb,
  timeout_milliseconds := 30000
);
