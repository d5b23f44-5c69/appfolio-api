"""SQLite storage for scraped listings and mirrored image metadata."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Iterable, Iterator

from .config import DB_PATH, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    site_key       TEXT NOT NULL,
    listable_uid   TEXT NOT NULL,
    data           TEXT NOT NULL,
    fetched_at     REAL NOT NULL,
    active         INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (site_key, listable_uid)
);

CREATE TABLE IF NOT EXISTS images (
    source_url     TEXT PRIMARY KEY,
    listable_uid   TEXT NOT NULL,
    local_path     TEXT NOT NULL,
    downloaded_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    site_key       TEXT PRIMARY KEY,
    last_run_at    REAL NOT NULL,
    last_status    TEXT NOT NULL,
    last_count     INTEGER NOT NULL DEFAULT 0,
    last_error     TEXT
);
"""


def init() -> None:
    ensure_dirs()
    with connect() as c:
        c.executescript(SCHEMA)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_listings(site_key: str, listings: Iterable[dict]) -> int:
    now = time.time()
    seen: list[str] = []
    with connect() as c:
        for listing in listings:
            uid = listing["listable_uid"]
            seen.append(uid)
            c.execute(
                """INSERT INTO listings (site_key, listable_uid, data, fetched_at, active)
                   VALUES (?, ?, ?, ?, 1)
                   ON CONFLICT(site_key, listable_uid) DO UPDATE SET
                     data=excluded.data, fetched_at=excluded.fetched_at, active=1""",
                (site_key, uid, json.dumps(listing), now),
            )
        if seen:
            placeholders = ",".join("?" * len(seen))
            c.execute(
                f"UPDATE listings SET active=0 WHERE site_key=? AND listable_uid NOT IN ({placeholders})",
                (site_key, *seen),
            )
        else:
            c.execute("UPDATE listings SET active=0 WHERE site_key=?", (site_key,))
    return len(seen)


def get_active_listings(site_key: str) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT data FROM listings WHERE site_key=? AND active=1 ORDER BY fetched_at DESC",
            (site_key,),
        ).fetchall()
    return [json.loads(r["data"]) for r in rows]


def get_listing(site_key: str, listable_uid: str) -> dict | None:
    with connect() as c:
        row = c.execute(
            "SELECT data FROM listings WHERE site_key=? AND listable_uid=?",
            (site_key, listable_uid),
        ).fetchone()
    return json.loads(row["data"]) if row else None


def record_image(source_url: str, listable_uid: str, local_path: str) -> None:
    with connect() as c:
        c.execute(
            """INSERT INTO images (source_url, listable_uid, local_path, downloaded_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(source_url) DO UPDATE SET local_path=excluded.local_path""",
            (source_url, listable_uid, local_path, time.time()),
        )


def get_image_local_path(source_url: str) -> str | None:
    with connect() as c:
        row = c.execute(
            "SELECT local_path FROM images WHERE source_url=?", (source_url,)
        ).fetchone()
    return row["local_path"] if row else None


def record_scrape_run(site_key: str, status: str, count: int, error: str | None = None) -> None:
    with connect() as c:
        c.execute(
            """INSERT INTO scrape_runs (site_key, last_run_at, last_status, last_count, last_error)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(site_key) DO UPDATE SET
                 last_run_at=excluded.last_run_at,
                 last_status=excluded.last_status,
                 last_count=excluded.last_count,
                 last_error=excluded.last_error""",
            (site_key, time.time(), status, count, error),
        )


def get_scrape_runs() -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM scrape_runs").fetchall()
    return [dict(r) for r in rows]
