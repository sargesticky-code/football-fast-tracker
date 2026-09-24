
do $$
declare j record;
begin
  for j in select jobid from cron.job where jobname='live-source-shadow-2min'
  loop perform cron.unschedule(j.jobid); end loop;
end $$;

select cron.schedule(
  'live-source-shadow-2min',
  '*/2 * * * *',
  $cron$
    select net.http_get(
      url := 'https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/live-source-shadow'
    );
  $cron$
);

select net.http_get(
  url := 'https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/live-source-shadow'
) as request_id;
