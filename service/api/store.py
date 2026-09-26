"""Small persistent store for accounts and dispatcher decisions.

SQLite is the single-container default. DATABASE_URL switches both tables to PostgreSQL.
Forecast arrays and the immutable forecast archive remain Parquet files.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import uuid
from pathlib import Path

AUTH_DIR = Path(os.environ.get("AUTH_DIR", "/app/auth"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _connect():
    if DATABASE_URL:
        import psycopg
        return psycopg.connect(DATABASE_URL)
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(AUTH_DIR / "users.db", timeout=10)


def init_db() -> None:
    with _connect() as con:
        binary_type = "BYTEA" if DATABASE_URL else "BLOB"
        con.execute(f"""CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, salt {binary_type}, hash {binary_type}, created_at TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS decisions (
            id TEXT PRIMARY KEY, alert_id TEXT NOT NULL, username TEXT NOT NULL,
            decision TEXT NOT NULL, comment TEXT NOT NULL, alert_date TEXT NOT NULL,
            route INTEGER, created_at TEXT NOT NULL, UNIQUE(alert_id, username))""")
        con.execute("""CREATE TABLE IF NOT EXISTS ingest_batches (
            filename TEXT PRIMARY KEY, username TEXT NOT NULL, kind TEXT NOT NULL,
            rows_count INTEGER NOT NULL, created_at TEXT NOT NULL)""")


init_db()


def get_user(username: str):
    with _connect() as con:
        row = con.execute("SELECT salt, hash FROM users WHERE username=" + ("%s" if DATABASE_URL else "?"), (username,)).fetchone()
    return row


def add_user(username: str, salt: bytes, digest: bytes) -> bool:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    if DATABASE_URL:
        sql = "INSERT INTO users VALUES (%s,%s,%s,%s) ON CONFLICT (username) DO NOTHING"
    else:
        sql = "INSERT OR IGNORE INTO users VALUES (?,?,?,?)"
    with _connect() as con:
        cur = con.execute(sql, (username, salt, digest, now))
        inserted = cur.rowcount > 0
    return inserted


def save_decision(alert_id: str, username: str, decision: str, comment: str,
                  alert_date: str, route: int | None) -> dict:
    ident = uuid.uuid4().hex
    created_at = dt.datetime.now(dt.timezone.utc).isoformat()
    ph = "%s" if DATABASE_URL else "?"
    sql = (f"INSERT INTO decisions VALUES ({','.join([ph] * 8)}) "
           "ON CONFLICT(alert_id, username) DO UPDATE SET decision=excluded.decision, "
           "comment=excluded.comment, created_at=excluded.created_at")
    with _connect() as con:
        con.execute(sql, (ident, alert_id, username, decision, comment, alert_date, route, created_at))
    return {"alert_id": alert_id, "username": username, "decision": decision, "comment": comment,
            "alert_date": alert_date, "route": route, "created_at": created_at}


def list_decisions(username: str | None = None, limit: int = 100) -> list[dict]:
    cols = ["alert_id", "username", "decision", "comment", "alert_date", "route", "created_at"]
    ph = "%s" if DATABASE_URL else "?"
    sql = "SELECT " + ",".join(cols) + " FROM decisions"
    params = []
    if username:
        sql += f" WHERE username={ph}"
        params.append(username)
    sql += f" ORDER BY created_at DESC LIMIT {ph}"
    params.append(limit)
    with _connect() as con:
        rows = con.execute(sql, params).fetchall()
    return [dict(zip(cols, row)) for row in rows]


def log_ingest(filename: str, username: str, kind: str, rows_count: int) -> None:
    ph = "%s" if DATABASE_URL else "?"
    sql = (f"INSERT INTO ingest_batches VALUES ({','.join([ph] * 5)}) "
           "ON CONFLICT(filename) DO NOTHING")
    with _connect() as con:
        con.execute(sql, (filename, username, kind, rows_count, dt.datetime.now(dt.timezone.utc).isoformat()))
