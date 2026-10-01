"""SQLite-backed chunk store. Vectors live in a BLOB column.

Level-1 knowledge is small (hundreds to a few thousand chunks), so a brute
force scan in NumPy is faster than any index and needs no extra service.
"""

import json
import sqlite3
from array import array
from typing import Iterable

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id       INTEGER PRIMARY KEY,
    source   TEXT NOT NULL,
    heading  TEXT NOT NULL DEFAULT '',
    text     TEXT NOT NULL,
    aliases  TEXT NOT NULL DEFAULT '', -- the `also:` line, kept verbatim
    tokens   TEXT NOT NULL,           -- pre-tokenised, JSON list, for BM25
    vector   BLOB,                    -- float32, unit length, NULL if none
    dim      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns an older index predates.

    `CREATE TABLE IF NOT EXISTS` leaves an existing table alone, so a database
    written before a column existed would fail every read against it. Adding
    them here means an upgrade never needs the store deleted by hand.
    """
    have = {row["name"] for row in conn.execute("PRAGMA table_info(chunks)")}
    for column, ddl in (("aliases", "TEXT NOT NULL DEFAULT ''"),):
        if column not in have:
            with conn:
                conn.execute(f"ALTER TABLE chunks ADD COLUMN {column} {ddl}")


def pack(vector) -> bytes:
    return array("f", vector).tobytes()


def unpack(blob: bytes) -> array:
    out = array("f")
    out.frombytes(blob)
    return out


def replace_all(conn: sqlite3.Connection, rows: Iterable[dict]) -> int:
    """Wipe and rewrite the index in one transaction."""
    with conn:
        conn.execute("DELETE FROM chunks")
        count = 0
        for row in rows:
            conn.execute(
                "INSERT INTO chunks"
                " (source, heading, text, aliases, tokens, vector, dim)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    row["source"],
                    row.get("heading", ""),
                    row["text"],
                    row.get("aliases", ""),
                    json.dumps(row["tokens"]),
                    pack(row["vector"]) if row.get("vector") is not None else None,
                    len(row["vector"]) if row.get("vector") is not None else 0,
                ),
            )
            count += 1
    return count


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def load_all(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, source, heading, text, aliases, tokens, vector, dim FROM chunks"
    ).fetchall()
    return [
        {
            "id": r["id"],
            "source": r["source"],
            "heading": r["heading"],
            "text": r["text"],
            "aliases": r["aliases"],
            "tokens": json.loads(r["tokens"]),
            "vector": list(unpack(r["vector"])) if r["vector"] else None,
        }
        for r in rows
    ]


def count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
