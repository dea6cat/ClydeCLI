import sqlite3
import tempfile
from pathlib import Path

from src.tool_system.tools.data import _sqlite_ro


def _make_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()


def test_encoded_dotdot_filename_does_not_escape_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ws = root / "ws"
        ws.mkdir()
        _make_db(root / "outside.db")
        decoy = ws / "..%2Foutside.db"
        decoy.write_bytes(b"")
        con = _sqlite_ro(decoy)
        try:
            tables = con.execute("SELECT name FROM sqlite_master").fetchall()
        except sqlite3.DatabaseError:
            tables = []
        finally:
            con.close()
        assert tables == []


def test_normal_db_opens_read_only():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "a b#c?.db"
        _make_db(db)
        con = _sqlite_ro(db)
        try:
            assert con.execute("SELECT x FROM t").fetchall() == [(1,)]
            try:
                con.execute("INSERT INTO t VALUES (2)")
                raise AssertionError("write allowed")
            except sqlite3.DatabaseError:
                pass
        finally:
            con.close()
