select
    date_trunc('month', o.placed_at)::date as month,
    i.item,
    i.category,
    sum(i.quantity) as quantity,
    round(sum(i.line_total), 2) as sales
from {{ ref('order_items') }} i
join {{ ref('orders') }} o using (order_id)
where o.status = 'completed'
group by 1, 2, 3
