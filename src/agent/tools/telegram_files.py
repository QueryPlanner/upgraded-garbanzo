"""Telegram file sending tool for the ADK agent."""

import contextlib
import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from google.adk.tools import ToolContext

from ..utils.config import get_data_dir
from ..utils.telegram_outbox import (
    TelegramFileOutboxError,
    register_telegram_file_for_send,
)

logger = logging.getLogger(__name__)

_MAX_TELEGRAM_UPLOAD_BYTES = 100 * 1024 * 1024
_MAX_TELEGRAM_INLINE_TEXT_BYTES = 512 * 1024
# Max length for treating ``text_file_body`` as a single-line filesystem path.
_MAX_PATHLIKE_TEXT_FILE_BODY_LEN = 4096


def _validate_agent_data_relative_path(relative_path: str) -> Path:
    """Resolve a path under the agent data directory (no traversal)."""
    rel = relative_path.replace("\\", "/").strip("/")
    if not rel:
        raise ValueError("agent_data_path cannot be empty")
    parts = [p for p in rel.split("/") if p]
    for part in parts:
        if part in (".", ".."):
            raise ValueError("Invalid path segment in agent_data_path")
    base = get_data_dir().resolve()
    full_path = (base / Path(*parts)).resolve()
    full_path.relative_to(base)
    return full_path


def _resolve_agent_data_or_host_path(agent_data_path: str) -> Path:
    """Resolve ``agent_data_path`` to a file path.

    * **Absolute** path: ``~`` is expanded, then :meth:`pathlib.Path.resolve`.
      Any regular file the process can read (e.g. ``/app/agent_data/x.png``).
    * **Relative** path: must stay under ``get_data_dir()`` (no ``..``).
    """
    trimmed = agent_data_path.strip()
    if not trimmed:
        raise ValueError("agent_data_path cannot be empty")
    expanded = Path(trimmed).expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return _validate_agent_data_relative_path(trimmed)


def _stage_file_copy_for_telegram(source: Path, display_name: str) -> Path:
    """Copy a source file into staging for upload and later deletion."""
    staging_root = get_data_dir() / ".telegram_staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    safe = display_name.replace("/", "_").replace("\\", "_")[:200]
    dest = staging_root / f"{uuid.uuid4().hex}_{safe}"
    shutil.copy2(source, dest)
    return dest


def _stage_utf8_text_for_telegram(text: str, display_name: str) -> Path:
    """Write UTF-8 text to a staged file."""
    body = text.encode("utf-8")
    if len(body) > _MAX_TELEGRAM_INLINE_TEXT_BYTES:
        max_kib = _MAX_TELEGRAM_INLINE_TEXT_BYTES // 1024
        raise ValueError(
            f"text_file_body exceeds inline limit ({max_kib} KiB). "
            "Write a larger file under agent data or .context first."
        )
    staging_root = get_data_dir() / ".telegram_staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    safe = display_name.replace("/", "_").replace("\\", "_")[:200]
    dest = staging_root / f"{uuid.uuid4().hex}_{safe}"
    dest.write_bytes(body)
    return dest


