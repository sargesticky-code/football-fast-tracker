select cron.schedule(
  'hkjc-live-direct-5min',
  '*/5 * * * *',
  $$select net.http_get(
    url := 'https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/hkjc-live-direct'
  );$$
);

select cron.schedule(
  'fast-tracker-live-score-5min',
  '*/5 * * * *',
  $$select net.http_post(
    url := 'https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/sync-fast-tracker',
    headers := '{"Content-Type":"application/json"}'::jsonb,
    body := '{"mode":"live"}'::jsonb
  );$$
);
