import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional

from werkzeug.security import generate_password_hash, check_password_hash


DEFAULT_DB_FILENAME = "NEXUSRDR_local.db"


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def init_local_db(db_path: str | Path) -> Path:
    """Create local SQLite database (if missing) with base login table."""
    db_path = Path(db_path or DEFAULT_DB_FILENAME)
    conn = get_connection(db_path)

    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS login_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                succeeded INTEGER NOT NULL,
                message TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )

    conn.close()
    return db_path


def seed_user(db_path: str | Path, email: str, password: str, *, overwrite: bool = False) -> None:
    if not email or not password:
        return

    conn = get_connection(db_path)
    password_hash = generate_password_hash(password)
    created_at = datetime.utcnow().isoformat()

    with conn:
        if overwrite:
            conn.execute(
                """
                INSERT INTO users (email, password_hash, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    password_hash=excluded.password_hash,
                    created_at=excluded.created_at
                """,
                (email, password_hash, created_at),
            )
        else:
            conn.execute(
                """
                INSERT OR IGNORE INTO users (email, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (email, password_hash, created_at),
            )

    conn.close()


def get_user_by_email(db_path: str | Path, email: str) -> Optional[dict]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, password_hash, created_at FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": row[0],
        "email": row[1],
        "password_hash": row[2],
        "created_at": row[3],
    }


def verify_user_credentials(db_path: str | Path, email: str, password: str) -> bool:
    user = get_user_by_email(db_path, email)
    if not user:
        return False
    return check_password_hash(user["password_hash"], password)


def log_login_attempt(db_path: str | Path, email: str, succeeded: bool, message: str | None = None) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO login_audit (email, succeeded, message, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (email, int(bool(succeeded)), message, datetime.utcnow().isoformat()),
        )
    conn.close()
