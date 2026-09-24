select cron.schedule(
  'hkjc-upcoming-direct-15min',
  '*/15 * * * *',
  $$select net.http_get(
    url := 'https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/hkjc-upcoming-direct'
  );$$
);
