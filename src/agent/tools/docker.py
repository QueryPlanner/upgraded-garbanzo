"""Docker bash execution tool for the ADK agent."""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)

_DOCKER_BASH_MAX_COMMAND_CHARS = 12_000
_DOCKER_BASH_MIN_TIMEOUT_SEC = 1
_DOCKER_BASH_MAX_TIMEOUT_SEC = 300
_DOCKER_BASH_MAX_COMBINED_OUTPUT_BYTES = 256_000


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


async def docker_bash_execute(
    tool_context: ToolContext,  # noqa: ARG001
    command: str,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Run a shell command with bash inside the container (Docker only).

    Available only when the agent process runs in Docker (``/.dockerenv``).
    On a developer machine or bare-metal host without that marker, the tool
    returns an error and does not execute anything.

    Intended for automation alongside agent-browser and Playwright inside the
    image (e.g. listing files under ``/app``, smoke checks). Do not pass
    secrets on the command line.

    Args:
        tool_context: ADK ToolContext (unused; required by ADK).
        command: A bash script or pipeline executed as ``bash -lc <command>``.
        timeout_seconds: Wall-clock limit (1–300 seconds; default 60).

    Returns:
        Status, exit_code, stdout, stderr, and whether output was truncated.
    """
    _ = tool_context
    if not _agent_runs_inside_docker():
        return {
            "status": "error",
            "message": (
                "docker_bash_execute is disabled outside Docker. "
                "Run the agent via the container image to use this tool."
            ),
        }

    stripped = command.strip()
    if not stripped:
        return {
            "status": "error",
            "message": "command must be a non-empty string.",
        }

    if len(command) > _DOCKER_BASH_MAX_COMMAND_CHARS:
        max_chars = _DOCKER_BASH_MAX_COMMAND_CHARS
        return {
            "status": "error",
            "message": f"command exceeds maximum length ({max_chars} characters).",
        }

    if timeout_seconds < _DOCKER_BASH_MIN_TIMEOUT_SEC:
        timeout_seconds = _DOCKER_BASH_MIN_TIMEOUT_SEC
    elif timeout_seconds > _DOCKER_BASH_MAX_TIMEOUT_SEC:
        timeout_seconds = _DOCKER_BASH_MAX_TIMEOUT_SEC

    workdir = "/app"
    if not Path(workdir).is_dir():
        workdir = str(Path.cwd())

    logger.info(
        "docker_bash_execute: timeout=%ss cwd=%s",
        timeout_seconds,
        workdir,
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "bash",
            "-lc",
            stripped,
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
    except OSError as e:
        logger.exception("docker_bash_execute failed to start bash")
        return {
            "status": "error",
            "message": f"Failed to start bash: {e}",
        }

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "status": "error",
            "message": f"Command exceeded timeout of {timeout_seconds} seconds.",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "timed_out": True,
        }

    exit_code = proc.returncode
    out_max = _DOCKER_BASH_MAX_COMBINED_OUTPUT_BYTES // 2
    stdout_text, out_trunc = _truncate_output(stdout_b, out_max)
    stderr_text, err_trunc = _truncate_output(stderr_b, out_max)
    truncated = out_trunc or err_trunc

    return {
        "status": "success",
        "exit_code": exit_code,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "output_truncated": truncated,
        "cwd": workdir,
    }


__all__ = ["docker_bash_execute"]
