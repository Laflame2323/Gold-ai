-- Research-only chronological benchmark for the daily 5-session direction target.
-- Uses only gold_daily_research_features_v2 inputs and a separate future-label view.
-- 70% chronological training set; five eligible observations purged before test.
-- The score is a simple train-correlation-weighted standardized linear score,
-- NOT a trained production model. No fees, spread, slippage, swap or execution model.
-- Date lags reduce look-ahead risk but do not prove exact historical publication times.

with base as (
 select f.session_date,
        case when l.target_direction_5_sessions > 0 then 1 else 0 end as y,
        l.target_return_5_sessions_pct as ret,
        array[
          f.gold_return_1d_pct,
          f.gold_return_5d_pct,
          f.gold_return_20d_pct,
          f.dgs10_change_5_calendar_days,
          f.dfii10_change_5_calendar_days,
          f.dollar_change_5_calendar_days_pct,
          f.vix_change_5_calendar_days_pct,
          f.managed_money_net_change_prior_report,
          f.managed_money_net_pct_oi_change_prior_report
        ]::double precision[] as x
 from public.gold_daily_research_features_v2 f
 join public.gold_daily_research_labels l using(session_date)
 where f.macro_complete and f.cot_available
   and l.target_direction_5_sessions is not null
   and f.dgs10_change_5_calendar_days is not null
   and f.dfii10_change_5_calendar_days is not null
   and f.dollar_change_5_calendar_days_pct is not null
   and f.vix_change_5_calendar_days_pct is not null
   and f.managed_money_net_change_prior_report is not null
   and f.managed_money_net_pct_oi_change_prior_report is not null
),
numbered as (
 select *, row_number() over(order by session_date) rn, count(*) over() n from base
),
train as (
 select * from numbered where rn <= floor(n*0.70)::int
),
test as (
 select * from numbered where rn > floor(n*0.70)::int + 5
),
stats as (
 select u.i, avg(u.val) mu, nullif(stddev_pop(u.val),0) sd,
        corr(u.val,t.y::double precision) weight
 from train t
 cross join lateral unnest(t.x) with ordinality u(val,i)
 group by u.i
),
majority as (
 select case when avg(y::double precision)>=0.5 then 1 else 0 end cls from train
),
scored as (
 select t.session_date,t.y,t.ret,
        (select sum(((u.val-s.mu)/s.sd)*s.weight)
         from unnest(t.x) with ordinality u(val,i)
         join stats s using(i)) score
 from test t
),
classified as (
 select *, case when score>=0 then 1 else 0 end pred from scored
)
select
 (select count(*) from train) train_rows,
 (select min(session_date) from train) train_start,
 (select max(session_date) from train) train_end,
 (select count(*) from test) test_rows,
 (select min(session_date) from test) test_start,
 (select max(session_date) from test) test_end,
 (select cls from majority) train_majority_class,
 count(*) evaluated,
 round(100.0*avg((pred=y)::int),2) accuracy_pct,
 round(100.0*sum((pred=1 and y=1)::int)::numeric/nullif(sum((pred=1)::int),0),2) precision_up_pct,
 sum((pred=1 and y=1)::int) true_up,
 sum((pred=1 and y=0)::int) false_up,
 sum((pred=0 and y=1)::int) missed_up,
 sum((pred=0 and y=0)::int) true_down,
 round(100.0*avg(((select cls from majority)=y)::int),2) majority_baseline_accuracy_pct,
 round(avg((case when pred=1 then 1.0 else -1.0 end)*ret)::numeric,4)
   mean_signed_5d_return_pct_before_costs,
 sum((pred=1)::int) predicted_up,
 sum((pred=0)::int) predicted_down
from classified;
