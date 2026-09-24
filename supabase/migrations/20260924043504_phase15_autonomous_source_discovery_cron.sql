
select cron.schedule(
  'phase15-source-scout-6h',
  '27 */6 * * *',
  $$select net.http_get(
      url := 'https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/phase15-source-scout',
      timeout_milliseconds := 60000
    );$$
);

select cron.schedule(
  'phase15-discovery-maintenance-6h',
  '37 */6 * * *',
  $$select private.ft_phase15_discovery_maintenance();$$
);
