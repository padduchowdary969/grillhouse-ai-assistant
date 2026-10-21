#!/bin/bash
# Runs once, when the database volume is first created.
# The owner (grillhouse) loads data; copilot_readonly is what the AI's SQL tool connects as, so even a bad or
# malicious query can only read the analytics tables.
set -euo pipefail

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ro_password="$GRILLHOUSE_READONLY_PASSWORD" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS raw;        -- tables as loaded from seed_data/
CREATE SCHEMA IF NOT EXISTS analytics;  -- dbt models the assistant queries

CREATE ROLE copilot_readonly LOGIN PASSWORD :'ro_password';
ALTER ROLE copilot_readonly SET default_transaction_read_only = on;
ALTER ROLE copilot_readonly SET statement_timeout = '5s';
REVOKE ALL ON SCHEMA public FROM PUBLIC;
-- pgvector's type and operators live in public: allow using them, not creating anything there
GRANT USAGE ON SCHEMA public TO copilot_readonly;
GRANT CONNECT ON DATABASE grillhouse TO copilot_readonly;
GRANT USAGE ON SCHEMA analytics TO copilot_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO copilot_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE grillhouse IN SCHEMA analytics GRANT SELECT ON TABLES TO copilot_readonly;
SQL
