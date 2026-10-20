-- Fails if nightly sales don't add up to the order-level total
select 'mismatch' as problem
from (select sum(sales) as s from {{ ref('daily_sales') }}) d,
     (select sum(total) as s from {{ ref('orders') }} where status = 'completed') o
where abs(d.s - o.s) > 0.01
