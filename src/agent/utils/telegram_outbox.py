"""Queue files to send via Telegram after an agent turn completes.

Tools register paths during ``run_async``; the handler drains the queue for the
current asyncio task via a :class:`contextvars.ContextVar` batch id so
concurrent chats do not mix uploads.

Lives under ``utils`` (not ``telegram/``) to avoid circular imports: loading
``agent.telegram`` runs ``bot.py``, which imports ``app`` while ``tools`` is
still initializing.
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PendingTelegramFile:
    """A local file to send with :meth:`telegram.Bot.send_document`."""

    path: Path
    caption: str | None
    filename: str | None = None


class TelegramFileOutboxError(Exception):
    """Raised when enqueueing a file outside an active Telegram agent batch."""


_batch_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "telegram_file_batch_id",
    default=None,
)
_lock = threading.Lock()
_batches: dict[str, list[PendingTelegramFile]] = {}


def begin_telegram_file_batch() -> None:
    """Start collecting files for the current agent turn (same asyncio Task)."""
    batch_id = str(uuid.uuid4())
    _batch_id_var.set(batch_id)
    with _lock:
        _batches[batch_id] = []


def register_telegram_file_for_send(
    path: Path,
    caption: str | None,
    *,
    filename: str | None = None,
    max_files_per_batch: int = 10,
) -> None:
    """Queue a file path to send after the model finishes.

    Args:
        path: Readable file on disk.
        caption: Optional Telegram caption (truncated by the sender to API limits).
        filename: Optional download name shown in Telegram.
        max_files_per_batch: Maximum files per turn.

    Raises:
        TelegramFileOutboxError: If not inside an active batch or limit exceeded.
    """
    batch_id = _batch_id_var.get()
    if batch_id is None:
        raise TelegramFileOutboxError(
            "Telegram file outbox is inactive (not running inside a Telegram "
            "agent turn)."
        )
    with _lock:
        bucket = _batches.get(batch_id)
        if bucket is None:
            raise TelegramFileOutboxError("Telegram file batch is invalid or ended.")
        if len(bucket) >= max_files_per_batch:
            raise TelegramFileOutboxError(
                f"At most {max_files_per_batch} files can be sent per message."
            )
        bucket.append(
            PendingTelegramFile(
                path=path,
                caption=caption,
                filename=filename,
            )
        )


def end_telegram_file_batch() -> list[PendingTelegramFile]:
    """End the current batch and return queued files (may be empty)."""
    batch_id = _batch_id_var.get()
    _batch_id_var.set(None)
    if batch_id is None:
        return []
    with _lock:
        return _batches.pop(batch_id, [])


def discard_telegram_staging_files(files: list[PendingTelegramFile]) -> None:
    """Remove staged paths after a failed turn (best-effort)."""
    for item in files:
        with contextlib.suppress(OSError):
            item.path.unlink(missing_ok=True)
