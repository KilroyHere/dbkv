"""SQLite tools for the BIRD ReAct agent: list_tables, describe_table, sample_rows, execute_sql.

Every call opens a read-only connection, enforces a wall-clock timeout via a progress handler, and
returns (text_for_the_model, info) where info has rows, runtime_s and an error class.
"""
import csv, functools, os, re, sqlite3, time

TIMEOUT_S = 60.0
MAX_ROWS = 40
MAX_CHARS = 3000

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


def connect(db_path):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
    con.text_factory = lambda b: b.decode("utf-8", errors="replace")
    return con


def run_query(db_path, sql, timeout=TIMEOUT_S, max_rows=None):
    """Returns (columns, rows, runtime_s, error_class, error_msg)."""
    con = connect(db_path)
    deadline = time.monotonic() + timeout
    con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)
    t = time.monotonic()
    try:
        cur = con.execute(sql)
        rows = cur.fetchall() if max_rows is None else cur.fetchmany(max_rows + 1)
        cols = [d[0] for d in (cur.description or [])]
        return cols, rows, time.monotonic() - t, None, None
    except sqlite3.OperationalError as e:
        msg = str(e)
        cls = "timeout" if "interrupted" in msg else ("no_such_column" if "no such column" in msg else
              ("no_such_table" if "no such table" in msg else ("syntax" if "syntax error" in msg else "operational")))
        return [], [], time.monotonic() - t, cls, msg
    except Exception as e:  # noqa: BLE001
        return [], [], time.monotonic() - t, type(e).__name__, str(e)
    finally:
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


@functools.lru_cache(maxsize=None)
def descriptions(db_path):
    """BIRD database_description/*.csv -> {table_lower: {column_lower: text}} (empty if absent)."""
    d = os.path.join(os.path.dirname(db_path), "database_description")
    out = {}
    if not os.path.isdir(d):
        return out
    for f in os.listdir(d):
        if not f.lower().endswith(".csv"):
            continue
        cols = {}
        try:
            with open(os.path.join(d, f), encoding="utf-8-sig", errors="replace", newline="") as fh:
                for r in csv.DictReader(fh):
                    name = (r.get("original_column_name") or "").strip()
                    if not name:
                        continue
                    desc = " ".join((r.get("column_description") or "").split())
                    if desc.lower() == name.lower():
                        desc = ""
                    vals = " ".join((r.get("value_description") or "").replace("commonsense evidence:", "").split())
                    text = desc + (f" (values: {vals[:150]})" if vals else "")
                    cols[name.lower()] = text.strip()
        except (OSError, csv.Error):
            continue
        out[os.path.splitext(f)[0].lower()] = cols
    return out


def tables_of(db_path):
    con = connect(db_path)
    try:
        return [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    finally:
        con.close()


def columns_of(db_path, table):
    con = connect(db_path)
    try:
        return [r[1] for r in con.execute(f"PRAGMA table_info({quote(table)})")]
    finally:
        con.close()


def name_help(db_path, sql, err):
    """For invented names: list the real tables, or the real columns of the tables the query uses."""
    tabs = tables_of(db_path)
    if err == "no_such_table":
        return "Available tables: " + ", ".join(tabs)
    used = []
    try:
        import sqlglot
        from sqlglot import exp
        used = [t.name for t in sqlglot.parse_one(sql, read="sqlite").find_all(exp.Table) if t.name]
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
        sql = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    elif name == "describe_table":
        sql = f"PRAGMA table_info({quote(args.get('table', ''))})"
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
        desc = descriptions(db_path).get(str(args.get("table", "")).lower(), {})
        text = "\n".join(f"{r[1]} {r[2]}{' PRIMARY KEY' if r[5] else ''}"
                         + (f" -- {desc[r[1].lower()]}" if desc.get(r[1].lower()) else "") for r in rows)
        fks = run_query(db_path, f"PRAGMA foreign_key_list({quote(args.get('table', ''))})")[1]
        if fks:
            text += "\nForeign keys: " + ", ".join(f"{f[3]} -> {f[2]}.{f[4]}" for f in fks)
    else:
        text = fmt(cols, rows)
    return text, dict(sql=sql, runtime_s=rt, error=None, rows=len(rows))


def schema(db_path, tables=None, columns=None, samples=3):
    """Text schema brief: every (or the given) table's columns with types and `samples` example values."""
    con = connect(db_path)
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        if tables is not None:
            low = {t.lower() for t in tables}
            names = [n for n in names if n.lower() in low]
        out = []
        for t in names:
            cols = con.execute(f"PRAGMA table_info({quote(t)})").fetchall()
            keep = [c for c in cols if columns is None or c[1].lower() in columns.get(t.lower(), set())] or cols
            lines = [f"TABLE {t}"]
            for c in keep:
                vals = []
                if samples:
                    try:
                        vals = [str(v[0])[:40] for v in con.execute(
                            f"SELECT DISTINCT {quote(c[1])} FROM {quote(t)} WHERE {quote(c[1])} IS NOT NULL LIMIT {samples}")]
                    except sqlite3.Error:
                        pass
                ex = f"  e.g. {', '.join(vals)}" if vals else ""
                lines.append(f"  {c[1]} {c[2]}{' PRIMARY KEY' if c[5] else ''}{ex}")
            out.append("\n".join(lines))
        return "\n\n".join(out)
    finally:
        con.close()


def gold_tables_columns(db_path, gold_sql):
    """Tables and columns referenced by the gold SQL (sqlglot), mapped onto the real schema."""
    import sqlglot
    from sqlglot import exp
    tree = sqlglot.parse_one(gold_sql, read="sqlite")
    tabs = {t.name.lower() for t in tree.find_all(exp.Table) if t.name}
    cols_named = {c.name.lower() for c in tree.find_all(exp.Column) if c.name}
    con = connect(db_path)
    try:
        cols = {}
        for t in tabs:
            info = con.execute(f"PRAGMA table_info({quote(t)})").fetchall()
            real = {r[1].lower() for r in info}
            keep = real & cols_named
            # also keep keys so joins stay readable
            keep |= {r[1].lower() for r in info if r[5]}
            cols[t] = keep
        return tabs, cols
    finally:
        con.close()


SQL_BLOCK = re.compile(r"```sql\s*(.+?)```", re.S | re.I)
