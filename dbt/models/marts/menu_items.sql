select item, category, price, allergens, dietary_tags, spice_level
from {{ source('raw', 'menu_items') }}
