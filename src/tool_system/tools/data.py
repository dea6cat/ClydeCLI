"""Data: look at data files the way a data engineer would, without leaving the agent loop.

profile  a file's columns and types, row count, nulls, distinct counts, min/max/mean and sample
         rows (CSV, TSV, Parquet, JSON, JSONL), or a SQLite database's tables, columns and counts
query    read-only SQL, across files (`SELECT ... FROM 'sales/*.parquet' JOIN 'customers.csv' USING (id)`)
         or against a SQLite database (`database`)

Files go through DuckDB, sandboxed: reads only inside the workspace (and any extra working
directories; stricter than Read, on purpose, for SQLite files too), no network, no extension installs, and only SELECT-type statements (checked with
DuckDB's own parser; SUMMARIZE, DESCRIBE and WITH count as SELECT), with the settings locked so SQL
can't loosen them. SQLite goes through Python's sqlite3, opened read-only with an authorizer that
refuses anything but reads. Every call has a time limit and a row cap.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError, ToolPermissionError
from ..protocol import ToolResult
from ..registry import ToolSpec

NAME = "Data"
TIMEOUT_S = 60
DEFAULT_ROWS, MAX_ROWS = 50, 1000
_CELL = 200            # characters shown per cell
_SQLITE = {".sqlite", ".sqlite3", ".db"}
_SQLITE_PRAGMAS = {"table_info", "table_list", "index_list", "foreign_key_list"}


def _table(columns: list[str], rows: list[tuple]) -> str:
    """Rows as a pipe table, cells cut to _CELL characters."""
    def cell(v: Any) -> str:
        text = "NULL" if v is None else str(v).replace("\n", " ").replace("|", "\\|")
        return text if len(text) <= _CELL else text[:_CELL - 1] + "…"
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _allowed_dirs(context: ToolContext) -> list[Path]:
    extra = getattr(context.permission_context, "additional_working_directories", ()) or ()
    return [Path(context.workspace_root).resolve(), *(Path(d).resolve() for d in extra)]


def _sandboxed_duckdb(context: ToolContext) -> Any:
    import duckdb

    # ponytail: DuckDB resolves relative paths against the process's working directory (where ClydeCLI
    # started, i.e. the workspace), not the tool context's cwd; after EnterWorktree, use absolute paths.
    con = duckdb.connect(":memory:")
    allowed = [str(d) + "/" for d in _allowed_dirs(context)]
    for setting in ("SET autoinstall_known_extensions=false", "SET autoload_known_extensions=false",
                    f"SET allowed_directories=[{', '.join(_quote(d) for d in allowed)}]",
                    "SET enable_external_access=false", "SET lock_configuration=true"):
        con.execute(setting)
    return con


def _with_timeout(con: Any, work: Any) -> Any:
    """Run work(); interrupt the connection if it takes longer than TIMEOUT_S."""
    timer = threading.Timer(TIMEOUT_S, con.interrupt)
    timer.start()
    try:
        return work()
    finally:
        timer.cancel()


def _duckdb_query(con: Any, sql: str, rows: int) -> tuple[list[str], list[tuple], bool]:
    import duckdb

    try:
        statements = con.extract_statements(sql)
    except duckdb.Error as e:
        raise ToolInputError(f"SQL doesn't parse: {e}") from e
    if not statements:
        raise ToolInputError("no SQL statement given")
    refused = [st.type.name for st in statements if st.type != duckdb.StatementType.SELECT]
    if refused:
        raise ToolInputError(f"only read-only SELECT queries run here (got {', '.join(refused)})")
    for st in statements[:-1]:
        con.execute(st)
    cur = con.execute(statements[-1])
    got = cur.fetchmany(rows + 1)
    return [d[0] for d in cur.description or []], got[:rows], len(got) > rows


def _sqlite_ro(path: Path) -> sqlite3.Connection:
    """A read-only connection whose authorizer refuses anything but reads, with a time limit."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}

    def authorizer(action: int, arg1: Any, arg2: Any, db: Any, source: Any) -> int:
        if action == sqlite3.SQLITE_PRAGMA:
            return sqlite3.SQLITE_OK if arg1 in _SQLITE_PRAGMAS else sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY

    con.set_authorizer(authorizer)
    end = time.monotonic() + TIMEOUT_S
    con.set_progress_handler(lambda: 1 if time.monotonic() > end else 0, 10_000)   # non-zero aborts
    return con


def _more(rows: int, more: bool) -> str:
    return f"\n\n(first {rows} rows; raise max_rows or aggregate for more)" if more else ""


class DataTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=NAME,
            description=(
                "Profile or query data files with read-only SQL (DuckDB). action=profile with a path shows a "
                "file's columns, types, row count, nulls, distinct counts, min/max/mean and sample rows (CSV, TSV, "
                "Parquet, JSON, JSONL), or a SQLite database's tables. action=query runs SELECT SQL; refer to files "
                "by path in FROM (relative to the project root, or absolute, inside the project), globs work "
                "('logs/*.parquet'), and files can be "
                "joined. For a SQLite database pass its path as `database`. Use this instead of reading large data "
                "files with Read."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["profile", "query"]},
                    "path": {"type": "string", "description": "profile: the data file or SQLite database"},
                    "sql": {"type": "string", "description": "query: one or more SELECT statements; the last one's rows are returned"},
                    "database": {"type": "string", "description": "query: a SQLite database to run the SQL against"},
                    "max_rows": {"type": "integer", "description": f"rows to return (default {DEFAULT_ROWS}, at most {MAX_ROWS})"},
                },
                "required": ["action"],
            },
            is_read_only=True,
            max_result_size_chars=200_000,
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = tool_input.get("action")
        rows = tool_input.get("max_rows", DEFAULT_ROWS)
        if not isinstance(rows, int) or not 1 <= rows <= MAX_ROWS:
            raise ToolInputError(f"max_rows must be an integer from 1 to {MAX_ROWS}")
        try:
            if action == "profile":
                path = self._path(tool_input.get("path"), "path", context)
                text = self._profile_sqlite(path) if path.suffix.lower() in _SQLITE else self._profile_file(path, context)
            elif action == "query":
                sql = tool_input.get("sql")
                if not isinstance(sql, str) or not sql.strip():
                    raise ToolInputError("query needs `sql`")
                if tool_input.get("database"):
                    text = self._query_sqlite(self._path(tool_input["database"], "database", context), sql, rows)
                else:
                    text = self._query_files(sql, rows, context)
            else:
                raise ToolInputError("action must be 'profile' or 'query'")
        except (ToolInputError, ToolPermissionError):
            raise   # Clyde's own input and permission handling, as for every tool
        except Exception as e:   # DuckDB / SQLite errors go back to the model as tool errors
            return ToolResult(name=NAME, output={"error": f"{type(e).__name__}: {str(e)[:600]}"}, is_error=True)
        return ToolResult(name=NAME, output=text, content_type="text")

    @staticmethod
    def _path(value: Any, field: str, context: ToolContext) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ToolInputError(f"`{field}` must be a file path")
        path = context.ensure_allowed_path(value)
        if not any(path.is_relative_to(d) for d in _allowed_dirs(context)):
            raise ToolInputError(f"outside the workspace: {path} (the Data tool reads only inside it)")
        if not path.is_file():
            raise ToolInputError(f"not a file: {path}")
        return path

    def _query_files(self, sql: str, rows: int, context: ToolContext) -> str:
        con = _sandboxed_duckdb(context)
        try:
            columns, got, more = _with_timeout(con, lambda: _duckdb_query(con, sql, rows))
        finally:
            con.close()
        return _table(columns, got) + _more(rows, more)

    def _profile_file(self, path: Path, context: ToolContext) -> str:
        con = _sandboxed_duckdb(context)
        source = _quote(str(path))

        def work() -> str:
            count = con.execute(f"SELECT count(*) FROM {source}").fetchone()[0]
            summary = con.execute(f"SUMMARIZE SELECT * FROM {source}")
            cols = [d[0] for d in summary.description]
            keep = [c for c in ("column_name", "column_type", "null_percentage", "approx_unique", "min", "max", "avg") if c in cols]
            stats = [tuple(row[cols.index(c)] for c in keep) for row in summary.fetchall()]
            sample = con.execute(f"SELECT * FROM {source} LIMIT 5")
            sample_cols = [d[0] for d in sample.description]
            return (f"{path.name}: {count:,} rows, {len(stats)} columns\n\n" + _table(keep, stats)
                    + "\n\nSample rows:\n\n" + _table(sample_cols, sample.fetchall()))
        try:
            return _with_timeout(con, work)
        finally:
            con.close()

    def _profile_sqlite(self, path: Path) -> str:
        con = _sqlite_ro(path)
        try:
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            parts = [f"{path.name}: SQLite, {len(tables)} table(s)"]
            for t in tables:
                quoted = '"' + t.replace('"', '""') + '"'
                count = con.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]
                cols = con.execute(f"PRAGMA table_info({quoted})").fetchall()
                parts.append(f"\n{t} ({count:,} rows)\n" + _table(["column", "type", "not null", "primary key"],
                                                                  [(c[1], c[2], bool(c[3]), bool(c[5])) for c in cols]))
            return "\n".join(parts)
        finally:
            con.close()

    def _query_sqlite(self, path: Path, sql: str, rows: int) -> str:
        con = _sqlite_ro(path)
        try:
            cur = con.execute(sql)
            got = cur.fetchmany(rows + 1)
            columns = [d[0] for d in cur.description or []]
        except sqlite3.DatabaseError as e:
            if "not authorized" in str(e):
                raise ToolInputError("only read-only queries run here") from e
            raise
        finally:
            con.close()
        return _table(columns, got[:rows]) + _more(rows, len(got) > rows)
