-- Four expanding-window walk-forward folds for the 5-session direction diagnostic.
-- Five eligible rows are embargoed between each training cutoff and test window.
-- Features are standardized and correlation-weighted using that fold's training data only.
-- This is a diagnostic score, not a production ML model or trading strategy.
with base as (
 select f.session_date,
        case when l.target_direction_5_sessions>0 then 1 else 0 end y,
        l.target_return_5_sessions_pct ret,
        array[f.gold_return_1d_pct,f.gold_return_5d_pct,f.gold_return_20d_pct,
              f.dgs10_change_5_calendar_days,f.dfii10_change_5_calendar_days,
              f.dollar_change_5_calendar_days_pct,f.vix_change_5_calendar_days_pct,
              f.managed_money_net_change_prior_report,
              f.managed_money_net_pct_oi_change_prior_report]::double precision[] x
 from public.gold_daily_research_features_v2 f
 join public.gold_daily_research_labels l using(session_date)
 where f.macro_complete and f.cot_available and l.target_direction_5_sessions is not null
   and f.dgs10_change_5_calendar_days is not null
   and f.dfii10_change_5_calendar_days is not null
   and f.dollar_change_5_calendar_days_pct is not null
   and f.vix_change_5_calendar_days_pct is not null
   and f.managed_money_net_change_prior_report is not null
   and f.managed_money_net_pct_oi_change_prior_report is not null
),
numbered as (
 select *,row_number() over(order by session_date) rn,count(*) over() n from base
),
bounds as (select floor(max(n)*0.70)::int cut,max(n)::int n from numbered),
folds as (
 select 1 fold,cut+6 start_rn,cut+55 end_rn from bounds
 union all select 2,cut+56,cut+105 from bounds
 union all select 3,cut+106,cut+155 from bounds
 union all select 4,cut+156,n from bounds
),
training as (
 select f.fold,n.* from folds f join numbered n on n.rn<=f.start_rn-6
),
fold_stats as (
 select t.fold,u.i,avg(u.val) mu,nullif(stddev_pop(u.val),0) sd,
        corr(u.val,t.y::double precision) weight
 from training t cross join lateral unnest(t.x) with ordinality u(val,i)
 group by t.fold,u.i
),
fold_majority as (
 select fold,case when avg(y::double precision)>=0.5 then 1 else 0 end cls
 from training group by fold
),
test_rows as (
 select f.fold,n.* from folds f join numbered n on n.rn between f.start_rn and f.end_rn
),
scored as (
 select t.fold,t.session_date,t.y,t.ret,
        (select sum(((u.val-s.mu)/s.sd)*s.weight)
         from unnest(t.x) with ordinality u(val,i)
         join fold_stats s on s.fold=t.fold and s.i=u.i) score
 from test_rows t
),
classified as (
 select s.*,case when score>=0 then 1 else 0 end pred,m.cls majority
 from scored s join fold_majority m using(fold)
)
select fold,count(*) test_rows,min(session_date) test_start,max(session_date) test_end,
       round(100.0*avg((pred=y)::int),2) score_accuracy_pct,
       round(100.0*avg((majority=y)::int),2) train_majority_accuracy_pct,
       round(100.0*sum((pred=1 and y=1)::int)::numeric/nullif(sum((pred=1)::int),0),2) precision_up_pct,
       sum((pred=1)::int) predicted_up,sum((pred=0)::int) predicted_down,
       round(avg((case when pred=1 then 1.0 else -1.0 end)*ret)::numeric,4)
         signed_return_pct_before_costs
from classified group by fold order by fold;
