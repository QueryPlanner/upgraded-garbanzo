"""Persistent storage for scheduled reminders backed by SQLite via aiosqlite.

A single ``aiosqlite`` connection is opened on the first call to
``initialize()`` and reused for every subsequent operation.  This eliminates
the per-call overhead of opening/closing a connection and removes the need
to offload work to a thread-pool executor.

The database file lives inside the agent data directory, which is mounted
as a Docker named volume (``agent_data``). Named volumes survive
``docker compose up -d`` redeploys, so reminders are never lost during CI/CD.

⚠️  Running ``docker compose down -v`` WILL destroy the volume and all data.
    Use ``docker compose down`` (without -v) to stop without data loss.
"""

import asyncio
import logging
from pathlib import Path

import aiosqlite
from pydantic import BaseModel

from ..utils.app_timezone import now_utc
from ..utils.config import get_data_dir

logger = logging.getLogger(__name__)


def _get_default_db_path() -> Path:
    return get_data_dir() / "reminders.db"


class Reminder(BaseModel):
    """A scheduled reminder.

    Attributes:
        id: Unique identifier (auto-generated).
        user_id: Telegram chat ID of the user who set the reminder.
        message: The reminder message to send.
        trigger_time: Next time to send the reminder (ISO format string).
        is_sent: Whether the reminder has been sent.
        recurrence_rule: Normalized cron rule for recurring reminders.
        recurrence_text: Human-readable recurrence description.
        timezone_name: IANA timezone used for recurring schedule calculation.
        created_at: When the reminder was created (ISO format string).
    """

    id: int | None = None
    user_id: str
    message: str
    trigger_time: str  # ISO format datetime string
    is_sent: bool = False
    recurrence_rule: str | None = None
    recurrence_text: str | None = None
    timezone_name: str | None = None
    created_at: str  # ISO format datetime string

    @property
    def is_recurring(self) -> bool:
        """True when this reminder will be rescheduled after firing."""
        return bool(self.recurrence_rule)


