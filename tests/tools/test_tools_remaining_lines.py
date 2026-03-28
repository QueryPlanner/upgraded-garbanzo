"""Line coverage for remaining branches in ``agent.tools``."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from conftest import MockState, MockToolContext
from google.adk.tools import ToolContext

from agent.fitness import CalorieEntry, MealType
from agent.tools import (
    add_calories,
    delete_context_file,
    delete_fitness_entry,
    get_calorie_stats,
    get_workout_stats,
    get_youtube_transcript,
    list_calories,
    list_context_files,
    list_workouts,
    log_workout,
    read_context_file,
    write_context_file,
)


@pytest.fixture
def mock_tool_context() -> ToolContext:
    ctx = MagicMock(spec=ToolContext)
    ctx.user_id = "u1"
    ctx.state = MagicMock()
    ctx.state.get = MagicMock(return_value="u1")
    return ctx


@pytest.fixture
def mock_tool_context_no_user() -> ToolContext:
    ctx = MagicMock(spec=ToolContext)
    ctx.user_id = None
    ctx.state = MagicMock()
    ctx.state.get = MagicMock(return_value=None)
    return ctx


class TestFitnessToolErrors:
    @pytest.mark.asyncio
    async def test_add_calories_storage_error(
        self, mock_tool_context: ToolContext
    ) -> None:
        ms = MagicMock()
        ms.add_calorie_entry = AsyncMock(side_effect=RuntimeError("x"))
        with patch("agent.fitness.tools.get_fitness_storage", return_value=ms):
            r = await add_calories(mock_tool_context, "f", 100)
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_list_calories_no_user(
        self, mock_tool_context_no_user: ToolContext
    ) -> None:
        r = await list_calories(mock_tool_context_no_user)
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_list_calories_meal_filter(
        self, mock_tool_context: ToolContext
    ) -> None:
        e1 = CalorieEntry(
            id=1,
            user_id="u1",
            date="2026-01-01",
            food_item="a",
            calories=1,
            meal_type=MealType.LUNCH,
            created_at=datetime.now(UTC).isoformat(),
        )
        e2 = CalorieEntry(
            id=2,
            user_id="u1",
            date="2026-01-01",
            food_item="b",
            calories=2,
            meal_type=MealType.SNACK,
            created_at=datetime.now(UTC).isoformat(),
        )
        ms = MagicMock()
        ms.get_calorie_entries = AsyncMock(return_value=[e1, e2])
        with patch("agent.fitness.tools.get_fitness_storage", return_value=ms):
            r = await list_calories(mock_tool_context, meal_type="lunch")
        assert r["count"] == 1

    @pytest.mark.asyncio
    async def test_list_calories_storage_error(
        self, mock_tool_context: ToolContext
    ) -> None:
        ms = MagicMock()
        ms.get_calorie_entries = AsyncMock(side_effect=OSError("x"))
        with patch("agent.fitness.tools.get_fitness_storage", return_value=ms):
            r = await list_calories(mock_tool_context)
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_calorie_stats_no_user(
        self, mock_tool_context_no_user: ToolContext
    ) -> None:
        r = await get_calorie_stats(mock_tool_context_no_user)
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_calorie_stats_storage_error(
        self, mock_tool_context: ToolContext
    ) -> None:
        ms = MagicMock()
        ms.get_calorie_stats = AsyncMock(side_effect=RuntimeError("x"))
        with patch("agent.fitness.tools.get_fitness_storage", return_value=ms):
            r = await get_calorie_stats(mock_tool_context)
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_log_workout_no_user(
        self, mock_tool_context_no_user: ToolContext
    ) -> None:
        r = await log_workout(mock_tool_context_no_user, "Run")
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_log_workout_detail_string_variants(
        self, mock_tool_context: ToolContext
    ) -> None:
        ms = MagicMock()
        ms.add_workout_entry = AsyncMock(return_value=1)
        with patch("agent.fitness.tools.get_fitness_storage", return_value=ms):
            r = await log_workout(
                mock_tool_context,
                "Run",
                exercise_type="cardio",
                duration_minutes=30,
                distance_km=5.0,
            )
        assert r["status"] == "success"
        assert "30min" in r["message"]
        assert "5.0km" in r["message"]

    @pytest.mark.asyncio
    async def test_log_workout_storage_error(
        self, mock_tool_context: ToolContext
    ) -> None:
        ms = MagicMock()
        ms.add_workout_entry = AsyncMock(side_effect=RuntimeError("x"))
        with patch("agent.fitness.tools.get_fitness_storage", return_value=ms):
            r = await log_workout(mock_tool_context, "x")
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_list_workouts_no_user(
        self, mock_tool_context_no_user: ToolContext
    ) -> None:
        r = await list_workouts(mock_tool_context_no_user)
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_list_workouts_empty_entries(
        self, mock_tool_context: ToolContext
    ) -> None:
        ms = MagicMock()
        ms.get_workout_entries = AsyncMock(return_value=[])
        with patch("agent.fitness.tools.get_fitness_storage", return_value=ms):
            r = await list_workouts(mock_tool_context)
        assert r["entries"] == []

    @pytest.mark.asyncio
    async def test_list_workouts_storage_error(
        self, mock_tool_context: ToolContext
    ) -> None:
        ms = MagicMock()
        ms.get_workout_entries = AsyncMock(side_effect=RuntimeError("x"))
        with patch("agent.fitness.tools.get_fitness_storage", return_value=ms):
            r = await list_workouts(mock_tool_context)
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_workout_stats_no_user(
        self, mock_tool_context_no_user: ToolContext
    ) -> None:
        r = await get_workout_stats(mock_tool_context_no_user)
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_workout_stats_storage_error(
        self, mock_tool_context: ToolContext
    ) -> None:
        ms = MagicMock()
        ms.get_workout_stats = AsyncMock(side_effect=RuntimeError("x"))
        with patch("agent.fitness.tools.get_fitness_storage", return_value=ms):
            r = await get_workout_stats(mock_tool_context)
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_delete_fitness_no_user(
        self, mock_tool_context_no_user: ToolContext
    ) -> None:
        r = await delete_fitness_entry(mock_tool_context_no_user, "calorie", 1)
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_delete_fitness_not_deleted(
        self, mock_tool_context: ToolContext
    ) -> None:
        ms = MagicMock()
        ms.delete_entry = AsyncMock(return_value=False)
        with patch("agent.fitness.tools.get_fitness_storage", return_value=ms):
            r = await delete_fitness_entry(mock_tool_context, "calorie", 9)
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_delete_fitness_storage_error(
        self, mock_tool_context: ToolContext
    ) -> None:
        ms = MagicMock()
        ms.delete_entry = AsyncMock(side_effect=RuntimeError("x"))
        with patch("agent.fitness.tools.get_fitness_storage", return_value=ms):
            r = await delete_fitness_entry(mock_tool_context, "workout", 1)
        assert r["status"] == "error"


class TestYoutubeTranscriptErrors:
    def test_video_unavailable(self) -> None:
        from youtube_transcript_api import VideoUnavailable

        mock_inst = MagicMock()
        mock_inst.list.side_effect = VideoUnavailable("x")
        with patch(
            "youtube_transcript_api.YouTubeTranscriptApi", return_value=mock_inst
        ):
            r = get_youtube_transcript(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
                "dQw4w9WgXcQ",
            )
        assert r["status"] == "error"
        assert "unavailable" in r["message"].lower()

    def test_transcripts_disabled(self) -> None:
        from youtube_transcript_api import TranscriptsDisabled

        mock_inst = MagicMock()
        mock_inst.list.side_effect = TranscriptsDisabled("x")
        with patch(
            "youtube_transcript_api.YouTubeTranscriptApi", return_value=mock_inst
        ):
            r = get_youtube_transcript(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
                "dQw4w9WgXcQ",
            )
        assert r["status"] == "error"

    def test_no_transcript_found(self) -> None:
        from youtube_transcript_api import NoTranscriptFound

        mock_inst = MagicMock()
        mock_inst.list.side_effect = NoTranscriptFound(
            "dQw4w9WgXcQ",
            ["zz"],
            MagicMock(),
        )
        with patch(
            "youtube_transcript_api.YouTubeTranscriptApi", return_value=mock_inst
        ):
            r = get_youtube_transcript(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
                "dQw4w9WgXcQ",
                language="zz",
            )
        assert r["status"] == "error"

    def test_stop_iteration_empty_transcripts(self) -> None:
        mock_list = MagicMock()
        mock_list.__iter__ = lambda self: iter([])
        mock_inst = MagicMock()
        mock_inst.list.return_value = mock_list
        with patch(
            "youtube_transcript_api.YouTubeTranscriptApi", return_value=mock_inst
        ):
            r = get_youtube_transcript(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
                "dQw4w9WgXcQ",
            )
        assert r["status"] == "error"

    def test_generic_transcript_error(self) -> None:
        mock_inst = MagicMock()
        mock_inst.list.side_effect = KeyError("x")
        with patch(
            "youtube_transcript_api.YouTubeTranscriptApi", return_value=mock_inst
        ):
            r = get_youtube_transcript(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
                "dQw4w9WgXcQ",
            )
        assert r["status"] == "error"


class TestContextFileErrors:
    def test_symlink_escape_rejected(self, tmp_path: Path) -> None:
        ctx = tmp_path / "cctx"
        ctx.mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("nope", encoding="utf-8")
        try:
            (ctx / "link.md").symlink_to(secret)
        except OSError:
            pytest.skip("symlinks not supported")
        with patch("agent.tools.context_files.get_context_dir", return_value=ctx):
            r = read_context_file(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
                "link.md",
            )
        assert r["status"] == "error"
        assert "within" in r["message"]

    def test_read_io_error(self, tmp_path: Path) -> None:
        ctx = tmp_path / "rctx"
        ctx.mkdir()
        p = ctx / "R.md"
        p.write_text("ok", encoding="utf-8")

        def _bad_read(*_a: object, **_k: object) -> str:
            raise OSError("io")

        with (
            patch("agent.tools.context_files.get_context_dir", return_value=ctx),
            patch.object(Path, "read_text", _bad_read),
        ):
            r = read_context_file(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
                "R.md",
            )
        assert r["status"] == "error"

    def test_write_io_error(self, tmp_path: Path) -> None:
        ctx = tmp_path / "wctx"
        ctx.mkdir()

        def _bad_write(*_a: object, **_k: object) -> int:
            raise OSError("w")

        with (
            patch("agent.tools.context_files.get_context_dir", return_value=ctx),
            patch.object(Path, "write_text", _bad_write),
        ):
            r = write_context_file(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
                "W.md",
                "c",
            )
        assert r["status"] == "error"

    def test_delete_invalid_filename_returns_error(self, tmp_path: Path) -> None:
        ctx = tmp_path / "delctx-invalid"
        ctx.mkdir()
        with patch("agent.tools.context_files.get_context_dir", return_value=ctx):
            r = delete_context_file(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
                "",
            )
        assert r["status"] == "error"

    def test_delete_success_and_missing(self, tmp_path: Path) -> None:
        ctx = tmp_path / "dctx"
        ctx.mkdir()
        with patch("agent.tools.context_files.get_context_dir", return_value=ctx):
            write_context_file(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
                "D.md",
                "x",
            )
            r_ok = delete_context_file(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
                "D.md",
            )
            assert r_ok["status"] == "success"
            r_miss = delete_context_file(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
                "D.md",
            )
            assert r_miss["status"] == "error"

    def test_delete_io_error(self, tmp_path: Path) -> None:
        ctx = tmp_path / "dctx2"
        ctx.mkdir()
        f = ctx / "E.md"
        f.write_text("z", encoding="utf-8")

        def _bad_unlink(*_a: object, **_k: object) -> None:
            raise OSError("u")

        with (
            patch("agent.tools.context_files.get_context_dir", return_value=ctx),
            patch.object(Path, "unlink", _bad_unlink),
        ):
            r = delete_context_file(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
                "E.md",
            )
        assert r["status"] == "error"

    def test_list_context_io_error(self, tmp_path: Path) -> None:
        ctx = tmp_path / "lctx"
        ctx.mkdir()
        (ctx / "a.md").write_text("x", encoding="utf-8")

        def _bad_iterdir(*_a: object, **_k: object) -> object:
            raise OSError("list")

        with (
            patch("agent.tools.context_files.get_context_dir", return_value=ctx),
            patch.object(Path, "iterdir", _bad_iterdir),
        ):
            r = list_context_files(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
            )
        assert r["status"] == "error"


class TestClaudeWorkdirResolution:
    """Tests for _resolve_claude_workdir edge cases."""

    def test_returns_cwd_when_requested_path_not_directory(self) -> None:
        """Non-existent directory should fall back to cwd."""
        from agent.tools.claude_coding import _resolve_claude_workdir

        with patch.object(Path, "is_dir", return_value=False):
            result = _resolve_claude_workdir("/nonexistent/path")

        assert result == str(Path.cwd())

    def test_returns_requested_path_when_directory_exists(self) -> None:
        """Valid directory should be returned as-is."""
        from agent.tools.claude_coding import _resolve_claude_workdir

        with patch.object(Path, "is_dir", return_value=True):
            result = _resolve_claude_workdir("/valid/path")

        assert result == "/valid/path"

    def test_uses_default_when_workdir_is_none(self) -> None:
        """None workdir should use default path."""
        from agent.tools.claude_coding import _resolve_claude_workdir

        with patch.object(Path, "is_dir", return_value=True):
            result = _resolve_claude_workdir(None)

        assert result == "/home/app/garbanzo-home/workspace"


class TestSplitPlainTextForTelegram:
    """Tests for _split_plain_text_for_telegram edge cases."""

    def test_returns_empty_list_for_empty_text(self) -> None:
        """Empty input should return empty list."""
        from agent.tools.claude_coding import _split_plain_text_for_telegram

        result = _split_plain_text_for_telegram("")
        assert result == []

    def test_returns_empty_list_for_none_text(self) -> None:
        """None-like input should return empty list."""
        from agent.tools.claude_coding import _split_plain_text_for_telegram

        result = _split_plain_text_for_telegram("")
        assert result == []


class TestSendBackgroundClaudeJobResultEdgeCases:
    """Tests for _send_background_claude_job_result branches."""

    @pytest.mark.asyncio
    async def test_sends_stderr_when_present(self) -> None:
        """stderr should be included in output sections."""
        from agent.tools.claude_coding import _send_background_claude_job_result

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        mock_notification_service = MagicMock()
        mock_notification_service.configure_mock(_bot=mock_bot)
        type(mock_notification_service).bot = property(lambda self: mock_bot)

        with patch(
            "agent.tools.claude_coding.get_notification_service",
            return_value=mock_notification_service,
        ):
            await _send_background_claude_job_result(
                chat_id="12345",
                job_id="job-stderr",
                cwd="/app/workspace",
                result={
                    "status": "error",
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": "error details",
                    "truncated": False,
                },
            )

        # Should have sent summary and stderr
        assert mock_bot.send_message.call_count == 2
        stderr_call = mock_bot.send_message.call_args_list[1]
        assert "stderr" in stderr_call.kwargs["text"]

    @pytest.mark.asyncio
    async def test_sends_truncated_message_when_output_truncated(self) -> None:
        """Truncated output should be indicated in summary."""
        from agent.tools.claude_coding import _send_background_claude_job_result

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        mock_notification_service = MagicMock()
        mock_notification_service.configure_mock(_bot=mock_bot)
        type(mock_notification_service).bot = property(lambda self: mock_bot)

        with patch(
            "agent.tools.claude_coding.get_notification_service",
            return_value=mock_notification_service,
        ):
            await _send_background_claude_job_result(
                chat_id="12345",
                job_id="job-truncated",
                cwd="/app/workspace",
                result={
                    "status": "success",
                    "exit_code": 0,
                    "stdout": "very long output",
                    "truncated": True,
                },
            )

        # Summary should mention truncation
        summary_call = mock_bot.send_message.call_args_list[0]
        assert "truncated" in summary_call.kwargs["text"].lower()

    @pytest.mark.asyncio
    async def test_sends_error_message_when_no_stdout_stderr(self) -> None:
        """Error message should be sent when no stdout/stderr."""
        from agent.tools.claude_coding import _send_background_claude_job_result

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        mock_notification_service = MagicMock()
        mock_notification_service.configure_mock(_bot=mock_bot)
        type(mock_notification_service).bot = property(lambda self: mock_bot)

        with patch(
            "agent.tools.claude_coding.get_notification_service",
            return_value=mock_notification_service,
        ):
            await _send_background_claude_job_result(
                chat_id="12345",
                job_id="job-errmsg",
                cwd="/app/workspace",
                result={
                    "status": "error",
                    "message": "Something went wrong",
                },
            )

        # Should have sent summary and error message
        assert mock_bot.send_message.call_count == 2
        error_call = mock_bot.send_message.call_args_list[1]
        assert "Something went wrong" in error_call.kwargs["text"]

    @pytest.mark.asyncio
    async def test_bot_unavailable_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should log warning and return early when bot is unavailable."""
        import logging

        from agent.tools.claude_coding import _send_background_claude_job_result

        caplog.set_level(logging.WARNING, logger="agent.tools")

        mock_notification_service = MagicMock()
        mock_notification_service._bot = None

        with patch(
            "agent.tools.claude_coding.get_notification_service",
            return_value=mock_notification_service,
        ):
            await _send_background_claude_job_result(
                chat_id="12345",
                job_id="job-nobot",
                cwd="/app/workspace",
                result={"status": "success"},
            )

        assert any("Telegram bot is unavailable" in r.message for r in caplog.records)


