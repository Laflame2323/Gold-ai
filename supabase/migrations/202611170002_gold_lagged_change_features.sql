-- Add lagged changes in macro conditions and CFTC positioning as research inputs.
-- This view contains historical features only; forward targets remain in gold_daily_research_labels.
-- Macro comparisons use observations at least six calendar days before the gold session.
-- CFTC changes compare the latest eligible report with the immediately prior report.
-- These date lags reduce look-ahead risk but do not prove exact publication-time availability.

create or replace view public.gold_daily_research_features_v2
with (security_invoker = true) as
select
  f.*,
  case when m5.dgs10 is not null then f.dgs10::double precision - m5.dgs10::double precision end as dgs10_change_5_calendar_days,
  case when m5.dfii10 is not null then f.dfii10::double precision - m5.dfii10::double precision end as dfii10_change_5_calendar_days,
  case when m5.dtwexbgs is not null and m5.dtwexbgs <> 0 then (f.dtwexbgs::double precision / m5.dtwexbgs::double precision - 1) * 100 end as dollar_change_5_calendar_days_pct,
  case when m5.vixcls is not null and m5.vixcls <> 0 then (f.vixcls::double precision / m5.vixcls::double precision - 1) * 100 end as vix_change_5_calendar_days_pct,
  case when cp.report_date is not null then f.managed_money_net - (cp.managed_money_long - cp.managed_money_short) end as managed_money_net_change_prior_report,
  case when cp.report_date is not null then f.producer_merchant_net - (cp.producer_merchant_long - cp.producer_merchant_short) end as producer_merchant_net_change_prior_report,
  case when cp.report_date is not null then f.swap_dealer_net - (cp.swap_dealer_long - cp.swap_dealer_short) end as swap_dealer_net_change_prior_report,
  case when cp.report_date is not null then f.other_reportable_net - (cp.other_reportable_long - cp.other_reportable_short) end as other_reportable_net_change_prior_report,
  case when cp.report_date is not null and cp.open_interest > 0 then
    f.managed_money_net / nullif(f.cot_open_interest,0) * 100
    - ((cp.managed_money_long - cp.managed_money_short)::double precision / nullif(cp.open_interest,0)::double precision) * 100
  end as managed_money_net_pct_oi_change_prior_report
from public.gold_daily_research_features f
left join lateral (
  select
    max(value) filter (where series_id='DGS10') as dgs10,
    max(value) filter (where series_id='DFII10') as dfii10,
    max(value) filter (where series_id='DTWEXBGS') as dtwexbgs,
    max(value) filter (where series_id='VIXCLS') as vixcls
  from (
    select distinct on (series_id) series_id, value
    from public.macro_observations
    where observation_date <= f.session_date - 6
      and series_id in ('DGS10','DFII10','DTWEXBGS','VIXCLS')
    order by series_id, observation_date desc
  ) prior_macro
) m5 on true
left join lateral (
  select report_date, open_interest,
    managed_money_long, managed_money_short,
    producer_merchant_long, producer_merchant_short,
    swap_dealer_long, swap_dealer_short,
    other_reportable_long, other_reportable_short
  from public.cot_gold_positions
  where report_date < f.cot_report_date
  order by report_date desc
  limit 1
) cp on true;

revoke all on public.gold_daily_research_features_v2 from anon, authenticated;
grant select on public.gold_daily_research_features_v2 to service_role;
