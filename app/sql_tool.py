"""The copilot's SQL tool: validate a model-written query, then run it as the read-only database user.

Two independent layers of protection:
  1. validate() parses the query with sqlglot and allows only one read-only SELECT over the approved
     analytics tables, with no system tables or dangerous functions; it also caps the number of rows.
  2. run() executes as `copilot_readonly`, which can't write, can't see the raw schema and is cancelled after
     5 seconds (see db/init/01_roles.sh), so anything the validator misses still can't do damage.

    from app.sql_tool import run
    result = run("SELECT night_of_week, avg(orders) FROM daily_sales GROUP BY 1")
    print(result.as_markdown())
"""

from dataclasses import dataclass, field

import psycopg
import sqlglot
from sqlglot import exp

from app.config import db_url

SCHEMA = "analytics"
ALLOWED_TABLES = {"orders", "order_items", "daily_sales", "item_sales_monthly", "menu_items", "reviews"}
MAX_ROWS = 200
# Functions a read-only query never needs; pg_* also covers pg_sleep, pg_read_file and friends
BLOCKED_FUNCTIONS = {"dblink", "lo_import", "lo_export", "set_config", "current_setting", "query_to_xml",
                     "copy", "txid_current"}
WRITE_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Merge, exp.Command,
               exp.Copy, exp.Grant, exp.TruncateTable, exp.Set, exp.Transaction, exp.Commit, exp.Rollback)


class SQLRejected(ValueError):
    """The query was refused before reaching the database; the message says why, for the model to fix it."""


def validate(sql: str) -> str:
    """Return the query to run (schema-qualified, row-capped), or raise SQLRejected."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as err:
        raise SQLRejected(f"could not parse the query: {str(err).splitlines()[0]}") from err
    if len(statements) != 1:
        raise SQLRejected("send exactly one SQL statement")
    query = statements[0]
    if not isinstance(query, (exp.Select, exp.SetOperation)):
        raise SQLRejected("only SELECT queries are allowed")
    if any(isinstance(node, WRITE_NODES) for node in query.walk()):
        raise SQLRejected("only read-only queries are allowed")

    cte_names = {cte.alias_or_name.lower() for cte in query.find_all(exp.CTE)}
    for table in query.find_all(exp.Table):
        name, schema = table.name.lower(), (table.db or "").lower()
        if not schema and name in cte_names:
            continue
        if schema not in ("", SCHEMA) or name not in ALLOWED_TABLES:
            raise SQLRejected(f"table {table.sql()} is not available; use one of: {', '.join(sorted(ALLOWED_TABLES))}")
        table.set("db", exp.to_identifier(SCHEMA))

    for func in query.find_all(exp.Func):
        name = (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()
        if name.startswith("pg_") or name in BLOCKED_FUNCTIONS:
            raise SQLRejected(f"function {name} is not allowed")

    limit = query.args.get("limit")
    if limit is None:
        query = query.limit(MAX_ROWS)
    elif isinstance(limit.expression, exp.Literal) and int(limit.expression.this) > MAX_ROWS:
        query = query.limit(MAX_ROWS)
    return query.sql(dialect="postgres")


@dataclass
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[tuple]
    truncated: bool = False
    error: str | None = field(default=None)

    def as_markdown(self, max_rows: int = 50) -> str:
        if self.error:
            return f"Query failed: {self.error}"
        if not self.rows:
            return "The query returned no rows."
        lines = ["| " + " | ".join(self.columns) + " |", "|" + "---|" * len(self.columns)]
        for row in self.rows[:max_rows]:
            lines.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
        if len(self.rows) > max_rows or self.truncated:
            lines.append(f"(showing {min(len(self.rows), max_rows)} of {'at least ' if self.truncated else ''}{len(self.rows)} rows)")
        return "\n".join(lines)


def run(sql: str) -> QueryResult:
    """Validate and execute. Validation failures and database errors come back in `error`, not as exceptions,
    so the agent can show the model what went wrong and let it retry."""
    try:
        safe_sql = validate(sql)
    except SQLRejected as err:
        return QueryResult(sql=sql, columns=[], rows=[], error=f"rejected: {err}")
    try:
        with psycopg.connect(db_url(readonly=True), connect_timeout=5) as conn:
            cur = conn.execute(safe_sql)
            rows = cur.fetchall()
            return QueryResult(sql=safe_sql, columns=[c.name for c in cur.description], rows=rows,
                               truncated=len(rows) >= MAX_ROWS)
    except psycopg.Error as err:
        return QueryResult(sql=safe_sql, columns=[], rows=[], error=str(err).splitlines()[0])


def schema_description() -> str:
    """Tables and columns the model may query, read from the database so it never goes stale."""
    with psycopg.connect(db_url(readonly=True), connect_timeout=5) as conn:
        rows = conn.execute(
            """SELECT table_name, column_name, data_type FROM information_schema.columns
               WHERE table_schema = %s ORDER BY table_name, ordinal_position""", (SCHEMA,)).fetchall()
    tables: dict[str, list[str]] = {}
    for table, column, dtype in rows:
        if table in ALLOWED_TABLES:
            tables.setdefault(table, []).append(f"{column} {dtype}")
    return "\n".join(f"{t}({', '.join(cols)})" for t, cols in sorted(tables.items()))