class TestRunBackgroundClaudeJobException:
    """Tests for _run_background_claude_job exception handling."""

    @pytest.mark.asyncio
    async def test_logs_exception_when_send_fails(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should log exception when sending result fails."""
        import logging

        from agent.tools.claude_coding import _run_background_claude_job

        caplog.set_level(logging.ERROR, logger="agent.tools")

        async def mock_execute(
            *, prompt: str, cwd: str, env: dict[str, str]
        ) -> dict[str, Any]:
            return {"status": "success"}

        async def mock_send(
            *, chat_id: str, job_id: str, cwd: str, result: dict[str, Any]
        ) -> None:
            raise RuntimeError("Send failed")

        with (
            patch(
                "agent.tools.claude_coding._execute_claude_coding_subprocess",
                side_effect=mock_execute,
            ),
            patch(
                "agent.tools.claude_coding._send_background_claude_job_result",
                side_effect=mock_send,
            ),
        ):
            await _run_background_claude_job(
                chat_id="12345",
                job_id="job-fail",
                prompt="test prompt",
                cwd="/app/workspace",
                env={},
            )

        assert any(
            "Failed to send Claude job completion" in r.message for r in caplog.records
        )


class TestStartBackgroundClaudeJob:
    """Tests for _start_background_claude_job function."""

    @pytest.mark.asyncio
    async def test_starts_job_and_returns_job_id(self) -> None:
        """Should start background job and return a job ID."""

        from agent.tools.claude_coding import (
            _ACTIVE_BACKGROUND_CLAUDE_JOBS,
            _start_background_claude_job,
        )

        async def mock_execute(
            *, prompt: str, cwd: str, env: dict[str, str]
        ) -> dict[str, Any]:
            return {"status": "success"}

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        mock_notification_service = MagicMock()
        mock_notification_service._bot = mock_bot
        mock_notification_service.bot = mock_bot

        with (
            patch(
                "agent.tools.claude_coding._execute_claude_coding_subprocess",
                side_effect=mock_execute,
            ),
            patch(
                "agent.telegram.notifications.get_notification_service",
                return_value=mock_notification_service,
            ),
        ):
            job_id = _start_background_claude_job(
                chat_id="12345",
                prompt="test prompt",
                cwd="/app/workspace",
                env={},
            )

        # Job ID should be 8 characters (hex)
        assert len(job_id) == 8
        assert job_id in _ACTIVE_BACKGROUND_CLAUDE_JOBS

        # Wait for the background task to complete
        task = _ACTIVE_BACKGROUND_CLAUDE_JOBS[job_id]
        await task
        await asyncio.sleep(0.01)

        # Job should be cleaned up
        assert job_id not in _ACTIVE_BACKGROUND_CLAUDE_JOBS


class TestTrackBackgroundClaudeJob:
    """Tests for _track_background_claude_job callback."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_job_from_active_dict(self) -> None:
        """Completed task should be removed from active jobs dict."""

        from agent.tools.claude_coding import (
            _ACTIVE_BACKGROUND_CLAUDE_JOBS,
            _track_background_claude_job,
        )

        job_id = "test-cleanup-job"
        task = asyncio.create_task(asyncio.sleep(0.01))

        _track_background_claude_job(job_id, task)
        assert job_id in _ACTIVE_BACKGROUND_CLAUDE_JOBS

        await task
        # Give callback a moment to run
        await asyncio.sleep(0.01)

        assert job_id not in _ACTIVE_BACKGROUND_CLAUDE_JOBS

    @pytest.mark.asyncio
    async def test_cleanup_handles_cancelled_task(self) -> None:
        """Cancelled task cleanup should not raise."""

        from agent.tools.claude_coding import (
            _ACTIVE_BACKGROUND_CLAUDE_JOBS,
            _track_background_claude_job,
        )

        job_id = "test-cancel-job"

        async def cancelable_task() -> None:
            await asyncio.sleep(10)

        task = asyncio.create_task(cancelable_task())

        _track_background_claude_job(job_id, task)
        assert job_id in _ACTIVE_BACKGROUND_CLAUDE_JOBS

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        # Give callback a moment to run
        await asyncio.sleep(0.01)

        assert job_id not in _ACTIVE_BACKGROUND_CLAUDE_JOBS
