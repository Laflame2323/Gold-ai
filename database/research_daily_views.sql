-- Leakage-aware daily research dataset for Gold AI.
-- Run after creating market_history_daily and macro_observations.
-- Features use only macro observations dated strictly before the gold session date.
-- Forward outcomes are isolated in research_daily_targets and must never be model inputs.

create index if not exists macro_observations_series_date_idx
  on public.macro_observations (series_id, observation_date desc);

create or replace view public.research_daily_features
with (security_invoker = true)
as
with base as (
  select
    session_date,
    close,
    high,
    low,
    lag(close) over (order by session_date) as prior_close,
    avg(close) over (order by session_date rows between 19 preceding and current row) as sma_20,
    avg(close) over (order by session_date rows between 49 preceding and current row) as sma_50
  from public.market_history_daily
  where symbol = 'XAUUSD'
),
returns as (
  select *,
    case when prior_close > 0 then (close / prior_close - 1) * 100 end as daily_return_pct
  from base
),
features as (
  select *,
    stddev_samp(daily_return_pct) over (
      order by session_date rows between 19 preceding and current row
    ) as realized_volatility_20d_pct
  from returns
)
select
  f.session_date,
  f.close,
  f.high,
  f.low,
  f.prior_close,
  f.daily_return_pct,
  f.sma_20,
  f.sma_50,
  case when f.sma_50 > 0 then (f.sma_20 / f.sma_50 - 1) * 100 end as sma_spread_pct,
  case when f.sma_20 > 0 then (f.close / f.sma_20 - 1) * 100 end as distance_from_sma20_pct,
  f.realized_volatility_20d_pct,
  real_yield.observation_date as real_yield_observation_date,
  real_yield.value as lagged_us_10y_real_yield,
  nominal_yield.observation_date as nominal_yield_observation_date,
  nominal_yield.value as lagged_us_10y_nominal_yield,
  dollar.observation_date as dollar_observation_date,
  dollar.value as lagged_us_dollar_broad_index,
  vix.observation_date as vix_observation_date,
  vix.value as lagged_vix,
  'XAUS daily reference prices + prior-date FRED observations'::text as dataset_source,
  'v1_no_lookahead_macro_lag'::text as dataset_version
from features f
left join lateral (
  select observation_date, value from public.macro_observations
  where series_id = 'DFII10' and observation_date < f.session_date
  order by observation_date desc limit 1
) real_yield on true
left join lateral (
  select observation_date, value from public.macro_observations
  where series_id = 'DGS10' and observation_date < f.session_date
  order by observation_date desc limit 1
) nominal_yield on true
left join lateral (
  select observation_date, value from public.macro_observations
  where series_id = 'DTWEXBGS' and observation_date < f.session_date
  order by observation_date desc limit 1
) dollar on true
left join lateral (
  select observation_date, value from public.macro_observations
  where series_id = 'VIXCLS' and observation_date < f.session_date
  order by observation_date desc limit 1
) vix on true;

create or replace view public.research_daily_targets
with (security_invoker = true)
as
with future_prices as (
  select
    session_date,
    close,
    lead(close, 1) over (order by session_date) as close_plus_1_session,
    lead(close, 5) over (order by session_date) as close_plus_5_sessions,
    lead(close, 20) over (order by session_date) as close_plus_20_sessions
  from public.market_history_daily
  where symbol = 'XAUUSD'
)
select
  session_date,
  case when close_plus_1_session is not null
    then (close_plus_1_session / close - 1) * 100 end as forward_return_1_session_pct,
  case when close_plus_1_session > close then 1
       when close_plus_1_session < close then -1
       when close_plus_1_session = close then 0 end as forward_direction_1_session,
  case when close_plus_5_sessions is not null
    then (close_plus_5_sessions / close - 1) * 100 end as forward_return_5_sessions_pct,
  case when close_plus_20_sessions is not null
    then (close_plus_20_sessions / close - 1) * 100 end as forward_return_20_sessions_pct,
  'targets_only_keep_out_of_feature_columns'::text as target_usage_note
from future_prices;

revoke all on public.research_daily_features from anon, authenticated;
revoke all on public.research_daily_targets from anon, authenticated;
grant select on public.research_daily_features to service_role;
grant select on public.research_daily_targets to service_role;
