"""Security boundary of the assistant's database user. Skipped when the database isn't running."""

import psycopg
import pytest

from app.config import db_url


@pytest.fixture(scope="module")
def readonly():
    try:
        conn = psycopg.connect(db_url(readonly=True), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("database not running (docker compose up -d db)")
    yield conn
    conn.close()


def test_can_read_analytics(readonly):
    assert readonly.execute("SELECT count(*) FROM analytics.daily_sales").fetchone()[0] > 0


def test_cannot_read_raw_tables(readonly):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        readonly.execute("SELECT * FROM raw.orders LIMIT 1")


@pytest.mark.parametrize("sql", ["CREATE TABLE analytics.x (i int)", "DELETE FROM analytics.orders",
                                 "UPDATE analytics.menu_items SET price = 0"])
def test_cannot_write(readonly, sql):
    with pytest.raises(psycopg.Error):
        readonly.execute(sql)


def test_long_queries_are_cancelled(readonly):
    with pytest.raises(psycopg.errors.QueryCanceled):
        readonly.execute("SELECT pg_sleep(6)")
