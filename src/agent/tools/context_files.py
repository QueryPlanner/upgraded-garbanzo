"""Context file tools for secure operations in .context/ directory."""

import logging
from pathlib import Path
from typing import Any

from google.adk.tools import ToolContext

from ..utils.config import get_context_dir

logger = logging.getLogger(__name__)


def _validate_context_filename(filename: str) -> Path:
    """Validate and resolve a filename within the .context/ directory.

    Args:
        filename: The filename to validate (e.g., "USER.md").

    Returns:
        The resolved absolute path within .context/.

    Raises:
        ValueError: If the filename is invalid or attempts path traversal.
    """
    # Sanitize filename: no path separators, no parent directory references
    if not filename:
        raise ValueError("Filename cannot be empty")

    # Normalize and check for path traversal
    normalized = filename.replace("\\", "/").strip("/")
    if ".." in normalized or "/" in normalized:
        raise ValueError(
            f"Invalid filename '{filename}': path separators and '..' not allowed"
        )

    context_dir = get_context_dir().resolve()

    # Resolve the full path
    full_path = (context_dir / normalized).resolve()

    # Ensure the resolved path is within the context directory
    try:
        full_path.relative_to(context_dir)
    except ValueError:
        raise ValueError(
            f"Invalid filename '{filename}': must be within .context/ directory"
        ) from None

    return full_path


def read_context_file(
    tool_context: ToolContext,  # noqa: ARG001
    filename: str,
) -> dict[str, Any]:
    """Read a file from the .context/ directory.

    Args:
        tool_context: ADK ToolContext (unused but required by ADK).
        filename: The filename to read (e.g., "USER.md", "IDENTITY.md").

    Returns:
        A dictionary with status and file contents or error message.
    """
    try:
        file_path = _validate_context_filename(filename)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    if not file_path.exists():
        return {"status": "error", "message": f"File '{filename}' not found."}

    try:
        content = file_path.read_text(encoding="utf-8")
        return {
            "status": "success",
            "filename": filename,
            "content": content,
            "path": str(file_path),
        }
    except Exception as e:
        logger.exception("Failed to read context file")
        return {"status": "error", "message": f"Failed to read file: {e}"}


def write_context_file(
    tool_context: ToolContext,  # noqa: ARG001
    filename: str,
    content: str,
) -> dict[str, Any]:
    """Write content to a file in the .context/ directory.

    Args:
        tool_context: ADK ToolContext (unused but required by ADK).
        filename: The filename to write (e.g., "USER.md").
        content: The content to write to the file.

    Returns:
        A dictionary with status and confirmation or error message.
    """
    try:
        file_path = _validate_context_filename(filename)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    try:
        file_path.write_text(content, encoding="utf-8")
        return {
            "status": "success",
            "filename": filename,
            "message": f"Successfully wrote {len(content)} characters to '{filename}'.",
            "path": str(file_path),
        }
    except Exception as e:
        logger.exception("Failed to write context file")
        return {"status": "error", "message": f"Failed to write file: {e}"}


def delete_context_file(
    tool_context: ToolContext,  # noqa: ARG001
    filename: str,
) -> dict[str, Any]:
    """Delete a file from the .context/ directory.

    Args:
        tool_context: ADK ToolContext (unused but required by ADK).
        filename: The filename to delete (e.g., "BOOTSTRAP.md").

    Returns:
        A dictionary with status and confirmation or error message.
    """
    try:
        file_path = _validate_context_filename(filename)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    if not file_path.exists():
        return {"status": "error", "message": f"File '{filename}' not found."}

    try:
        file_path.unlink()
        return {
            "status": "success",
            "filename": filename,
            "message": f"Successfully deleted '{filename}'.",
        }
    except Exception as e:
        logger.exception("Failed to delete context file")
        return {"status": "error", "message": f"Failed to delete file: {e}"}


def list_context_files(
    tool_context: ToolContext,  # noqa: ARG001
) -> dict[str, Any]:
    """List all files in the .context/ directory.

    Args:
        tool_context: ADK ToolContext (unused but required by ADK).

    Returns:
        A dictionary with status and list of files or error message.
    """
    try:
        context_dir = get_context_dir()
        if not context_dir.exists():
            return {
                "status": "success",
                "files": [],
                "message": "No .context/ directory found.",
            }
        files: list[dict[str, int | str]] = [
            {"name": f.name, "size": f.stat().st_size}
            for f in context_dir.iterdir()
            if f.is_file() and not f.name.startswith(".")
        ]
        files.sort(key=lambda x: str(x["name"]))
        return {
            "status": "success",
            "files": files,
            "count": len(files),
            "message": f"Found {len(files)} file(s) in .context/ directory.",
        }
    except Exception as e:
        logger.exception("Failed to list context files")
        return {"status": "error", "message": f"Failed to list files: {e}"}


__all__ = [
    "delete_context_file",
    "list_context_files",
    "read_context_file",
    "write_context_file",
]
