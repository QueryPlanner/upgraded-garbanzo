"""Claude coding task tool for long-running autonomous coding."""

import asyncio
import contextlib
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from google.adk.tools import ToolContext
from telegram import InputFile

from ..telegram.notifications import get_notification_service

logger = logging.getLogger(__name__)

_DOCKER_BASH_MAX_COMBINED_OUTPUT_BYTES = 256_000
_TELEGRAM_PLAIN_TEXT_MAX_MESSAGE_CHARS = 4000
_TELEGRAM_DOCUMENT_CAPTION_MAX = 1024

_ACTIVE_BACKGROUND_CLAUDE_JOBS: dict[str, asyncio.Task[None]] = {}


def _agent_runs_inside_docker() -> bool:
    """Return True when running in a typical Docker Linux container."""
    return Path("/.dockerenv").exists()


def _truncate_output(data: bytes, max_bytes: int) -> tuple[str, bool]:
    """Decode output with replacement; truncate to max_bytes (whole codepoints)."""
    truncated = False
    raw = data
    if len(raw) > max_bytes:
        truncated = True
        raw = raw[:max_bytes]
    text = raw.decode(errors="replace")
    if truncated:
        text += "\n… [output truncated]"
    return text, truncated


def _resolve_claude_workdir(workdir: str | None) -> str:
    """Return a valid working directory for Claude Code."""
    requested_cwd = workdir or str(Path("/home/app/garbanzo-home/workspace"))
    if Path(requested_cwd).is_dir():
        return requested_cwd
    return str(Path.cwd())


def _build_claude_subprocess_env() -> dict[str, str]:
    """Return a copy of the process env for the Claude subprocess.

    Set ``ANTHROPIC_BASE_URL`` and ``ANTHROPIC_AUTH_TOKEN`` in the agent process
    environment (e.g. ``.env`` / Compose); they are passed through unchanged.
    """
    return os.environ.copy()


