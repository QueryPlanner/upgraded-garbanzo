"""Tests for telegram file outbox (queued document sends)."""

import asyncio
from collections.abc import Generator
from pathlib import Path

import pytest

from agent.utils import telegram_outbox as telegram_outbox_mod
from agent.utils.telegram_outbox import (
    PendingTelegramFile,
    TelegramFileOutboxError,
    begin_telegram_file_batch,
    discard_telegram_staging_files,
    end_telegram_file_batch,
    register_telegram_file_for_send,
)


@pytest.fixture(autouse=True)
def _reset_telegram_outbox_context() -> Generator[None]:
    """Avoid leaked batch ids from other test modules in the same session."""
    telegram_outbox_mod._batch_id_var.set(None)
    yield
    telegram_outbox_mod._batch_id_var.set(None)


class TestTelegramFileOutbox:
    def test_register_requires_active_batch(self, tmp_path: Path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("x", encoding="utf-8")
        with pytest.raises(TelegramFileOutboxError, match="inactive"):
            register_telegram_file_for_send(f, None)

    def test_begin_register_end_roundtrip(self, tmp_path: Path) -> None:
        f = tmp_path / "b.txt"
        f.write_text("y", encoding="utf-8")
        begin_telegram_file_batch()
        register_telegram_file_for_send(f, caption="hi", filename="b.txt")
        pending = end_telegram_file_batch()
        assert len(pending) == 1
        assert pending[0].caption == "hi"
        assert pending[0].filename == "b.txt"
        assert pending[0].path == f

    def test_end_without_begin_returns_empty(self) -> None:
        assert end_telegram_file_batch() == []

    def test_register_fails_when_batch_bucket_missing(self, tmp_path: Path) -> None:
        """Corrupted state: batch id set but bucket was removed."""
        begin_telegram_file_batch()
        batch_id = telegram_outbox_mod._batch_id_var.get()
        assert batch_id is not None
        with telegram_outbox_mod._lock:
            del telegram_outbox_mod._batches[batch_id]
        f = tmp_path / "orphan.txt"
        f.write_text("x", encoding="utf-8")
        with pytest.raises(TelegramFileOutboxError, match="invalid or ended"):
            register_telegram_file_for_send(f, None)
        telegram_outbox_mod._batch_id_var.set(None)

    def test_max_files_per_batch(self, tmp_path: Path) -> None:
        begin_telegram_file_batch()
        for i in range(10):
            p = tmp_path / f"f{i}.txt"
            p.write_text("z", encoding="utf-8")
            register_telegram_file_for_send(p, None)
        extra = tmp_path / "extra.txt"
        extra.write_text("z", encoding="utf-8")
        with pytest.raises(TelegramFileOutboxError, match="At most"):
            register_telegram_file_for_send(extra, None)
        end_telegram_file_batch()

    def test_discard_removes_files(self, tmp_path: Path) -> None:
        f = tmp_path / "gone.txt"
        f.write_text("z", encoding="utf-8")
        discard_telegram_staging_files(
            [PendingTelegramFile(path=f, caption=None, filename=None)]
        )
        assert not f.exists()

    @pytest.mark.asyncio
    async def test_concurrent_tasks_isolated_batches(self, tmp_path: Path) -> None:
        """Each asyncio Task gets its own contextvar batch id."""

        async def worker(suffix: str) -> list[PendingTelegramFile]:
            begin_telegram_file_batch()
            p = tmp_path / f"w{suffix}.txt"
            p.write_text(suffix, encoding="utf-8")
            register_telegram_file_for_send(p, None)
            return end_telegram_file_batch()

        results = await asyncio.gather(worker("a"), worker("b"))
        assert len(results[0]) == 1
        assert len(results[1]) == 1
        assert results[0][0].path.name.startswith("wa")