def _validate_single_download_filename(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("text_file_name cannot be empty")
    if "/" in cleaned or "\\" in cleaned:
        raise ValueError("text_file_name must not contain path separators")
    if cleaned in (".", ".."):
        raise ValueError("Invalid text_file_name")
    return cleaned


def _coerce_text_file_body_to_string(body: Any) -> str:
    """Normalize ``text_file_body`` to UTF-8 text for staging or path detection."""
    if isinstance(body, str):
        return body
    if isinstance(body, (dict, list, tuple)):
        try:
            return json.dumps(
                body,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "text_file_body structure could not be encoded as JSON text."
            ) from exc
    raise ValueError(
        "text_file_body must be a string (raw file content, or one line that is "
        "an absolute path to an existing file), or a dict/list/tuple (pretty "
        "JSON). To attach a file already on disk, use agent_data_path with that "
        "path instead of embedding the path inside a JSON object."
    )


def _existing_file_if_text_body_is_path_string(body: str) -> Path | None:
    """If ``body`` is a single-line absolute (or ``~/``) path to a file, return it.

    Models often mistakenly pass a host path in ``text_file_body``; without this,
    the path string itself is UTF-8-encoded and sent as the file content.
    """
    if not body:
        return None
    if len(body) > _MAX_PATHLIKE_TEXT_FILE_BODY_LEN:
        return None
    if "\n" in body or "\r" in body:
        return None
    stripped = body.strip()
    if not stripped:
        return None
    try:
        p = Path(stripped).expanduser()
        if not p.is_absolute():
            return None
        if p.is_file() and p.exists():
            return p.resolve()
    except Exception:
        return None
    return None


def _queue_telegram_send_file_copy(
    source: Path,
    display_name: str,
    tool_context: ToolContext,
    caption: str | None = None,
    parse_mode: str | None = None,
) -> dict[str, Any]:
    """Copy file to staging and register for async Telegram send after reply."""
    user_id = getattr(tool_context, "user_id", None) or tool_context.state.get(
        "user_id"
    )
    if not user_id:
        raise TelegramFileOutboxError("Cannot send file: user not identified.")

    staged = _stage_file_copy_for_telegram(source, display_name)
    try:
        register_telegram_file_for_send(
            path=staged,
            caption=caption,
            filename=display_name,
        )
    except Exception:
        # Clean up staged file if registration fails
        with contextlib.suppress(Exception):
            staged.unlink(missing_ok=True)
        raise
    logger.info(
        "Queued Telegram file %s for chat %s (staged at %s)",
        display_name,
        user_id,
        staged,
    )
    return {
        "status": "queued",
        "filename": display_name,
        "path": str(staged),
        "size_bytes": staged.stat().st_size,
    }


def send_telegram_file(
    tool_context: ToolContext,
    text_file_name: str,
    # ADK uses isinstance(default, annotation); ``typing.Any`` raises TypeError.
    # Use plain ``dict``/``list`` (not parameterized) so runtime isinstance() is valid.
    text_file_body: str | dict | list | None = None,
    agent_data_path: str | None = None,
    caption: str | None = None,
    parse_mode: str | None = None,
) -> dict[str, Any]:
    """Queue a file to be sent to the user on Telegram after the agent reply.

    Exactly one of ``text_file_body`` or ``agent_data_path`` must be provided.

    Args:
        tool_context: ADK ToolContext with user_id in state.
        text_file_name: Display filename for the Telegram attachment
            (no path separators).
        text_file_body: UTF-8 text, or a JSON-serializable dict/list. Can also
            be a single-line absolute path to an existing file on the host.
        agent_data_path: Path to an existing file under the agent data directory
            (relative, no ``..``) or an absolute path on the host.
        caption: Optional caption text for the Telegram file message.
        parse_mode: Optional parse mode for caption (``"MarkdownV2"`` or ``"HTML"``).

    Returns:
        Status dict with ``status`` and either ``filename``/``size_bytes``
        or ``message``.
    """
    try:
        safe_name = _validate_single_download_filename(text_file_name)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    source: Path | None = None
    try:
        if agent_data_path is not None and text_file_body is not None:
            return {
                "status": "error",
                "message": (
                    "Provide only one of agent_data_path or text_file_body, not both."
                ),
            }

        if agent_data_path is not None:
            try:
                source = _resolve_agent_data_or_host_path(agent_data_path)
            except ValueError as e:
                return {"status": "error", "message": str(e)}

            if not source.is_file():
                return {
                    "status": "error",
                    "message": f"File not found: {agent_data_path}",
                }
            file_size = source.stat().st_size
            if file_size > _MAX_TELEGRAM_UPLOAD_BYTES:
                max_mb = _MAX_TELEGRAM_UPLOAD_BYTES // (1024 * 1024)
                return {
                    "status": "error",
                    "message": (
                        f"File too large ({file_size} bytes). Max: {max_mb} MiB."
                    ),
                }
        elif text_file_body is not None:
            body_str = _coerce_text_file_body_to_string(text_file_body)

            existing = _existing_file_if_text_body_is_path_string(body_str)
            if existing is not None:
                file_size = existing.stat().st_size
                if file_size > _MAX_TELEGRAM_UPLOAD_BYTES:
                    max_mb = _MAX_TELEGRAM_UPLOAD_BYTES // (1024 * 1024)
                    return {
                        "status": "error",
                        "message": (
                            f"File too large ({file_size} bytes). Max: {max_mb} MiB."
                        ),
                    }
                source = existing
            else:
                try:
                    source = _stage_utf8_text_for_telegram(body_str, safe_name)
                except ValueError as e:
                    return {"status": "error", "message": str(e)}
        else:
            return {
                "status": "error",
                "message": "Provide either agent_data_path or text_file_body.",
            }

        try:
            return _queue_telegram_send_file_copy(
                source=source,
                display_name=safe_name,
                tool_context=tool_context,
                caption=caption,
                parse_mode=parse_mode,
            )
        except TelegramFileOutboxError as e:
            return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.exception("send_telegram_file failed")
        return {"status": "error", "message": f"Failed to send file: {e}"}


__all__ = ["send_telegram_file"]
