
select cron.alter_job(9, schedule := '*/10 * * * *');

select net.http_post(
  url := 'https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/sync-fast-tracker',
  headers := jsonb_build_object(
    'Content-Type','application/json',
    'x-fast-tracker-cron',(select decrypted_secret from vault.decrypted_secrets where name='fast_tracker_cron_secret' limit 1)
  ),
  body := '{"mode":"current"}'::jsonb,
  timeout_milliseconds := 30000
);
