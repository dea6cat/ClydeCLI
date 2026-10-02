"""Data tool: profiling and read-only SQL over files (DuckDB) and SQLite, and everything it must refuse."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import duckdb

from src.tool_system.context import ToolContext
from src.tool_system.errors import ToolInputError, ToolPermissionError
from src.tool_system.tools.data import DataTool


class TestDataTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.ws = base / "ws"
        (self.ws / "logs").mkdir(parents=True)
        (self.ws / "sales.csv").write_text("id,name,amount\n1,ann,10.5\n2,bob,\n3,cy,7\n")
        (self.ws / "tiers.jsonl").write_text('{"id":1,"tier":"gold"}\n{"id":3,"tier":"silver"}\n')
        for day, n in (("01", 2), ("02", 3)):
            duckdb.sql(f"COPY (SELECT range AS v FROM range({n})) TO '{self.ws}/logs/{day}.parquet' (FORMAT parquet)")
        (base / "outside.csv").write_text("secret\n42\n")
        self.outside = base / "outside.csv"
        db = sqlite3.connect(self.ws / "app.db")
        db.executescript("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL);"
                         "INSERT INTO users (email) VALUES ('a@x.io'), ('b@x.io');")
        db.commit()
        db.close()
        self.ctx = ToolContext(workspace_root=self.ws)
        self.tool = DataTool()
        self._cwd = os.getcwd()
        os.chdir(self.ws)   # ClydeCLI runs from the workspace; relative paths resolve there

    def tearDown(self):
        os.chdir(self._cwd)
        self.tmp.cleanup()

    def run_tool(self, **kwargs):
        return self.tool.run(kwargs, self.ctx)

    def test_profile_shows_shape_types_nulls_and_samples(self):
        out = self.run_tool(action="profile", path="sales.csv").output
        self.assertIn("sales.csv: 3 rows, 3 columns", out)
        self.assertIn("| amount | DOUBLE | 33.33", out)    # one of three amounts is missing
        self.assertIn("Sample rows:", out)
        self.assertIn("| 1 | ann | 10.5 |", out)

    def test_query_joins_files_by_relative_path(self):
        out = self.run_tool(action="query", sql="SELECT s.name, t.tier FROM 'sales.csv' s "
                                                "JOIN read_json_auto('tiers.jsonl') t USING (id) ORDER BY s.id").output
        self.assertEqual(out.splitlines()[2:], ["| ann | gold |", "| cy | silver |"])

    def test_parquet_globs_and_row_cap(self):
        self.assertIn("| 5 |", self.run_tool(action="query", sql="SELECT count(*) AS n FROM 'logs/*.parquet'").output)
        capped = self.run_tool(action="query", sql="SELECT * FROM 'logs/*.parquet'", max_rows=2).output
        self.assertIn("(first 2 rows; raise max_rows or aggregate for more)", capped)

    def test_anything_but_select_is_refused(self):
        for sql in (f"COPY (SELECT 1) TO '{self.ws}/out.csv'", "CREATE TABLE t AS SELECT 1", "ATTACH 'app.db'",
                    "INSTALL httpfs", "SET enable_external_access=true", "SELECT 1; DROP TABLE x"):
            with self.subTest(sql=sql), self.assertRaisesRegex(ToolInputError, "only read-only SELECT|doesn't parse"):
                self.run_tool(action="query", sql=sql)
        self.assertFalse((self.ws / "out.csv").exists())

    def test_files_outside_the_workspace_and_the_network_are_out_of_reach(self):
        result = self.run_tool(action="query", sql=f"SELECT * FROM '{self.outside}'")
        self.assertTrue(result.is_error)
        self.assertIn("Permission", result.output["error"])
        self.assertTrue(self.run_tool(action="query", sql="SELECT * FROM 'https://example.com/x.csv'").is_error)
        self.assertTrue(self.run_tool(action="query", sql="SELECT * FROM '../outside.csv'").is_error)
        for kwargs in ({"action": "profile", "path": str(self.outside)},
                       {"action": "query", "database": "../outside.csv", "sql": "SELECT 1"}):
            with self.subTest(**kwargs), self.assertRaisesRegex((ToolInputError, ToolPermissionError), "outside"):
                self.run_tool(**kwargs)

    def test_sqlite_profile_and_read_only_query(self):
        profile = self.run_tool(action="profile", path="app.db").output
        self.assertIn("users (2 rows)", profile)
        self.assertIn("| email | TEXT | True | False |", profile)
        out = self.run_tool(action="query", database="app.db", sql="SELECT email FROM users ORDER BY id").output
        self.assertIn("| a@x.io |", out)
        for sql in ("DELETE FROM users", "UPDATE users SET email = 'x'", "DROP TABLE users", "ATTACH 'other.db' AS o",
                    "PRAGMA writable_schema = 1"):
            with self.subTest(sql=sql), self.assertRaises((ToolInputError, sqlite3.DatabaseError)):
                self.run_tool(action="query", database="app.db", sql=sql)
        self.assertIn("| 2 |", self.run_tool(action="query", database="app.db", sql="SELECT count(*) FROM users").output)

    def test_bad_input_is_explained(self):
        with self.assertRaisesRegex(ToolInputError, "query needs `sql`"):
            self.run_tool(action="query")
        with self.assertRaisesRegex(ToolInputError, "max_rows"):
            self.run_tool(action="query", sql="SELECT 1", max_rows=0)
        with self.assertRaisesRegex(ToolInputError, "not a file"):
            self.run_tool(action="profile", path="logs")


if __name__ == "__main__":
    unittest.main()