class ReminderStorage:
    """Storage for reminders using a persistent aiosqlite connection."""

    def __init__(self, db_path: Path | None = None) -> None:
        """Initialize reminder storage.

        Args:
            db_path: Override the database file path. When None (default),
                uses ``reminders.db`` inside the agent data directory.
                Pass an explicit path in tests to use a temp file.
        """
        self._db_path = db_path or _get_default_db_path()
        self._lock = asyncio.Lock()
        self._conn: aiosqlite.Connection | None = None

    @property
    def db_path(self) -> Path:
        """Path to the SQLite database file."""
        return self._db_path

    async def initialize(self) -> None:
        """Open the connection and create schema if needed (idempotent)."""
        async with self._lock:
            if self._conn is not None:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(self._db_path)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await self._create_tables(conn)
            self._conn = conn
            logger.info("Reminder storage initialized at %s", self._db_path)

    async def close(self) -> None:
        """Close the underlying database connection."""
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Reminder storage is not initialized")
        return self._conn

    async def _create_tables(self, conn: aiosqlite.Connection) -> None:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT    NOT NULL,
                message      TEXT    NOT NULL,
                trigger_time TEXT    NOT NULL,
                is_sent      INTEGER NOT NULL DEFAULT 0,
                recurrence_rule TEXT,
                recurrence_text TEXT,
                timezone_name TEXT,
                created_at   TEXT    NOT NULL
            )
        """)
        await self._migrate_schema(conn)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trigger_time_sent
            ON reminders (trigger_time, is_sent)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_id
            ON reminders (user_id)
        """)
        await conn.commit()

    async def _migrate_schema(self, conn: aiosqlite.Connection) -> None:
        """Add new columns for older reminder databases."""
        cursor = await conn.execute("PRAGMA table_info(reminders)")
        rows = await cursor.fetchall()
        existing_columns = {row["name"] for row in rows}

        required_columns = {
            "recurrence_rule": "TEXT",
            "recurrence_text": "TEXT",
            "timezone_name": "TEXT",
        }

        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue

            await conn.execute(
                f"ALTER TABLE reminders ADD COLUMN {column_name} {column_type}"
            )

    async def add_reminder(self, reminder: Reminder) -> int:
        """Insert a reminder and return its new row ID."""
        await self.initialize()
        conn = self._require_conn()
        cursor = await conn.execute(
            """
            INSERT INTO reminders
                (
                    user_id,
                    message,
                    trigger_time,
                    is_sent,
                    recurrence_rule,
                    recurrence_text,
                    timezone_name,
                    created_at
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reminder.user_id,
                reminder.message,
                reminder.trigger_time,
                int(reminder.is_sent),
                reminder.recurrence_rule,
                reminder.recurrence_text,
                reminder.timezone_name,
                reminder.created_at,
            ),
        )
        await conn.commit()
        rid = cursor.lastrowid or 0
        logger.info(
            "Added reminder %s for user %s: '%s...' at %s",
            rid,
            reminder.user_id,
            reminder.message[:30],
            reminder.trigger_time,
        )
        return rid

    async def get_due_reminders(self) -> list[Reminder]:
        """Return all unsent reminders whose trigger time has passed."""
        await self.initialize()
        conn = self._require_conn()
        now = now_utc().isoformat(timespec="seconds")
        cursor = await conn.execute(
            """
            SELECT
                id,
                user_id,
                message,
                trigger_time,
                is_sent,
                recurrence_rule,
                recurrence_text,
                timezone_name,
                created_at
            FROM reminders
            WHERE trigger_time <= ? AND is_sent = 0
            ORDER BY trigger_time ASC
            """,
            (now,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_reminder(r) for r in rows]

    async def mark_sent(self, reminder_id: int) -> None:
        """Mark a reminder as sent so the scheduler won't fire it again."""
        await self.initialize()
        conn = self._require_conn()
        await conn.execute(
            "UPDATE reminders SET is_sent = 1 WHERE id = ?", (reminder_id,)
        )
        await conn.commit()
        logger.info("Marked reminder %s as sent", reminder_id)

    async def reschedule_reminder(
        self, reminder_id: int, next_trigger_time: str
    ) -> None:
        """Move a recurring reminder to its next scheduled fire time."""
        await self.initialize()
        conn = self._require_conn()
        await conn.execute(
            """
            UPDATE reminders
            SET trigger_time = ?, is_sent = 0
            WHERE id = ?
            """,
            (next_trigger_time, reminder_id),
        )
        await conn.commit()
        logger.info(
            "Rescheduled recurring reminder %s for %s",
            reminder_id,
            next_trigger_time,
        )

    async def get_user_reminders(
        self, user_id: str, include_sent: bool = False
    ) -> list[Reminder]:
        """Return reminders for a user, optionally including already-sent ones."""
        await self.initialize()
        conn = self._require_conn()
        if include_sent:
            cursor = await conn.execute(
                """
                SELECT
                    id,
                    user_id,
                    message,
                    trigger_time,
                    is_sent,
                    recurrence_rule,
                    recurrence_text,
                    timezone_name,
                    created_at
                FROM reminders WHERE user_id = ?
                ORDER BY trigger_time ASC
                """,
                (user_id,),
            )
        else:
            cursor = await conn.execute(
                """
                SELECT
                    id,
                    user_id,
                    message,
                    trigger_time,
                    is_sent,
                    recurrence_rule,
                    recurrence_text,
                    timezone_name,
                    created_at
                FROM reminders WHERE user_id = ? AND is_sent = 0
                ORDER BY trigger_time ASC
                """,
                (user_id,),
            )
        rows = await cursor.fetchall()
        return [self._row_to_reminder(r) for r in rows]

    async def delete_reminder(self, reminder_id: int, user_id: str) -> bool:
        """Delete a reminder if it belongs to the given user.

        Returns:
            True if deleted, False if not found or wrong user.
        """
        await self.initialize()
        conn = self._require_conn()
        cursor = await conn.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?",
            (reminder_id, user_id),
        )
        await conn.commit()
        deleted = (cursor.rowcount or 0) > 0
        if deleted:
            logger.info("Deleted reminder %s", reminder_id)
        return deleted

    def _row_to_reminder(self, row: aiosqlite.Row) -> Reminder:
        return Reminder(
            id=row["id"],
            user_id=row["user_id"],
            message=row["message"],
            trigger_time=row["trigger_time"],
            is_sent=bool(row["is_sent"]),
            recurrence_rule=row["recurrence_rule"],
            recurrence_text=row["recurrence_text"],
            timezone_name=row["timezone_name"],
            created_at=row["created_at"],
        )


_storage: ReminderStorage | None = None


def get_storage() -> ReminderStorage:
    """Return the process-wide singleton ReminderStorage instance."""
    global _storage
    if _storage is None:
        _storage = ReminderStorage()
    return _storage


async def close_shared_reminder_storage() -> None:
    """Close the singleton connection and clear the global instance.

    aiosqlite keeps a non-daemon worker thread per open connection. Call this
    before process exit (e.g. end of pytest) so the interpreter is not blocked
    in ``threading._shutdown()``.
    """
    global _storage
    if _storage is None:
        return
    await _storage.close()
    _storage = None