def _claude_anthropic_env_is_configured(env: dict[str, str]) -> bool:
    base = (env.get("ANTHROPIC_BASE_URL") or "").strip()
    token = (env.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    return bool(base and token)


def _split_plain_text_for_telegram(
    text: str,
    max_chars: int = _TELEGRAM_PLAIN_TEXT_MAX_MESSAGE_CHARS,
) -> list[str]:
    """Split plain text into Telegram-sized chunks."""
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    text_length = len(text)
    while start < text_length:
        end = min(start + max_chars, text_length)
        chunks.append(text[start:end])
        start = end
    return chunks


async def _execute_claude_coding_subprocess(
    *,
    prompt: str,
    cwd: str,
    env: dict[str, str],
) -> dict[str, Any]:
    """Run Claude Code and return a normalized result payload."""
    logger.info(
        "run_claude_coding_task: Starting Claude with prompt length %d in %s",
        len(prompt),
        cwd,
    )

    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        "glm-5",
        "--dangerously-skip-permissions",
        "--output-format",
        "text",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_b, stderr_b = await proc.communicate()
        exit_code = proc.returncode

        out_max = _DOCKER_BASH_MAX_COMBINED_OUTPUT_BYTES // 2
        stdout_text, out_trunc = _truncate_output(stdout_b, out_max)
        stderr_text, err_trunc = _truncate_output(stderr_b, out_max)

        return {
            "status": "success" if exit_code == 0 else "error",
            "exit_code": exit_code,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "truncated": out_trunc or err_trunc,
        }
    except Exception as e:
        logger.exception("run_claude_coding_task failed")
        return {"status": "error", "message": f"Failed to execute Claude Code: {e}"}


def _track_background_claude_job(job_id: str, task: asyncio.Task[None]) -> None:
    """Keep background Claude tasks alive until they finish."""
    _ACTIVE_BACKGROUND_CLAUDE_JOBS[job_id] = task

    def _cleanup(completed_task: asyncio.Task[None]) -> None:
        _ACTIVE_BACKGROUND_CLAUDE_JOBS.pop(job_id, None)
        with contextlib.suppress(asyncio.CancelledError):
            completed_task.result()

    task.add_done_callback(_cleanup)


async def _send_background_claude_job_result(
    *,
    chat_id: str,
    job_id: str,
    cwd: str,
    result: dict[str, Any],
) -> None:
    """Send the final Claude job result back to Telegram."""
    notification_service = get_notification_service()
    if notification_service._bot is None:
        logger.warning(
            "Claude job %s finished but Telegram bot is unavailable",
            job_id,
        )
        return

    summary_lines = [
        f"Claude job `{job_id}` finished.",
        f"Status: {result.get('status', 'unknown')}",
        f"Workdir: {cwd}",
    ]

    exit_code = result.get("exit_code")
    if exit_code is not None:
        summary_lines.append(f"Exit code: {exit_code}")
    if result.get("truncated"):
        summary_lines.append("Output was truncated.")

    summary_chunks = _split_plain_text_for_telegram("\n".join(summary_lines))
    for chunk in summary_chunks:
        await notification_service.bot.send_message(chat_id=chat_id, text=chunk)

    stdout_text = str(result.get("stdout") or "").strip()
    stderr_text = str(result.get("stderr") or "").strip()
    error_message = str(result.get("message") or "").strip()

    output_sections: list[str] = []
    if stdout_text:
        output_sections.append(f"stdout:\n{stdout_text}")
    if stderr_text:
        output_sections.append(f"stderr:\n{stderr_text}")
    if error_message and not output_sections:
        output_sections.append(error_message)

    for section in output_sections:
        for chunk in _split_plain_text_for_telegram(section):
            await notification_service.bot.send_message(chat_id=chat_id, text=chunk)

    await _deliver_claude_completion_to_agent_session(
        chat_id=chat_id,
        job_id=job_id,
        cwd=cwd,
        result=result,
    )


async def _deliver_claude_completion_to_agent_session(
    *,
    chat_id: str,
    job_id: str,
    cwd: str,
    result: dict[str, Any],
) -> None:
    """Append the job result to the user's ADK session and post the agent's reply."""
    from ..telegram.bot import send_agent_markdown_to_chat_id
    from ..telegram.handler import get_handler, process_claude_job_completion

    if get_handler() is None:
        logger.warning(
            "Claude job %s finished but Telegram handler is not initialized; "
            "skipping agent follow-up turn",
            job_id,
        )
        return

    try:
        reply = await process_claude_job_completion(
            user_id=chat_id,
            job_id=job_id,
            cwd=cwd,
            result=result,
        )
    except Exception:
        logger.exception("Agent follow-up failed for Claude job %s", job_id)
        return

    if reply is None or reply.superseded:
        return

    has_text = bool(reply.text.strip())
    has_docs = bool(reply.documents)
    if not has_text and not has_docs:
        return

    notification_service = get_notification_service()
    if notification_service._bot is None:
        logger.warning(
            "Claude job %s agent follow-up produced output but bot is unavailable",
            job_id,
        )
        return

    bot = notification_service.bot

    if has_text:
        await send_agent_markdown_to_chat_id(bot, chat_id, reply.text)

    for doc in reply.documents:
        try:
            caption = doc.caption
            if caption is not None and len(caption) > _TELEGRAM_DOCUMENT_CAPTION_MAX:
                caption = caption[: _TELEGRAM_DOCUMENT_CAPTION_MAX - 1] + "…"
            with doc.path.open("rb") as upload_fh:
                document = InputFile(
                    upload_fh,
                    filename=doc.filename or doc.path.name,
                )
            await bot.send_document(
                chat_id=chat_id,
                document=document,
                caption=caption,
            )
        except Exception:
            logger.exception(
                "Failed to send follow-up document for Claude job %s path=%s",
                job_id,
                doc.path,
            )
        finally:
            doc.path.unlink(missing_ok=True)


async def _run_background_claude_job(
    *,
    chat_id: str,
    job_id: str,
    prompt: str,
    cwd: str,
    env: dict[str, str],
) -> None:
    """Execute one background Claude job and notify Telegram when it finishes."""
    result = await _execute_claude_coding_subprocess(prompt=prompt, cwd=cwd, env=env)
    try:
        await _send_background_claude_job_result(
            chat_id=chat_id,
            job_id=job_id,
            cwd=cwd,
            result=result,
        )
    except Exception:
        logger.exception("Failed to send Claude job completion for %s", job_id)


def _start_background_claude_job(
    *,
    chat_id: str,
    prompt: str,
    cwd: str,
    env: dict[str, str],
) -> str:
    """Launch Claude Code in the background for Telegram users."""
    job_id = uuid.uuid4().hex[:8]
    task = asyncio.create_task(
        _run_background_claude_job(
            chat_id=chat_id,
            job_id=job_id,
            prompt=prompt,
            cwd=cwd,
            env=env,
        )
    )
    _track_background_claude_job(job_id, task)
    return job_id


def _get_user_id(tool_context: ToolContext) -> str | None:
    """Extract user_id from tool context."""
    user_id = getattr(tool_context, "user_id", None) or tool_context.state.get(
        "user_id"
    )
    return str(user_id) if user_id is not None else None


async def run_claude_coding_task(
    tool_context: ToolContext,  # noqa: ARG001
    prompt: str,
    workdir: str | None = None,
) -> dict[str, Any]:
    """Run a long-running Claude Code task to resolve coding issues/features.

    This tool is designed to take a significant amount of time (up to hours) to complete
    as it autonomously implements features and fixes bugs. Once the task finishes, the
    result will be returned asynchronously.

    Available only when the agent process runs in Docker (``/.dockerenv``).

    Args:
        tool_context: ADK ToolContext (unused; required by ADK).
        prompt: Instructions for Claude. Include issue details, requirements, etc.
        workdir: Directory to run in (default: /home/app/garbanzo-home/workspace)
    """
    if not _agent_runs_inside_docker():
        return {
            "status": "error",
            "message": "run_claude_coding_task is disabled outside Docker.",
        }

    env = _build_claude_subprocess_env()
    if not _claude_anthropic_env_is_configured(env):
        return {
            "status": "error",
            "message": (
                "Missing ANTHROPIC_BASE_URL or ANTHROPIC_AUTH_TOKEN in env. "
                "Set them in the agent environment (see .env.example)."
            ),
        }

    cwd = _resolve_claude_workdir(workdir)
    user_id = _get_user_id(tool_context)

    if user_id:
        job_id = _start_background_claude_job(
            chat_id=user_id,
            prompt=prompt,
            cwd=cwd,
            env=env,
        )
        return {
            "status": "started",
            "job_id": job_id,
            "message": (
                f"Started Claude job {job_id} in the background. "
                "You can keep chatting here, and the final result will be "
                "sent back to Telegram when the job finishes."
            ),
        }

    return await _execute_claude_coding_subprocess(prompt=prompt, cwd=cwd, env=env)


__all__ = ["run_claude_coding_task"]
