select cron.unschedule(jobid)
from cron.job
where jobname='fast-tracker-live-score-5min';

select cron.schedule(
  'live-score-direct-5min',
  '*/5 * * * *',
  $$select net.http_get(
    url := 'https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/live-score-direct'
  );$$
);
