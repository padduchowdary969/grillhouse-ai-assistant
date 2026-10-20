-- One row per trading night (18:00 to closing), with the context that explains busy and quiet nights.
-- Built from the calendar so nights with no orders still appear (as zeros).
with calendar as (
    select generate_series(min(trading_night), max(trading_night), interval '1 day')::date as trading_night
    from {{ ref('orders') }}
),
nights as (
    select
        trading_night,
        count(*) filter (where status = 'completed') as orders,
        count(*) filter (where status = 'cancelled') as cancelled_orders,
        coalesce(sum(total) filter (where status = 'completed'), 0) as sales,
        count(*) filter (where status = 'completed' and channel = 'pickup') as pickup_orders,
        count(*) filter (where is_late) as late_deliveries,
        avg(minutes_late) filter (where channel = 'delivery' and status = 'completed') as avg_minutes_late
    from {{ ref('orders') }}
    group by trading_night
),
events as (
    select trading_night, max(nullif(event, '')) as event, bool_or(courier_shortage) as courier_shortage
    from {{ source('raw', 'events') }}
    group by trading_night
)
select
    cal.trading_night,
    to_char(cal.trading_night, 'Dy') as night_of_week,
    coalesce(n.orders, 0) as orders,
    coalesce(n.cancelled_orders, 0) as cancelled_orders,
    round(coalesce(n.sales, 0), 2) as sales,
    round(n.sales / nullif(n.orders, 0), 2) as avg_order_value,
    coalesce(n.pickup_orders, 0) as pickup_orders,
    coalesce(n.late_deliveries, 0) as late_deliveries,
    round(n.avg_minutes_late, 1) as avg_minutes_late,
    c.temp_max_c,
    c.precip_mm,
    c.is_rainy,
    c.bank_holiday,
    coalesce(c.is_bank_holiday, false) as is_bank_holiday,
    e.event,
    coalesce(e.courier_shortage, false) as courier_shortage
from calendar cal
left join nights n using (trading_night)
left join {{ source('raw', 'daily_context') }} c on c.date = cal.trading_night
left join events e on e.trading_night = cal.trading_night
