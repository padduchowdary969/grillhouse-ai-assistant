select
    i.order_id,
    i.item,
    m.category,
    i.quantity,
    i.unit_price,
    i.quantity * i.unit_price as line_total
from {{ source('raw', 'order_items') }} i
join {{ source('raw', 'menu_items') }} m using (item)
