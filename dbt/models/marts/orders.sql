-- One row per order, with its delivery outcome
select
    o.order_id,
    o.placed_at,
    o.trading_night,
    to_char(o.trading_night, 'Dy') as night_of_week,
    extract(hour from o.placed_at)::int as hour,
    o.channel,
    o.items,
    o.total,                                   -- paid by the customer, before Uber's commission
    o.status,
    d.promised_minutes,
    d.actual_minutes,
    d.actual_minutes - d.promised_minutes as minutes_late,
    coalesce(d.actual_minutes - d.promised_minutes > 10, false) as is_late,
    nullif(d.delay_reason, '') as delay_reason
from {{ source('raw', 'orders') }} o
left join {{ source('raw', 'deliveries') }} d using (order_id)
