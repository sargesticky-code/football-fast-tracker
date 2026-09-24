
select cron.alter_job(3, active := false);
select cron.alter_job(4, schedule := '*/2 * * * *');
select cron.alter_job(6, schedule := '1-59/2 * * * *');
select cron.alter_job(9, active := false);
select cron.alter_job(12, schedule := '10,40 * * * *');
select cron.alter_job(13, schedule := '1,11,21,31,41,51 * * * *');
select cron.alter_job(14, schedule := '*/2 * * * *');
select cron.alter_job(15, schedule := '4,9,14,19,24,29,34,39,44,49,54,59 * * * *');
select cron.alter_job(16, schedule := '3,8,13,18,23,28,33,38,43,48,53,58 * * * *');
select cron.alter_job(17, schedule := '1-59/2 * * * *');
select cron.alter_job(23, schedule := '*/2 * * * *');
select cron.alter_job(28, schedule := '1-59/2 * * * *');
