-- Fails if a phone number or email survived redaction
select order_id, comment from {{ ref('reviews') }}
where comment ~ '07[0-9]{3}\s?[0-9]{3}\s?[0-9]{3}' or comment like '%@%'
