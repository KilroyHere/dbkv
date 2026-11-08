"""DuckDB tools for the W agent (PLAN §2h): list_tables, describe_table, sample_rows, execute_sql.

A port of agent-frozen-v1:harness/agent/tools.py with the same tool interface, tool texts, output
truncation, error classes and "real names" hint; only the backend changes from SQLite to DuckDB.
Every call opens a read-only connection with the GPU-job caps (PLAN §4a: memory_limit 16GB, threads 8),
enforces a wall-clock timeout with con.interrupt() from a timer thread, and returns
(text_for_the_model, info) where info has rows, runtime_s and an error class.
"""
import re, threading, time

import duckdb

TIMEOUT_S = 60.0
MAX_ROWS = 40
MAX_CHARS = 3000
MEMORY_LIMIT = "16GB"
THREADS = 8

# Same names, descriptions and parameters as the frozen agent (the texts say SQLite there; kept verbatim).
TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "list_tables", "description": "List the tables in the database.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "describe_table", "description": "Show a table's columns and types.",
        "parameters": {"type": "object", "properties": {"table": {"type": "string"}}, "required": ["table"]}}},
    {"type": "function", "function": {
        "name": "sample_rows", "description": "Show a few rows of a table.",
        "parameters": {"type": "object", "properties": {"table": {"type": "string"},
                                                         "n": {"type": "integer", "description": "rows (default 3, max 10)"}},
                       "required": ["table"]}}},
    {"type": "function", "function": {
        "name": "execute_sql", "description": "Run a read-only SQLite query and return its result (first 40 rows).",
        "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}}},
]
EXPLORE = {"list_tables", "describe_table", "sample_rows"}

LIST_SQL = "SELECT table_name AS name FROM duckdb_tables() WHERE NOT internal ORDER BY table_name"


def connect(db_path):
    con = duckdb.connect(db_path, read_only=True)
    con.execute(f"SET memory_limit='{MEMORY_LIMIT}'")
    con.execute(f"SET threads={THREADS}")
    return con


def classify(e):
    """Map a DuckDB exception onto the frozen agent's error classes."""
    msg = str(e)
    if isinstance(e, duckdb.InterruptException) or "INTERRUPT" in msg.upper():
        return "timeout"
    if isinstance(e, duckdb.ParserException):
        return "syntax"
    if isinstance(e, duckdb.CatalogException) and re.search(r"Table with name .* does not exist", msg):
        return "no_such_table"
    if isinstance(e, duckdb.BinderException) and re.search(
            r"Referenced column .* not found|Referenced table .* not found|does not have a column named"
            r"|Table .* does not have a column", msg):
        return "no_such_column"  # SQLite reports an unknown alias in t.col as "no such column: t.col" too
    if isinstance(e, duckdb.Error):
        return "operational"
    return type(e).__name__


def run_query(db_path, sql, timeout=TIMEOUT_S, max_rows=None):
    """Returns (columns, rows, runtime_s, error_class, error_msg)."""
    t = time.monotonic()
    try:
        con = connect(db_path)
    except Exception as e:  # noqa: BLE001
        return [], [], time.monotonic() - t, classify(e), str(e)
    timer = threading.Timer(timeout, con.interrupt)
    timer.daemon = True
    timer.start()
    t = time.monotonic()
    try:
        cur = con.execute(sql)
        rows = cur.fetchall() if max_rows is None else cur.fetchmany(max_rows + 1)
        cols = [d[0] for d in (cur.description or [])]
        return cols, rows, time.monotonic() - t, None, None
    except Exception as e:  # noqa: BLE001
        return [], [], time.monotonic() - t, classify(e), str(e)
    finally:
        timer.cancel()
        con.close()


def fmt(cols, rows, limit=MAX_ROWS):
    lines = [" | ".join(cols)] if cols else []
    for r in rows[:limit]:
        lines.append(" | ".join("NULL" if v is None else str(v)[:80] for v in r))
    if len(rows) > limit:
        lines.append(f"... (more than {limit} rows)")
    out = "\n".join(lines) if lines else "(no rows)"
    return out[:MAX_CHARS] + ("\n...(truncated)" if len(out) > MAX_CHARS else "")


def quote(name):
    return '"' + str(name).replace('"', '""') + '"'


def literal(s):
    return "'" + str(s).replace("'", "''") + "'"


def tables_of(db_path):
    return [r[0] for r in run_query(db_path, LIST_SQL)[1]]


def columns_of(db_path, table):
    return [r[0] for r in run_query(db_path, describe_sql(table))[1]]


def describe_sql(table):
    # Case-insensitive like SQLite's PRAGMA table_info.
    return ("SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_schema = 'main' AND lower(table_name) = lower({literal(table)}) ORDER BY ordinal_position")


def constraints(db_path, table):
    """(primary-key columns, [(column, referenced_table, referenced_column)]) from duckdb_constraints()."""
    rows = run_query(db_path, "SELECT constraint_type, constraint_column_names, referenced_table, "
                              "referenced_column_names FROM duckdb_constraints() "
                              f"WHERE lower(table_name) = lower({literal(table)})")[1]
    pk, fks = set(), []
    for ctype, cols, rtab, rcols in rows:
        if ctype == "PRIMARY KEY":
            pk |= {c.lower() for c in cols or []}
        elif ctype == "FOREIGN KEY":
            fks += [(c, rtab, rc) for c, rc in zip(cols or [], rcols or [])]
    return pk, fks


def name_help(db_path, sql, err):
    """For invented names: list the real tables, or the real columns of the tables the query uses."""
    tabs = tables_of(db_path)
    if err == "no_such_table":
        return "Available tables: " + ", ".join(tabs)
    used = []
    try:
        import sqlglot
        from sqlglot import exp
        used = [t.name for t in sqlglot.parse_one(sql, read="duckdb").find_all(exp.Table) if t.name]
    except Exception:  # noqa: BLE001
        pass
    low = {t.lower(): t for t in tabs}
    used = [low[u.lower()] for u in used if u.lower() in low] or tabs
    parts = [f"{t}({', '.join(columns_of(db_path, t))})" for t in dict.fromkeys(used)]
    return ("Columns of the tables in your query: " + "; ".join(parts))[:1500]


def call(db_path, name, args):
    """Execute a tool. Returns (text, info)."""
    sql = None
    if name == "list_tables":
        sql = LIST_SQL
    elif name == "describe_table":
        sql = describe_sql(args.get("table", ""))
    elif name == "sample_rows":
        n = max(1, min(10, int(args.get("n") or 3)))
        sql = f"SELECT * FROM {quote(args.get('table', ''))} LIMIT {n}"
    elif name == "execute_sql":
        sql = str(args.get("sql", ""))
    else:
        return f"Error: unknown tool {name}", dict(sql=None, runtime_s=0.0, error="unknown_tool", rows=0)
    cols, rows, rt, err, msg = run_query(db_path, sql, max_rows=MAX_ROWS)
    if err:
        hint = ""
        if err in ("no_such_column", "no_such_table"):
            hint = "\n" + name_help(db_path, sql, err)
        return f"Error ({err}): {msg}{hint}", dict(sql=sql, runtime_s=rt, error=err, rows=0)
    if name == "describe_table":
        if not rows:
            return f"Error: no such table {args.get('table')}", dict(sql=sql, runtime_s=rt, error="no_such_table", rows=0)
        # No column descriptions: TPC-DS has no BIRD-style description CSVs.
        pk, fks = constraints(db_path, str(args.get("table", "")))
        text = "\n".join(f"{r[0]} {r[1]}{' PRIMARY KEY' if r[0].lower() in pk else ''}" for r in rows)
        if fks:
            text += "\nForeign keys: " + ", ".join(f"{c} -> {t}.{rc}" for c, t, rc in fks)
    else:
        text = fmt(cols, rows)
    return text, dict(sql=sql, runtime_s=rt, error=None, rows=len(rows))


SQL_BLOCK = re.compile(r"```sql\s*(.+?)```", re.S | re.I)
