-- Leakage-aware daily gold research dataset.
-- Run against the Gold AI Supabase project. The corresponding views were
-- applied and validated on 2026-11-17.
--
-- Conservative alignment:
--   * Macro observations are restricted to dates <= gold session date - 1 day.
--   * CFTC report dates are restricted to dates <= gold session date - 3 days.
-- These calendar-day lags reduce look-ahead risk but do NOT prove exact
-- historical publication timestamps. A publication-time dataset is still
-- required before claiming a fully point-in-time backtest.

create or replace view public.gold_daily_research_features
with (security_invoker = true)
as
with gold as (
  select
    session_date,
    close::double precision as gold_close,
    lag(close::double precision, 1) over (order by session_date) as gold_close_lag_1d,
    lag(close::double precision, 5) over (order by session_date) as gold_close_lag_5d,
    lag(close::double precision, 20) over (order by session_date) as gold_close_lag_20d,
    high::double precision as gold_high,
    low::double precision as gold_low,
    source as gold_source,
    data_state as gold_data_state
  from public.market_history_daily
  where symbol = 'XAUUSD'
),
aligned as (
  select
    g.*,
    m.dgs10, m.dgs10_date,
    m.dfii10, m.dfii10_date,
    m.dtwexbgs, m.dtwexbgs_date,
    m.vixcls, m.vixcls_date,
    c.report_date as cot_report_date,
    c.open_interest::double precision as cot_open_interest,
    (c.managed_money_long - c.managed_money_short)::double precision as managed_money_net,
    (c.producer_merchant_long - c.producer_merchant_short)::double precision as producer_merchant_net,
    (c.swap_dealer_long - c.swap_dealer_short)::double precision as swap_dealer_net,
    (c.other_reportable_long - c.other_reportable_short)::double precision as other_reportable_net
  from gold g
  left join lateral (
    select
      max(value) filter (where series_id='DGS10') as dgs10,
      max(observation_date) filter (where series_id='DGS10') as dgs10_date,
      max(value) filter (where series_id='DFII10') as dfii10,
      max(observation_date) filter (where series_id='DFII10') as dfii10_date,
      max(value) filter (where series_id='DTWEXBGS') as dtwexbgs,
      max(observation_date) filter (where series_id='DTWEXBGS') as dtwexbgs_date,
      max(value) filter (where series_id='VIXCLS') as vixcls,
      max(observation_date) filter (where series_id='VIXCLS') as vixcls_date
    from (
      select distinct on (series_id) series_id, value, observation_date
      from public.macro_observations
      where observation_date <= g.session_date - 1
        and series_id in ('DGS10','DFII10','DTWEXBGS','VIXCLS')
      order by series_id, observation_date desc
    ) latest_macro
  ) m on true
  left join lateral (
    select report_date, open_interest, managed_money_long, managed_money_short,
      producer_merchant_long, producer_merchant_short,
      swap_dealer_long, swap_dealer_short,
      other_reportable_long, other_reportable_short
    from public.cot_gold_positions
    where report_date <= g.session_date - 3
    order by report_date desc
    limit 1
  ) c on true
)
select
  session_date, gold_close,
  case when gold_close_lag_1d > 0 then (gold_close / gold_close_lag_1d - 1) * 100 end as gold_return_1d_pct,
  case when gold_close_lag_5d > 0 then (gold_close / gold_close_lag_5d - 1) * 100 end as gold_return_5d_pct,
  case when gold_close_lag_20d > 0 then (gold_close / gold_close_lag_20d - 1) * 100 end as gold_return_20d_pct,
  gold_high, gold_low,
  dgs10, dgs10_date, dfii10, dfii10_date,
  dtwexbgs, dtwexbgs_date, vixcls, vixcls_date,
  cot_report_date, cot_open_interest,
  managed_money_net, producer_merchant_net, swap_dealer_net, other_reportable_net,
  case when cot_open_interest > 0 then managed_money_net / cot_open_interest * 100 end as managed_money_net_pct_oi,
  gold_source, gold_data_state,
  (dgs10_date is not null and dfii10_date is not null and dtwexbgs_date is not null and vixcls_date is not null) as macro_complete,
  (cot_report_date is not null) as cot_available,
  'Macro observations lagged by at least 1 calendar day; CFTC report dates lagged by at least 3 calendar days. Research alignment only, not proof of publication-time availability.'::text as leakage_control_note
from aligned;

create or replace view public.gold_daily_research_labels
with (security_invoker = true)
as
with future_prices as (
  select
    session_date,
    lead(close::double precision, 1) over (order by session_date) as close_fwd_1_session,
    lead(close::double precision, 5) over (order by session_date) as close_fwd_5_sessions,
    lead(close::double precision, 20) over (order by session_date) as close_fwd_20_sessions
  from public.market_history_daily
  where symbol='XAUUSD'
)
select
  f.session_date, f.gold_close,
  f.gold_return_1d_pct, f.gold_return_5d_pct, f.gold_return_20d_pct,
  f.dgs10, f.dgs10_date, f.dfii10, f.dfii10_date,
  f.dtwexbgs, f.dtwexbgs_date, f.vixcls, f.vixcls_date,
  f.cot_report_date, f.cot_open_interest,
  f.managed_money_net, f.producer_merchant_net,
  f.swap_dealer_net, f.other_reportable_net,
  f.managed_money_net_pct_oi, f.macro_complete, f.cot_available,
  case when p.close_fwd_1_session is not null and f.gold_close > 0
    then (p.close_fwd_1_session / f.gold_close - 1) * 100 end as target_return_1_session_pct,
  case when p.close_fwd_5_sessions is not null and f.gold_close > 0
    then (p.close_fwd_5_sessions / f.gold_close - 1) * 100 end as target_return_5_sessions_pct,
  case when p.close_fwd_20_sessions is not null and f.gold_close > 0
    then (p.close_fwd_20_sessions / f.gold_close - 1) * 100 end as target_return_20_sessions_pct,
  case when p.close_fwd_1_session is null then null
    when p.close_fwd_1_session > f.gold_close then 1
    when p.close_fwd_1_session < f.gold_close then -1 else 0 end as target_direction_1_session,
  case when p.close_fwd_5_sessions is null then null
    when p.close_fwd_5_sessions > f.gold_close then 1
    when p.close_fwd_5_sessions < f.gold_close then -1 else 0 end as target_direction_5_sessions,
  case when p.close_fwd_20_sessions is null then null
    when p.close_fwd_20_sessions > f.gold_close then 1
    when p.close_fwd_20_sessions < f.gold_close then -1 else 0 end as target_direction_20_sessions,
  'Targets are future session outcomes and must never be included in model input features.'::text as target_usage_note
from public.gold_daily_research_features f
join future_prices p using (session_date);

revoke all on public.gold_daily_research_features from anon, authenticated;
revoke all on public.gold_daily_research_labels from anon, authenticated;
grant select on public.gold_daily_research_features to service_role;
grant select on public.gold_daily_research_labels to service_role;
