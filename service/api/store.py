"""Хранилище пользователей, журнала решений диспетчера и журнала приёма данных — PostgreSQL (DATABASE_URL).

Прогноз и архив версий прогноза остаются неизменяемыми Parquet-файлами в томе state.
"""
from __future__ import annotations

import datetime as dt
import os
import time
import uuid

import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("не задана переменная DATABASE_URL (PostgreSQL), например postgresql://tram:пароль@db:5432/tram")


def _connect():
    return psycopg.connect(DATABASE_URL)


def init_db(retries: int = 30) -> None:
    for attempt in range(retries):                 # база может ещё стартовать
        try:
            with _connect() as con:
                con.execute("""CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY, salt BYTEA, hash BYTEA, created_at TEXT)""")
                con.execute("""CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY, alert_id TEXT NOT NULL, username TEXT NOT NULL,
                    decision TEXT NOT NULL, comment TEXT NOT NULL, alert_date TEXT NOT NULL,
                    route INTEGER, created_at TEXT NOT NULL, UNIQUE(alert_id, username))""")
                con.execute("""CREATE TABLE IF NOT EXISTS ingest_batches (
                    filename TEXT PRIMARY KEY, username TEXT NOT NULL, kind TEXT NOT NULL,
                    rows_count INTEGER NOT NULL, created_at TEXT NOT NULL)""")
            return
        except psycopg.errors.UniqueViolation:     # таблицу одновременно создал другой воркер
            return
        except psycopg.OperationalError:
            if attempt == retries - 1:
                raise RuntimeError("PostgreSQL недоступен: проверьте DATABASE_URL и что контейнер db запущен") from None
            time.sleep(1)


init_db()


def get_user(username: str):
    with _connect() as con:
        return con.execute("SELECT salt, hash FROM users WHERE username=%s", (username,)).fetchone()


def add_user(username: str, salt: bytes, digest: bytes) -> bool:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with _connect() as con:
        cur = con.execute("INSERT INTO users VALUES (%s,%s,%s,%s) ON CONFLICT (username) DO NOTHING",
                          (username, salt, digest, now))
        return cur.rowcount > 0


def save_decision(alert_id: str, username: str, decision: str, comment: str,
                  alert_date: str, route: int | None) -> dict:
    created_at = dt.datetime.now(dt.timezone.utc).isoformat()
    with _connect() as con:
        con.execute("INSERT INTO decisions VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT(alert_id, username) DO UPDATE SET decision=excluded.decision, "
                    "comment=excluded.comment, created_at=excluded.created_at",
                    (uuid.uuid4().hex, alert_id, username, decision, comment, alert_date, route, created_at))
    return {"alert_id": alert_id, "username": username, "decision": decision, "comment": comment,
            "alert_date": alert_date, "route": route, "created_at": created_at}


def list_decisions(username: str | None = None, limit: int = 100) -> list[dict]:
    cols = ["alert_id", "username", "decision", "comment", "alert_date", "route", "created_at"]
    sql = "SELECT " + ",".join(cols) + " FROM decisions"
    params: list = []
    if username:
        sql += " WHERE username=%s"
        params.append(username)
    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)
    with _connect() as con:
        rows = con.execute(sql, params).fetchall()
    return [dict(zip(cols, row)) for row in rows]


def log_ingest(filename: str, username: str, kind: str, rows_count: int) -> None:
    with _connect() as con:
        con.execute("INSERT INTO ingest_batches VALUES (%s,%s,%s,%s,%s) ON CONFLICT(filename) DO NOTHING",
                    (filename, username, kind, rows_count, dt.datetime.now(dt.timezone.utc).isoformat()))
