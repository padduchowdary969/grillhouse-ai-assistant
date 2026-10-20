-- Raw tables, rebuilt on every load by pipelines/load_db.py

DROP TABLE IF EXISTS raw.order_items, raw.deliveries, raw.reviews, raw.orders, raw.menu_items,
                     raw.daily_context, raw.events, raw.documents CASCADE;

CREATE TABLE raw.menu_items (
    item          text PRIMARY KEY,
    category      text NOT NULL,
    price         numeric(6, 2) NOT NULL CHECK (price >= 0),
    allergens     text,
    dietary_tags  text,
    spice_level   smallint NOT NULL CHECK (spice_level BETWEEN 0 AND 3)
);

CREATE TABLE raw.orders (
    order_id       text PRIMARY KEY,
    placed_at      timestamp NOT NULL,   -- Europe/London local time
    trading_night  date NOT NULL,        -- the evening the shift started (orders after midnight belong to it)
    channel        text NOT NULL CHECK (channel IN ('delivery', 'pickup')),
    items          integer NOT NULL CHECK (items > 0),
    total          numeric(8, 2) NOT NULL CHECK (total >= 0),  -- what the customer paid, before Uber's commission
    status         text NOT NULL CHECK (status IN ('completed', 'cancelled'))
);

CREATE TABLE raw.order_items (
    order_id    text NOT NULL REFERENCES raw.orders,
    item        text NOT NULL REFERENCES raw.menu_items,
    quantity    integer NOT NULL CHECK (quantity > 0),
    unit_price  numeric(6, 2) NOT NULL,
    PRIMARY KEY (order_id, item)
);

CREATE TABLE raw.deliveries (
    order_id          text PRIMARY KEY REFERENCES raw.orders,
    promised_minutes  integer NOT NULL,
    actual_minutes    integer,           -- null when cancelled
    status            text NOT NULL CHECK (status IN ('delivered', 'cancelled')),
    delay_reason      text               -- set when more than 10 minutes late
);

CREATE TABLE raw.daily_context (
    date             date PRIMARY KEY,
    temp_max_c       numeric(4, 1),
    temp_min_c       numeric(4, 1),
    precip_mm        numeric(5, 1),
    rain_mm          numeric(5, 1),
    wind_max_kmh     numeric(5, 1),
    is_rainy         boolean,
    bank_holiday     text,
    is_bank_holiday  boolean
);

CREATE TABLE raw.events (
    trading_night     date NOT NULL,
    event             text,
    courier_shortage  boolean NOT NULL
);

CREATE TABLE raw.reviews (
    order_id          text,
    ordered_at        timestamp,
    hour              integer,
    trading_night     text,
    delivery_minutes  numeric,
    rated_on          date,
    rating            integer CHECK (rating BETWEEN 1 AND 5),
    tags              text,
    comment           text,               -- PII-redacted at ingestion
    fulfilment        text,
    app               text
);

-- Document chunks for retrieval (filled in Phase 2); 768 = nomic-embed-text dimensions
CREATE TABLE raw.documents (
    id         bigserial PRIMARY KEY,
    source     text NOT NULL,
    heading    text,
    content    text NOT NULL,
    embedding  vector(768)
);
