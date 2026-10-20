-- Comments were PII-redacted at ingestion
select order_id, ordered_at, trading_night, delivery_minutes, rated_on, rating, nullif(tags, '') as tags,
       nullif(comment, '') as comment, fulfilment
from {{ source('raw', 'reviews') }}
