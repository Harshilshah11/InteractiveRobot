"""Build the index: data/ -> chunks -> tokens + vectors -> SQLite.

Run directly:  python -m app.ingest
or hit POST /api/reindex while the server is running.
"""

from __future__ import annotations

import time

from . import embedder, store
from .config import DATA_DIR
from .text import load_documents, tokenize


def data_mtime() -> float:
    """Newest modification time across the knowledge files."""
    latest = 0.0
    if DATA_DIR.exists():
        for path in DATA_DIR.rglob("*"):
            if path.suffix.lower() in {".md", ".txt", ".json"}:
                latest = max(latest, path.stat().st_mtime)
    return latest


def is_stale() -> bool:
    """True when data/ has changed since the index was written."""
    conn = store.connect()
    try:
        if store.count(conn) == 0:
            return True
        built_at = float(store.get_meta(conn, "built_at", "0") or 0)
    finally:
        conn.close()
    return data_mtime() > built_at


def build() -> dict:
    started = time.time()
    # Snapshot before reading: anything edited mid-build then has a newer
    # mtime than the stamp, so the next start rebuilds instead of missing it.
    snapshot = data_mtime()
    chunks = load_documents(DATA_DIR)

    if not chunks:
        conn = store.connect()
        store.replace_all(conn, [])
        conn.close()
        return {
            "chunks": 0,
            "embeddings": "none",
            "seconds": 0.0,
            "warning": f"No .md / .txt / .json files found in {DATA_DIR}",
        }

    # Heading and aliases are indexed *and* embedded alongside the body, so
    # "working hours" matches a chunk whose body only says "9 AM to 6 PM".
    # They stay out of `text`, which is the only field the answer is read from.
    searchable = [
        " ".join(
            part
            for part in (c["heading"], c.get("aliases", ""), c["text"])
            if part
        )
        for c in chunks
    ]
    vectors = embedder.embed(searchable)

    rows = []
    for i, chunk in enumerate(chunks):
        rows.append(
            {
                "source": chunk["source"],
                "heading": chunk["heading"],
                "text": chunk["text"],
                "aliases": chunk.get("aliases", ""),
                "tokens": tokenize(searchable[i]),
                "vector": vectors[i] if vectors else None,
            }
        )

    conn = store.connect()
    written = store.replace_all(conn, rows)
    store.set_meta(conn, "embedder", embedder.status())
    store.set_meta(conn, "built_at", repr(snapshot))
    conn.close()

    return {
        "chunks": written,
        "embeddings": embedder.status(),
        "seconds": round(time.time() - started, 2),
    }


if __name__ == "__main__":
    result = build()
    print(
        f"Indexed {result['chunks']} chunks in {result.get('seconds', 0)}s "
        f"(embeddings: {result['embeddings']})"
    )
    if result.get("warning"):
        print("!", result["warning"])
