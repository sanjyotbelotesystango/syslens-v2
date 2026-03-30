"""
frontend/db_logger.py — SQLite query analytics logger.

Mirrors the db_logger pattern from the reference app.
Tracks every query: mode, provider, duration, visual count, success.
Used by the sidebar Query Analytics panel.
"""

import sqlite3
import time
from pathlib import Path

_DB_PATH = Path(__file__).parent / "syslens_analytics.db"


def init_db() -> None:
    """Create the analytics table if it doesn't exist."""
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS queries (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                ts               REAL    NOT NULL,
                question         TEXT    NOT NULL,
                mode             TEXT    NOT NULL,
                provider         TEXT    NOT NULL DEFAULT '',
                model            TEXT    NOT NULL DEFAULT '',
                success          INTEGER NOT NULL DEFAULT 1,
                summary          TEXT    NOT NULL DEFAULT '',
                error_message    TEXT    NOT NULL DEFAULT '',
                duration_seconds REAL    NOT NULL DEFAULT 0,
                visual_count     INTEGER NOT NULL DEFAULT 0,
                kpi_count        INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()


def log_query(
    question: str,
    mode: str,
    provider: str = "",
    model: str = "",
    success: bool = True,
    summary: str = "",
    error_message: str = "",
    duration_seconds: float = 0.0,
    visual_count: int = 0,
    kpi_count: int = 0,
) -> None:
    """Insert one query record. Silent on failure — never crash the UI."""
    try:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute(
                """INSERT INTO queries
                   (ts, question, mode, provider, model, success, summary,
                    error_message, duration_seconds, visual_count, kpi_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    time.time(), question[:500], mode, provider, model,
                    int(success), summary[:300], error_message[:300],
                    round(duration_seconds, 3), visual_count, kpi_count,
                ),
            )
            conn.commit()
    except Exception:
        pass


def get_stats() -> dict:
    """Return aggregate statistics for the sidebar panel."""
    try:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT
                    COUNT(*)                                   AS queries,
                    SUM(visual_count)                          AS visuals,
                    SUM(kpi_count)                             AS kpis,
                    ROUND(AVG(duration_seconds), 2)            AS avg_duration,
                    ROUND(100.0 * SUM(success) / COUNT(*), 1) AS success_rate
                FROM queries
            """).fetchone()
            return dict(row) if row else {}
    except Exception:
        return {}


def get_recent(n: int = 5) -> list[dict]:
    """Return the N most recent query rows for the sidebar history list."""
    try:
        with sqlite3.connect(_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT question, mode, duration_seconds, visual_count, kpi_count, success
                   FROM queries ORDER BY ts DESC LIMIT ?""",
                (n,),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []