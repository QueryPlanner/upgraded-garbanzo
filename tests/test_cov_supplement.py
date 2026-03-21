"""Targeted tests to reach full coverage on measured ``src/agent`` sources."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from apscheduler.triggers.cron import CronTrigger  # type: ignore
from google.adk.apps import App

from agent.fitness import (
    CalorieEntry,
    ExerciseType,
    FitnessStorage,
    MealType,
    WorkoutEntry,
)
from agent.reminders.recurrence import get_next_trigger_time
from agent.reminders.scheduler import (
    ReminderScheduler,
    _parse_stored_trigger_time,
    get_scheduler,
)
from agent.reminders.storage import (
    Reminder,
    ReminderStorage,
    close_shared_reminder_storage,
)
from agent.skills.loader import SkillParseError, get_available_skills, parse_skill_file
from agent.utils.config import SessionConfig, get_data_dir
from agent.utils.pg_app_pool import postgres_dsn_from_environment
from agent.utils.session import create_session_service_for_runner


class TestSessionFactoryInMemoryPaths:
    def test_in_memory_when_no_session_uri_configured(self) -> None:
        cfg = SessionConfig.model_validate(
            {"ADK_USE_DATABASE_SESSION": "true"},
        )
        svc = create_session_service_for_runner(config=cfg)
        from google.adk.sessions.in_memory_session_service import (
            InMemorySessionService,
        )

        assert isinstance(svc, InMemorySessionService)

    def test_default_agents_dir_when_none_passed(self) -> None:
        cfg = SessionConfig.model_validate(
            {
                "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
                "ADK_USE_DATABASE_SESSION": "true",
            }
        )
        mock_service = MagicMock()
        with patch(
            "google.adk.cli.utils.service_factory.create_session_service_from_options",
            return_value=mock_service,
        ) as factory:
            svc = create_session_service_for_runner(config=cfg, agents_dir=None)
        assert svc is mock_service
        assert "base_dir" in factory.call_args.kwargs


class TestRecurrenceEdge:
    def test_get_next_trigger_time_raises_when_no_fire(self) -> None:
        real = CronTrigger.from_crontab("0 * * * *", timezone=ZoneInfo("UTC"))
        fake = MagicMock()
        fake.get_next_fire_time.return_value = None
        with (
            patch(
                "agent.reminders.recurrence.CronTrigger.from_crontab",
                side_effect=[real, fake],
            ),
            pytest.raises(ValueError, match="no future fire time"),
        ):
            get_next_trigger_time("0 * * * *", "UTC")

    def test_get_next_trigger_time_fills_tz_when_next_fire_naive(self) -> None:
        """Cover branch when APScheduler returns a naive next fire datetime."""
        real = CronTrigger.from_crontab("0 * * * *", timezone=ZoneInfo("UTC"))
        mock_trigger = MagicMock()
        mock_trigger.get_next_fire_time.return_value = datetime(2026, 6, 1, 12, 0, 0)
        with patch(
            "agent.reminders.recurrence.CronTrigger.from_crontab",
            side_effect=[real, mock_trigger],
        ):
            out = get_next_trigger_time(
                "0 * * * *",
                "UTC",
                reference_time=datetime(2026, 6, 1, 11, 0, 0, tzinfo=UTC),
            )
        assert out.tzinfo == UTC


class TestSchedulerPrivateHelpers:
    def test_parse_stored_trigger_time_assumes_utc_when_naive_iso(self) -> None:
        parsed = _parse_stored_trigger_time("2026-01-01T12:00:00")
        assert parsed.tzinfo == UTC
        assert parsed.hour == 12

    def test_parse_stored_trigger_time_normalizes_offset_to_utc(self) -> None:
        parsed = _parse_stored_trigger_time("2026-01-01T12:00:00+05:30")
        assert parsed.tzinfo == UTC

    @pytest.mark.asyncio
    async def test_complete_reminder_delivery_requires_id(self) -> None:
        scheduler = ReminderScheduler()
        reminder = Reminder(
            id=None,
            user_id="u",
            message="m",
            trigger_time="2026-01-01T12:00:00+00:00",
            is_sent=False,
            created_at="2026-01-01T10:00:00",
        )
        with pytest.raises(ValueError, match="must have an ID"):
            await scheduler._complete_reminder_delivery(reminder)


class TestSessionFactoryPostgres:
    def test_uses_create_session_service_when_uri_configured(
        self, tmp_path: Path
    ) -> None:
        agents_dir = tmp_path / "adk-agents"
        agents_dir.mkdir()
        cfg = SessionConfig.model_validate(
            {
                "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
                "ADK_USE_DATABASE_SESSION": "true",
            }
        )
        mock_service = MagicMock()
        with patch(
            "google.adk.cli.utils.service_factory.create_session_service_from_options",
            return_value=mock_service,
        ) as factory:
            svc = create_session_service_for_runner(
                config=cfg, agents_dir=str(agents_dir)
            )
        assert svc is mock_service
        factory.assert_called_once()
        call_kw = factory.call_args.kwargs
        assert call_kw["base_dir"] == str(agents_dir)
        assert call_kw["session_service_uri"].startswith("postgresql+asyncpg://")


class TestPgPoolValidationError:
    def test_postgres_dsn_none_on_invalid_session_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/db")
        monkeypatch.setenv("DB_POOL_SIZE", "not-a-number")
        assert postgres_dsn_from_environment() is None


class TestSessionConfigUriBranches:
    def test_asyncpg_session_uri_keeps_agent_engine_scheme(self) -> None:
        cfg = SessionConfig.model_validate({"AGENT_ENGINE": "my-id"})
        assert cfg.asyncpg_session_uri == "agentengine://my-id"

    def test_effective_asyncpg_dsn_none_for_non_postgres_url(self) -> None:
        cfg = SessionConfig.model_validate({"DATABASE_URL": "sqlite:///tmp/x.db"})
        assert cfg.effective_asyncpg_dsn is None


class TestDataDirMigration:
    def test_migrates_legacy_db_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import agent.utils.config as cfgmod

        legacy = tmp_path / "legacy_home"
        legacy.mkdir()
        (legacy / "reminders.db").write_text("legacy", encoding="utf-8")
        new_dir = tmp_path / "agent_data"
        new_dir.mkdir()

        monkeypatch.setenv("AGENT_DATA_DIR", str(new_dir))
        monkeypatch.setattr(cfgmod, "LEGACY_DATA_DIR", legacy)

        data_dir = get_data_dir()
        assert (data_dir / "reminders.db").exists()
        assert (data_dir / ".migrated").exists()

    def test_skips_migration_when_target_has_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import agent.utils.config as cfgmod

        legacy = tmp_path / "legacy2"
        legacy.mkdir()
        (legacy / "a.db").write_text("x", encoding="utf-8")
        new_dir = tmp_path / "agent_data2"
        new_dir.mkdir()
        (new_dir / "existing.db").write_text("y", encoding="utf-8")

        monkeypatch.setenv("AGENT_DATA_DIR", str(new_dir))
        monkeypatch.setattr(cfgmod, "LEGACY_DATA_DIR", legacy)

        get_data_dir()
        assert not (new_dir / "a.db").exists()

    def test_legacy_empty_marks_migrated_without_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import agent.utils.config as cfgmod

        legacy = tmp_path / "legacy3"
        legacy.mkdir()
        new_dir = tmp_path / "agent_data3"
        new_dir.mkdir()

        monkeypatch.setenv("AGENT_DATA_DIR", str(new_dir))
        monkeypatch.setattr(cfgmod, "LEGACY_DATA_DIR", legacy)

        get_data_dir()
        assert (new_dir / ".migrated").exists()


class TestReminderStorageInternals:
    @pytest.mark.asyncio
    async def test_require_conn_before_initialize(self, tmp_path: Path) -> None:
        storage = ReminderStorage(db_path=tmp_path / "r.db")
        with pytest.raises(RuntimeError, match="not initialized"):
            storage._require_conn()

    @pytest.mark.asyncio
    async def test_get_user_reminders_include_sent(self, tmp_path: Path) -> None:
        db = tmp_path / "rs.db"
        storage = ReminderStorage(db_path=db)
        await storage.initialize()
        rid = await storage.add_reminder(
            Reminder(
                user_id="u1",
                message="m",
                trigger_time="2020-01-01T00:00:00",
                created_at="2020-01-01T00:00:00",
            )
        )
        await storage.mark_sent(rid)
        active = await storage.get_user_reminders("u1", include_sent=False)
        assert active == []
        all_rows = await storage.get_user_reminders("u1", include_sent=True)
        assert len(all_rows) == 1
        await storage.close()

    @pytest.mark.asyncio
    async def test_close_shared_reminder_storage_no_singleton(self) -> None:
        import agent.reminders.storage as st

        st._storage = None
        await close_shared_reminder_storage()


class TestFitnessStorageInternals:
    @pytest.mark.asyncio
    async def test_close_idempotent(self, tmp_path: Path) -> None:
        db = tmp_path / "f.db"
        store = FitnessStorage(db_path=db)
        await store.initialize()
        await store.close()
        await store.close()

    @pytest.mark.asyncio
    async def test_require_conn_before_initialize(self, tmp_path: Path) -> None:
        store = FitnessStorage(db_path=tmp_path / "g.db")
        with pytest.raises(RuntimeError, match="not initialized"):
            store._require_conn()

    @pytest.mark.asyncio
    async def test_calorie_entries_end_date_filter(self, tmp_path: Path) -> None:
        store = FitnessStorage(db_path=tmp_path / "c.db")
        await store.initialize()
        for d, food in [("2026-03-10", "A"), ("2026-03-20", "B")]:
            await store.add_calorie_entry(
                CalorieEntry(
                    user_id="u",
                    date=d,
                    food_item=food,
                    calories=100,
                    meal_type=MealType.SNACK,
                    created_at=datetime.now(UTC).isoformat(),
                )
            )
        rows = await store.get_calorie_entries("u", end_date="2026-03-15")
        assert len(rows) == 1
        assert rows[0].food_item == "A"
        await store.close()

    @pytest.mark.asyncio
    async def test_workout_entries_date_range(self, tmp_path: Path) -> None:
        store = FitnessStorage(db_path=tmp_path / "w.db")
        await store.initialize()
        await store.add_workout_entry(
            WorkoutEntry(
                user_id="u",
                date="2026-01-01",
                exercise_type=ExerciseType.CARDIO,
                exercise_name="Run",
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        await store.add_workout_entry(
            WorkoutEntry(
                user_id="u",
                date="2026-06-01",
                exercise_type=ExerciseType.CARDIO,
                exercise_name="Swim",
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        rows = await store.get_workout_entries(
            "u", start_date="2026-03-01", end_date="2026-12-31"
        )
        assert len(rows) == 1
        assert rows[0].exercise_name == "Swim"
        await store.close()

    @pytest.mark.asyncio
    async def test_workout_stats_picks_heavier_pr(self, tmp_path: Path) -> None:
        store = FitnessStorage(db_path=tmp_path / "pr.db")
        await store.initialize()
        created = datetime.now(UTC).isoformat()
        await store.add_workout_entry(
            WorkoutEntry(
                user_id="u",
                date="2026-03-15",
                exercise_type=ExerciseType.STRENGTH,
                exercise_name="Bench Press",
                weight=60.0,
                created_at=created,
            )
        )
        await store.add_workout_entry(
            WorkoutEntry(
                user_id="u",
                date="2026-03-15",
                exercise_type=ExerciseType.STRENGTH,
                exercise_name="Bench Press",
                weight=90.0,
                created_at=created,
            )
        )
        stats = await store.get_workout_stats("u")
        assert stats["personal_records"][0]["weight_kg"] == 90.0
        await store.close()


class TestSchedulerEmptyDue:
    @pytest.mark.asyncio
    async def test_check_returns_when_no_due_reminders(self, tmp_path: Path) -> None:
        db = tmp_path / "nodue.db"
        storage = ReminderStorage(db_path=db)
        await storage.initialize()
        scheduler = ReminderScheduler()
        scheduler.storage = storage
        await scheduler._check_and_send_reminders()
        await storage.close()


class TestSchedulerCheckDueLoop:
    @pytest.mark.asyncio
    async def test_processes_non_empty_due_list(self, tmp_path: Path) -> None:
        db = tmp_path / "due.db"
        storage = ReminderStorage(db_path=db)
        await storage.initialize()
        scheduler = ReminderScheduler()
        scheduler.storage = storage
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        scheduler.set_bot(mock_bot)
        due = Reminder(
            id=1,
            user_id="u",
            message="m",
            trigger_time="2020-01-01T00:00:00",
            is_sent=False,
            created_at="2020-01-01T00:00:00",
        )
        with patch.object(
            storage,
            "get_due_reminders",
            new_callable=AsyncMock,
            return_value=[due],
        ):
            await scheduler._check_and_send_reminders()
        mock_bot.send_message.assert_called_once()
        await storage.close()


class TestSchedulerBranches:
    @pytest.mark.asyncio
    async def test_check_reminders_swallows_storage_errors(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "sch.db"
        storage = ReminderStorage(db_path=db)
        await storage.initialize()
        scheduler = ReminderScheduler()
        scheduler.storage = storage
        with patch.object(
            storage,
            "get_due_reminders",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db down"),
        ):
            await scheduler._check_and_send_reminders()
        await storage.close()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self) -> None:
        scheduler = ReminderScheduler()
        await scheduler.stop()

    def test_get_scheduler_singleton(self) -> None:
        import agent.reminders.scheduler as sch

        sch._scheduler = None
        first = get_scheduler()
        second = get_scheduler()
        assert first is second

    @pytest.mark.asyncio
    async def test_send_reminder_parses_naive_trigger_time(self) -> None:
        scheduler = ReminderScheduler()
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        scheduler.set_bot(mock_bot)
        storage = MagicMock()
        storage.mark_sent = AsyncMock(return_value=None)
        scheduler.storage = storage
        reminder = Reminder(
            id=9,
            user_id="u",
            message="hi",
            trigger_time="2026-03-15T10:00:00",
            is_sent=False,
            created_at="2026-03-15T09:00:00",
        )
        await scheduler._send_reminder(reminder)
        mock_bot.send_message.assert_called_once()


class TestSkillsLoaderBranches:
    def test_parse_skill_invalid_yaml(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "bad-yaml"
        skill_dir.mkdir()
        path = skill_dir / "SKILL.md"
        path.write_text("---\n[\n---\nbody\n", encoding="utf-8")
        with pytest.raises(SkillParseError, match="Invalid YAML"):
            parse_skill_file(path)

    def test_parse_skill_missing_name(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "no-name"
        skill_dir.mkdir()
        path = skill_dir / "SKILL.md"
        path.write_text(
            "---\ndescription: only desc\n---\n\nbody\n",
            encoding="utf-8",
        )
        with pytest.raises(SkillParseError, match="Missing 'name'"):
            parse_skill_file(path)

    def test_parse_skill_missing_description(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "no-desc"
        skill_dir.mkdir()
        path = skill_dir / "SKILL.md"
        path.write_text(
            "---\nname: only-name\n---\n\nbody\n",
            encoding="utf-8",
        )
        with pytest.raises(SkillParseError, match="Missing 'description'"):
            parse_skill_file(path)

    def test_get_available_skills_logs_parse_errors(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        root = tmp_path / "skills"
        root.mkdir()
        bad = root / "bad"
        bad.mkdir()
        (bad / "SKILL.md").write_text("no frontmatter", encoding="utf-8")
        caplog.set_level("ERROR")
        skills = get_available_skills(root)
        assert skills == []
        assert "Failed to parse skill" in caplog.text

    def test_get_available_skills_skips_folder_without_skill_md(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        root = tmp_path / "skills2"
        root.mkdir()
        (root / "empty-dir").mkdir()
        caplog.set_level("DEBUG")
        assert get_available_skills(root) == []
        assert "No SKILL.md" in caplog.text


class TestTelegramHandlerAgentBranches:
    @pytest.mark.asyncio
    async def test_runner_with_agent_and_session_service(self) -> None:
        mock_agent = MagicMock()
        mock_agent.name = "agent"
        mock_runner = MagicMock()
        with patch("agent.telegram.handler.Runner", return_value=mock_runner):
            from agent.telegram.handler import TelegramHandler

            TelegramHandler(
                agent=mock_agent,
                app_name="custom",
                session_service=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_in_memory_runner_with_agent_only(self) -> None:
        mock_agent = MagicMock()
        mock_agent.name = "agent"
        with patch("agent.telegram.handler.InMemoryRunner") as im:
            im.return_value = MagicMock()
            from agent.telegram.handler import TelegramHandler

            TelegramHandler(agent=mock_agent, app_name="only-agent")
            im.assert_called_once()

    def test_requires_agent_or_app(self) -> None:
        from agent.telegram.handler import TelegramHandler

        with pytest.raises(ValueError, match="Either 'agent' or 'app'"):
            TelegramHandler(agent=None, app=None)


class TestTelegramHandlerAppBranches:
    @pytest.mark.asyncio
    async def test_initializes_runner_with_app_and_session_service(self) -> None:
        mock_agent = MagicMock()
        mock_agent.name = "agent"
        mock_app = MagicMock(spec=App)
        mock_app.root_agent = mock_agent
        mock_app.name = "from-app"

        mock_runner = MagicMock()
        with patch("agent.telegram.handler.Runner", return_value=mock_runner) as rc:
            from agent.telegram.handler import TelegramHandler

            svc = MagicMock()
            handler = TelegramHandler(app=mock_app, session_service=svc)
            assert handler.app_name == "from-app"
            rc.assert_called_once()
            assert handler.runner is mock_runner

    @pytest.mark.asyncio
    async def test_initializes_in_memory_runner_when_no_session_service(self) -> None:
        mock_agent = MagicMock()
        mock_app = MagicMock(spec=App)
        mock_app.root_agent = mock_agent
        mock_app.name = "app2"

        with patch("agent.telegram.handler.InMemoryRunner") as im:
            im.return_value = MagicMock()
            from agent.telegram.handler import TelegramHandler

            TelegramHandler(app=mock_app)
            im.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_message_latency_logs(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("TELEGRAM_LATENCY_LOG", "1")
        caplog.set_level("INFO")
        mock_agent = MagicMock()
        mock_agent.name = "a"
        from agent.telegram.handler import TelegramHandler

        handler = TelegramHandler(mock_agent, app_name="t")
        mock_runner = MagicMock()
        mock_runner.session_service = MagicMock()
        mock_runner.session_service.get_session = AsyncMock(return_value=None)
        mock_runner.session_service.create_session = AsyncMock(
            return_value=MagicMock(id="s", state={"user_id": "u1"})
        )

        async def empty_stream(**_: object) -> object:
            for _ in []:
                yield _

        mock_runner.run_async = empty_stream
        handler.runner = mock_runner

        await handler.process_message("u1", "hi")
        assert "telegram.pre_llm_latency" in caplog.text
        assert "telegram.adk_first_stream_event" in caplog.text

    @pytest.mark.asyncio
    async def test_process_message_delete_session_warning_on_failure(
        self,
    ) -> None:
        mock_agent = MagicMock()
        mock_agent.name = "a"
        from agent.telegram.handler import TelegramHandler

        handler = TelegramHandler(mock_agent, app_name="t")
        mock_runner = MagicMock()
        mock_runner.session_service = MagicMock()
        session = MagicMock()
        session.state = {}
        mock_runner.session_service.get_session = AsyncMock(return_value=session)
        mock_runner.session_service.delete_session = AsyncMock(
            side_effect=RuntimeError("nope")
        )
        mock_runner.session_service.create_session = AsyncMock(
            return_value=MagicMock(id="s", state={"user_id": "u"})
        )

        async def one_event(**_: object) -> object:
            yield MagicMock()

        mock_runner.run_async = one_event
        handler.runner = mock_runner

        await handler.process_message("u", "x")

    @pytest.mark.asyncio
    async def test_process_reminder_coerces_naive_scheduled_time(self) -> None:
        mock_agent = MagicMock()
        mock_agent.name = "a"
        from agent.telegram.handler import TelegramHandler

        handler = TelegramHandler(mock_agent, app_name="t")
        mock_runner = MagicMock()
        mock_runner.session_service = MagicMock()
        mock_runner.session_service.get_session = AsyncMock(return_value=None)
        mock_runner.session_service.create_session = AsyncMock(
            return_value=MagicMock(id="s", state={"user_id": "u"})
        )

        async def one_event(**_: object) -> object:
            yield MagicMock()

        mock_runner.run_async = one_event
        handler.runner = mock_runner

        await handler.process_reminder(
            user_id="u",
            reminder_message="m",
            scheduled_time=datetime(2026, 3, 15, 10, 0),
        )


class TestBotRemindersEarlyExit:
    @pytest.mark.asyncio
    async def test_reminders_command_requires_message(
        self, mock_context: MagicMock
    ) -> None:
        from agent.telegram.bot import reminders_command

        update = MagicMock()
        update.message = None
        update.effective_user = MagicMock()
        await reminders_command(update, mock_context)


class TestBotExtraBranches:
    @pytest.mark.asyncio
    async def test_reminders_command_empty(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        from agent.telegram.bot import reminders_command

        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 7
        with patch("agent.telegram.bot.get_scheduler") as gs:
            sched = MagicMock()
            sched.get_user_reminders = AsyncMock(return_value=[])
            gs.return_value = sched
            await reminders_command(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_reminders_command_lists_items(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        from agent.telegram.bot import reminders_command

        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 7
        r = MagicMock()
        r.id = 3
        r.message = "short"
        r.trigger_time = "2026-03-15T10:00:00+00:00"
        with patch("agent.telegram.bot.get_scheduler") as gs:
            sched = MagicMock()
            sched.get_user_reminders = AsyncMock(return_value=[r])
            gs.return_value = sched
            await reminders_command(mock_update, mock_context)
        txt = mock_update.message.reply_text.call_args[0][0]
        assert "#3" in txt

    @pytest.mark.asyncio
    async def test_reminders_command_exception(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        from agent.telegram.bot import reminders_command

        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 7
        with patch("agent.telegram.bot.get_scheduler") as gs:
            sched = MagicMock()
            sched.get_user_reminders = AsyncMock(side_effect=RuntimeError("x"))
            gs.return_value = sched
            await reminders_command(mock_update, mock_context)
        assert "Failed" in mock_update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_handle_message_empty_agent_reply(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        from agent.telegram.bot import handle_message

        with patch(
            "agent.telegram.bot.process_message",
            new_callable=AsyncMock,
            return_value="   ",
        ):
            await handle_message(mock_update, mock_context)
        assert "rephrase" in mock_update.message.reply_text.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_typing_indicator_timeout_and_network_and_generic(
        self, mock_update: MagicMock, mock_context: MagicMock
    ) -> None:
        from telegram.error import NetworkError, TimedOut

        from agent.telegram.bot import handle_message

        with patch(
            "agent.telegram.bot.process_message",
            new_callable=AsyncMock,
            return_value="ok",
        ):
            mock_context.bot.send_chat_action = AsyncMock(side_effect=TimedOut("t"))
            await handle_message(mock_update, mock_context)
            await asyncio.sleep(0)

            mock_context.bot.send_chat_action = AsyncMock(side_effect=NetworkError("n"))
            await handle_message(mock_update, mock_context)
            await asyncio.sleep(0)

            mock_context.bot.send_chat_action = AsyncMock(side_effect=KeyError("x"))
            await handle_message(mock_update, mock_context)
            await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_error_handler_branches(self) -> None:
        from telegram import Update
        from telegram.error import NetworkError, TimedOut

        from agent.telegram.bot import error_handler

        ctx = MagicMock()
        ctx.error = TimedOut("t")
        upd = MagicMock(spec=Update)
        upd.message = MagicMock()
        upd.message.reply_text = AsyncMock()
        await error_handler(upd, ctx)

        upd_nomsg = MagicMock(spec=Update)
        upd_nomsg.message = None
        await error_handler(upd_nomsg, ctx)

        ctx.error = NetworkError("n")
        await error_handler(upd, ctx)

        ctx.error = ValueError("other")
        await error_handler(upd, ctx)

    @pytest.mark.asyncio
    async def test_set_bot_commands_with_and_without_handler(
        self,
    ) -> None:
        from agent.telegram.bot import _set_bot_commands

        mock_application = MagicMock()
        mock_application.bot = MagicMock()
        mock_application.bot.set_my_commands = AsyncMock()

        mock_scheduler = MagicMock()
        mock_scheduler.start = AsyncMock()

        with (
            patch("agent.telegram.bot.get_scheduler", return_value=mock_scheduler),
            patch("agent.telegram.bot.get_handler", return_value=None),
            patch(
                "agent.telegram.bot.get_notification_service",
                return_value=MagicMock(),
            ),
        ):
            await _set_bot_commands(mock_application)

        with (
            patch("agent.telegram.bot.get_scheduler", return_value=mock_scheduler),
            patch("agent.telegram.bot.get_handler", return_value=MagicMock()),
            patch(
                "agent.telegram.bot.get_notification_service",
                return_value=MagicMock(),
            ),
        ):
            await _set_bot_commands(mock_application)


@pytest.fixture
def mock_update() -> MagicMock:
    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.text = "hi"
    update.effective_user = MagicMock()
    update.effective_user.id = 1
    update.effective_chat = MagicMock()
    update.effective_chat.id = 2
    return update


@pytest.fixture
def mock_context() -> MagicMock:
    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_chat_action = AsyncMock()
    return context
