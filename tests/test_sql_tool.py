import psycopg
import pytest

from app.config import db_url
from app.sql_tool import MAX_ROWS, SQLRejected, run, validate


@pytest.mark.parametrize("sql", [
    "SELECT night_of_week, avg(orders) FROM daily_sales GROUP BY 1",
    "SELECT item, sum(quantity) FROM order_items JOIN orders USING (order_id) WHERE status = 'completed' GROUP BY 1",
    "WITH late AS (SELECT * FROM orders WHERE is_late) SELECT delay_reason, count(*) FROM late GROUP BY 1",
    "SELECT * FROM analytics.menu_items WHERE dietary_tags LIKE '%vegan%'",
    "SELECT hour FROM orders UNION SELECT 0",
])
def test_read_queries_are_allowed(sql):
    assert validate(sql).lower().startswith(("select", "with"))


@pytest.mark.parametrize("sql, reason", [
    ("DELETE FROM orders", "only SELECT"),
    ("DROP TABLE orders", "only SELECT"),
    ("SELECT 1; DROP TABLE orders", "exactly one"),
    ("SELECT * FROM raw.orders", "not available"),
    ("SELECT * FROM pg_catalog.pg_roles", "not available"),
    ("SELECT * FROM information_schema.tables", "not available"),
    ("SELECT * FROM customers", "not available"),
    ("SELECT pg_sleep(10)", "not allowed"),
    ("SELECT pg_read_file('/etc/passwd')", "not allowed"),
    ("SELECT set_config('statement_timeout', '0', false)", "not allowed"),
    ("WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x", "read-only"),
    ("COPY orders TO '/tmp/out.csv'", "only SELECT"),
    ("SET statement_timeout = 0", "only SELECT"),
    ("SELEC * FRM orders", "parse|only SELECT"),  # typos are refused either way
])
def test_unsafe_queries_are_rejected(sql, reason):
    with pytest.raises(SQLRejected, match=reason):
        validate(sql)


def test_tables_are_schema_qualified():
    assert "analytics.daily_sales" in validate("SELECT * FROM daily_sales")


def test_row_cap_is_added_and_enforced():
    assert f"LIMIT {MAX_ROWS}" in validate("SELECT * FROM orders")
    assert f"LIMIT {MAX_ROWS}" in validate("SELECT * FROM orders LIMIT 100000")
    assert "LIMIT 5" in validate("SELECT * FROM orders LIMIT 5")


@pytest.fixture(scope="module")
def database():
    try:
        psycopg.connect(db_url(readonly=True), connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.skip("database not running (docker compose up -d db)")


def test_run_returns_rows(database):
    result = run("SELECT night_of_week, round(avg(orders), 1) AS avg_orders FROM daily_sales GROUP BY 1 ORDER BY 2 DESC")
    assert result.error is None
    assert result.columns == ["night_of_week", "avg_orders"]
    assert result.rows[0][0] == "Sat"
    assert "| night_of_week | avg_orders |" in result.as_markdown()


def test_run_reports_rejections_instead_of_raising(database):
    result = run("DELETE FROM orders")
    assert result.error.startswith("rejected")
