"""Database manager for JARVIS Desktop Assistant.

Handles SQLite storage for contacts, custom application paths,
and command execution history.
"""

from __future__ import annotations

import datetime
import os
import sqlite3
from typing import Any

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jarvis.db")


def get_db_path(custom_path: str | None = None) -> str:
    """Resolve database path from argument or default."""
    return custom_path if custom_path is not None else DEFAULT_DB_PATH


def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    """Create a connection with row factory enabled, auto-creating schema if needed."""
    path = get_db_path(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | None = None) -> None:
    """Initialize database schema if tables do not exist."""
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS app_paths (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            path TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS command_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            query TEXT NOT NULL,
            response TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def ensure_db(db_path: str | None = None) -> None:
    """Convenience helper to guarantee schema exists."""
    init_db(db_path)


def find_contact_number(name: str, db_path: str | None = None) -> str | None:
    """Look up contact phone number by name (case-insensitive substring match)."""
    if not name or not name.strip():
        return None
    ensure_db(db_path)
    conn = get_conn(db_path)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT phone FROM contacts WHERE lower(name) LIKE ? ORDER BY length(name) ASC LIMIT 1",
            (f"%{name.lower().strip()}%",),
        )
        row = cur.fetchone()
        return row["phone"] if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def add_contact(name: str, phone: str, email: str = "", db_path: str | None = None) -> int:
    """Insert a new contact into the database."""
    ensure_db(db_path)
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO contacts (name, phone, email) VALUES (?, ?, ?)",
        (name.strip(), phone.strip(), email.strip()),
    )
    conn.commit()
    inserted_id = cur.lastrowid or 0
    conn.close()
    return inserted_id


def get_all_contacts(db_path: str | None = None) -> list[dict[str, Any]]:
    """Fetch all contacts ordered by name."""
    ensure_db(db_path)
    conn = get_conn(db_path)
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, name, phone, email FROM contacts ORDER BY name ASC")
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def get_app_path(name: str, db_path: str | None = None) -> str | None:
    """Look up registered application executable path by app name."""
    if not name or not name.strip():
        return None
    ensure_db(db_path)
    conn = get_conn(db_path)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT path FROM app_paths WHERE lower(name) = ? LIMIT 1",
            (name.lower().strip(),),
        )
        row = cur.fetchone()
        return row["path"] if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def register_app_path(name: str, path: str, db_path: str | None = None) -> bool:
    """Register or update an application path."""
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO app_paths (name, path) VALUES (?, ?)
        ON CONFLICT(name) DO UPDATE SET path = excluded.path
        """,
        (name.lower().strip(), path.strip()),
    )
    conn.commit()
    conn.close()
    return True


def get_all_app_paths(db_path: str | None = None) -> list[dict[str, Any]]:
    """List all registered custom application paths."""
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, name, path FROM app_paths ORDER BY name ASC")
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def log_command(query: str, response: str, db_path: str | None = None) -> int:
    """Log user query and Jarvis response to history table."""
    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO command_history (ts, query, response) VALUES (?, ?, ?)",
        (now_iso, query.strip(), response.strip()),
    )
    conn.commit()
    inserted_id = cur.lastrowid or 0
    conn.close()
    return inserted_id


def get_recent_history(limit: int = 50, db_path: str | None = None) -> list[dict[str, Any]]:
    """Retrieve recent command history records (newest first)."""
    conn = get_conn(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, ts, query, response FROM command_history ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]
