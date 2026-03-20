"""Persistent storage for scheduled reminders (Postgres or SQLite).

When DATABASE_URL points at Postgres, reminders are stored there alongside ADK
sessions. Otherwise a local SQLite file under the agent data directory is used.
"""

import asyncio
import logging
import sqlite3
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
from pydantic import BaseModel

from ..utils.app_timezone import now_utc
from ..utils.config import get_data_dir
from ..utils.pg_app_pool import get_shared_app_pool, postgres_dsn_from_environment

logger = logging.getLogger(__name__)


def _get_default_db_path() -> Path:
    """Get the default SQLite database path in the agent data directory."""
    return get_data_dir() / "reminders.db"


class Reminder(BaseModel):
    """A scheduled reminder.

    Attributes:
        id: Unique identifier (auto-generated).
        user_id: Telegram chat ID of the user who set the reminder.
        message: The reminder message to send.
        trigger_time: When to send the reminder (ISO format string).
        is_sent: Whether the reminder has been sent.
        created_at: When the reminder was created (ISO format string).
    """

    id: int | None = None
    user_id: str
    message: str
    trigger_time: str  # ISO format datetime string
    is_sent: bool = False
    created_at: str  # ISO format datetime string


class ReminderStorage:
    """Storage for reminders using Postgres (when configured) or SQLite."""

    def __init__(self, db_path: Path | None = None) -> None:
        """Initialize reminder storage.

        Args:
            db_path: If set, always use SQLite at this path (e.g. tests).
                If None, use Postgres when DATABASE_URL is a Postgres URL,
                otherwise default SQLite under the agent data directory.
        """
        self._explicit_sqlite = db_path is not None
        self._sqlite_db_path = db_path or _get_default_db_path()
        self._use_postgres = (not self._explicit_sqlite) and (
            postgres_dsn_from_environment() is not None
        )
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def db_path(self) -> Path:
        """Path to the SQLite database file (meaningful only in SQLite mode)."""
        return self._sqlite_db_path

    def _ensure_db_dir(self) -> None:
        """Ensure the SQLite database directory exists."""
        self._sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_sqlite_connection(self) -> sqlite3.Connection:
        """Open a SQLite connection."""
        conn = sqlite3.connect(self._sqlite_db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    async def initialize(self) -> None:
        """Create schema if needed."""
        async with self._lock:
            if self._initialized:
                return

            if self._use_postgres:
                pool = await get_shared_app_pool()
                if pool is None:
                    msg = "Postgres was expected but pool could not be created"
                    raise RuntimeError(msg)
                self._pool = pool
                await self._create_tables_postgres()
                logger.info(
                    "Reminder storage initialized (Postgres table agent_reminders)"
                )
            else:
                self._ensure_db_dir()
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._create_tables_sqlite)
                logger.info("Reminder storage initialized at %s", self._sqlite_db_path)

            self._initialized = True

    async def _create_tables_postgres(self) -> None:
        pool = self._pool
        if pool is None:
            msg = "Postgres pool is not initialized"
            raise RuntimeError(msg)
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_reminders (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    trigger_time TEXT NOT NULL,
                    is_sent BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TEXT NOT NULL
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_reminders_trigger_sent
                ON agent_reminders (trigger_time, is_sent)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_reminders_user_id
                ON agent_reminders (user_id)
            """)

    def _create_tables_sqlite(self) -> None:
        conn = self._get_sqlite_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    trigger_time TEXT NOT NULL,
                    is_sent INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trigger_time_sent
                ON reminders(trigger_time, is_sent)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_id
                ON reminders(user_id)
            """)
            conn.commit()
        finally:
            conn.close()

    async def add_reminder(self, reminder: Reminder) -> int:
        """Add a reminder; returns new row id."""
        await self.initialize()

        if self._use_postgres:
            pool = self._pool
            if pool is None:
                msg = "Postgres pool is not initialized"
                raise RuntimeError(msg)
            reminder_id = await pool.fetchval(
                """
                INSERT INTO agent_reminders
                (user_id, message, trigger_time, is_sent, created_at)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                reminder.user_id,
                reminder.message,
                reminder.trigger_time,
                reminder.is_sent,
                reminder.created_at,
            )
            rid = int(reminder_id) if reminder_id is not None else 0
        else:
            loop = asyncio.get_running_loop()
            rid = await loop.run_in_executor(None, self._add_reminder_sqlite, reminder)

        logger.info(
            "Added reminder %s for user %s: '%s...' at %s",
            rid,
            reminder.user_id,
            reminder.message[:30],
            reminder.trigger_time,
        )
        return rid

    def _add_reminder_sqlite(self, reminder: Reminder) -> int:
        conn = self._get_sqlite_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO reminders
                (user_id, message, trigger_time, is_sent, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    reminder.user_id,
                    reminder.message,
                    reminder.trigger_time,
                    int(reminder.is_sent),
                    reminder.created_at,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            conn.close()

    async def get_due_reminders(self) -> list[Reminder]:
        """Reminders with trigger_time <= now and not yet sent."""
        await self.initialize()
        now = now_utc().isoformat(timespec="seconds")

        if self._use_postgres:
            pool = self._pool
            if pool is None:
                msg = "Postgres pool is not initialized"
                raise RuntimeError(msg)
            rows = await pool.fetch(
                """
                SELECT id, user_id, message, trigger_time, is_sent, created_at
                FROM agent_reminders
                WHERE trigger_time <= $1 AND is_sent = FALSE
                ORDER BY trigger_time ASC
                """,
                now,
            )
            return [self._record_to_reminder(r) for r in rows]

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_due_reminders_sqlite, now)

    def _get_due_reminders_sqlite(self, now: str) -> list[Reminder]:
        conn = self._get_sqlite_connection()
        try:
            cursor = conn.execute(
                """
                SELECT id, user_id, message, trigger_time, is_sent, created_at
                FROM reminders
                WHERE trigger_time <= ? AND is_sent = 0
                ORDER BY trigger_time ASC
                """,
                (now,),
            )
            rows = cursor.fetchall()
            return [self._sqlite_row_to_reminder(row) for row in rows]
        finally:
            conn.close()

    async def mark_sent(self, reminder_id: int) -> None:
        """Mark a reminder as sent."""
        await self.initialize()

        if self._use_postgres:
            pool = self._pool
            if pool is None:
                msg = "Postgres pool is not initialized"
                raise RuntimeError(msg)
            await pool.execute(
                "UPDATE agent_reminders SET is_sent = TRUE WHERE id = $1",
                reminder_id,
            )
        else:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._mark_sent_sqlite, reminder_id)

        logger.info("Marked reminder %s as sent", reminder_id)

    def _mark_sent_sqlite(self, reminder_id: int) -> None:
        conn = self._get_sqlite_connection()
        try:
            conn.execute(
                "UPDATE reminders SET is_sent = 1 WHERE id = ?",
                (reminder_id,),
            )
            conn.commit()
        finally:
            conn.close()

    async def get_user_reminders(
        self, user_id: str, include_sent: bool = False
    ) -> list[Reminder]:
        """List reminders for one user."""
        await self.initialize()

        if self._use_postgres:
            pool = self._pool
            if pool is None:
                msg = "Postgres pool is not initialized"
                raise RuntimeError(msg)
            if include_sent:
                rows = await pool.fetch(
                    """
                    SELECT id, user_id, message, trigger_time, is_sent, created_at
                    FROM agent_reminders
                    WHERE user_id = $1
                    ORDER BY trigger_time ASC
                    """,
                    user_id,
                )
            else:
                rows = await pool.fetch(
                    """
                    SELECT id, user_id, message, trigger_time, is_sent, created_at
                    FROM agent_reminders
                    WHERE user_id = $1 AND is_sent = FALSE
                    ORDER BY trigger_time ASC
                    """,
                    user_id,
                )
            return [self._record_to_reminder(r) for r in rows]

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._get_user_reminders_sqlite, user_id, include_sent
        )

    def _get_user_reminders_sqlite(
        self, user_id: str, include_sent: bool
    ) -> list[Reminder]:
        conn = self._get_sqlite_connection()
        try:
            if include_sent:
                cursor = conn.execute(
                    """
                    SELECT id, user_id, message, trigger_time, is_sent, created_at
                    FROM reminders
                    WHERE user_id = ?
                    ORDER BY trigger_time ASC
                    """,
                    (user_id,),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT id, user_id, message, trigger_time, is_sent, created_at
                    FROM reminders
                    WHERE user_id = ? AND is_sent = 0
                    ORDER BY trigger_time ASC
                    """,
                    (user_id,),
                )
            rows = cursor.fetchall()
            return [self._sqlite_row_to_reminder(row) for row in rows]
        finally:
            conn.close()

    async def delete_reminder(self, reminder_id: int, user_id: str) -> bool:
        """Delete a reminder if it belongs to the user."""
        await self.initialize()

        if self._use_postgres:
            pool = self._pool
            if pool is None:
                msg = "Postgres pool is not initialized"
                raise RuntimeError(msg)
            row = await pool.fetchrow(
                (
                    "DELETE FROM agent_reminders "
                    "WHERE id = $1 AND user_id = $2 RETURNING id"
                ),
                reminder_id,
                user_id,
            )
            deleted = row is not None
        else:
            loop = asyncio.get_running_loop()
            deleted = await loop.run_in_executor(
                None, self._delete_reminder_sqlite, reminder_id, user_id
            )

        if deleted:
            logger.info("Deleted reminder %s", reminder_id)
        return deleted

    def _delete_reminder_sqlite(self, reminder_id: int, user_id: str) -> bool:
        conn = self._get_sqlite_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM reminders WHERE id = ? AND user_id = ?",
                (reminder_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def _sqlite_row_to_reminder(self, row: sqlite3.Row) -> Reminder:
        return Reminder(
            id=row["id"],
            user_id=row["user_id"],
            message=row["message"],
            trigger_time=row["trigger_time"],
            is_sent=bool(row["is_sent"]),
            created_at=row["created_at"],
        )

    def _record_to_reminder(self, row: asyncpg.Record) -> Reminder:
        return Reminder(
            id=row["id"],
            user_id=row["user_id"],
            message=row["message"],
            trigger_time=row["trigger_time"],
            is_sent=bool(row["is_sent"]),
            created_at=row["created_at"],
        )


_storage: ReminderStorage | None = None


def get_storage() -> ReminderStorage:
    """Singleton ReminderStorage for the process."""
    global _storage
    if _storage is None:
        _storage = ReminderStorage()
    return _storage
