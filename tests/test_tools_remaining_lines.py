"""Line coverage for remaining branches in ``agent.tools``."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
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
        with patch("agent.tools.get_fitness_storage", return_value=ms):
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
        with patch("agent.tools.get_fitness_storage", return_value=ms):
            r = await list_calories(mock_tool_context, meal_type="lunch")
        assert r["count"] == 1

    @pytest.mark.asyncio
    async def test_list_calories_storage_error(
        self, mock_tool_context: ToolContext
    ) -> None:
        ms = MagicMock()
        ms.get_calorie_entries = AsyncMock(side_effect=OSError("x"))
        with patch("agent.tools.get_fitness_storage", return_value=ms):
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
        with patch("agent.tools.get_fitness_storage", return_value=ms):
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
        with patch("agent.tools.get_fitness_storage", return_value=ms):
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
        with patch("agent.tools.get_fitness_storage", return_value=ms):
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
        with patch("agent.tools.get_fitness_storage", return_value=ms):
            r = await list_workouts(mock_tool_context)
        assert r["entries"] == []

    @pytest.mark.asyncio
    async def test_list_workouts_storage_error(
        self, mock_tool_context: ToolContext
    ) -> None:
        ms = MagicMock()
        ms.get_workout_entries = AsyncMock(side_effect=RuntimeError("x"))
        with patch("agent.tools.get_fitness_storage", return_value=ms):
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
        with patch("agent.tools.get_fitness_storage", return_value=ms):
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
        with patch("agent.tools.get_fitness_storage", return_value=ms):
            r = await delete_fitness_entry(mock_tool_context, "calorie", 9)
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_delete_fitness_storage_error(
        self, mock_tool_context: ToolContext
    ) -> None:
        ms = MagicMock()
        ms.delete_entry = AsyncMock(side_effect=RuntimeError("x"))
        with patch("agent.tools.get_fitness_storage", return_value=ms):
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
        with patch("agent.tools.get_context_dir", return_value=ctx):
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
            patch("agent.tools.get_context_dir", return_value=ctx),
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
            patch("agent.tools.get_context_dir", return_value=ctx),
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
        with patch("agent.tools.get_context_dir", return_value=ctx):
            r = delete_context_file(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
                "",
            )
        assert r["status"] == "error"

    def test_delete_success_and_missing(self, tmp_path: Path) -> None:
        ctx = tmp_path / "dctx"
        ctx.mkdir()
        with patch("agent.tools.get_context_dir", return_value=ctx):
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
            patch("agent.tools.get_context_dir", return_value=ctx),
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
            patch("agent.tools.get_context_dir", return_value=ctx),
            patch.object(Path, "iterdir", _bad_iterdir),
        ):
            r = list_context_files(
                MockToolContext(state=MockState({})),  # type: ignore[arg-type]
            )
        assert r["status"] == "error"
