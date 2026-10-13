"""The Data tool must not be a way around the secret-read ask."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.tool_system.context import ToolContext
from src.tool_system.errors import ToolInputError
from src.tool_system.tools.data import DataTool

try:
    import duckdb  # noqa: F401
except ImportError:  # pragma: no cover
    duckdb = None


@unittest.skipIf(duckdb is None, "duckdb is not installed")
class TestDataSecrets(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        (self.root / "sales.csv").write_text("id,amount\n1,10\n2,20\n")
        (self.root / ".env").write_text("TOKEN=CANARY-env\n")
        (self.root / "deploy.pem").write_text("CANARY-pem\n")
        (self.root / "notes.txt").write_text("hello\n")
        self.ctx = ToolContext(workspace_root=self.root, cwd=self.root)

    def _query(self, sql):
        return DataTool().run({"action": "query", "sql": sql}, self.ctx)

    def test_a_normal_query_still_works(self):
        out = self._query(f"SELECT sum(amount) AS total FROM '{self.root}/sales.csv'").output
        self.assertIn("30", out)

    def test_sql_that_names_a_secret_file_is_refused(self):
        for sql in ("SELECT * FROM read_text('.env')", "SELECT * FROM '.env'", "SELECT * FROM read_csv('deploy.pem', delim='|')",
                    f"SELECT * FROM read_text('{self.root}/.env')", 'SELECT * FROM read_text(".env")'):
            with self.assertRaises(ToolInputError, msg=sql):
                self._query(sql)

    def test_globs_that_reach_a_secret_file_are_refused(self):
        with self.assertRaises(ToolInputError):
            self._query("SELECT * FROM read_text('*.pem')")
        with self.assertRaises(ToolInputError):
            self._query("SELECT * FROM read_text('.e*')")

    def test_building_the_path_at_run_time_is_refused_rather_than_trusted(self):
        with self.assertRaises(ToolInputError):
            self._query("SELECT * FROM read_text('.e' || 'nv')")

    def test_profile_and_sqlite_paths_that_are_secrets_are_refused(self):
        with self.assertRaises(ToolInputError):
            DataTool().run({"action": "profile", "path": ".env"}, self.ctx)
        (self.root / "id_rsa.db").write_text("x")
        with self.assertRaises(ToolInputError):
            DataTool().run({"action": "query", "database": "id_rsa.db", "sql": "select 1"}, self.ctx)


if __name__ == "__main__":
    unittest.main()
