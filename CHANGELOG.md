# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-03-28

### Added
- **Claude Code Automation Skill:** Add skill for working on GitHub issues and creating PRs with Claude Code, including workspace cleanup workflow.
- **Claude Background Jobs:** Run Claude Code tasks in background for Telegram; post completion with session injection and agent follow-up.
- **Telegram Streaming:** Stream visible ADK text to Telegram during a turn with tool-call notifications.
- **LongRunningFunctionTool:** Add dedicated tool for Claude Code tasks with proper async handling.
- **OTLP Tracer Provider:** Install SDK TracerProvider with OTLP export when environment requests it.

### Changed
- **Tools Reorganization:** Refactored tools into domain modules (reminders, fitness, brave_search, youtube, context_files, docker, telegram_files, claude_coding, misc) with backward-compatible re-exports.
- **Telegram Plugin Location:** Move telegram_litellm_request_plugin.py to telegram/litellm_plugin.py and telegram_prefs.py to telegram/prefs.py.
- **Test Structure:** Reorganize tests to mirror source structure.

### Fixed
- **OTLP Detection:** Avoid probe span pollution in Langfuse by checking TracerProvider type.
- **ADK Type Annotation:** Fix text_file_body type annotation for ADK isinstance compatibility.
- **Docker Dev Loop:** Optimize dev loop, fix make commands and docker build caching.
- **Linux Docker:** Add host.docker.internal mapping for Linux in docker-compose.dev.

## [0.0.1] - 2026-03-25

### Added
- **Multi-Environment Docker Setup:** Run dev and prod simultaneously with isolated configs, volumes, and ports via `docker-compose.dev.yml`, `docker-compose.prod.yml`, and `Makefile` commands.
- **Automated Server Setup:** Introduced `setup.sh` to automate system updates, Docker installation, firewall (UFW) configuration, and Fail2Ban setup.
- **Production Deployment Workflow:** Enhanced GitHub Actions (`docker-publish.yml`) to securely inject environment variables (DB credentials, API keys) into the production server.
- **Configurable Connection Pooling:** Exposed PostgreSQL connection pool settings (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, etc.) via environment variables.
- **Observability Configuration:** Added support for configuring `ROOT_AGENT_MODEL` and Langfuse keys (`LANGFUSE_PUBLIC_KEY`, etc.) via deployment secrets.
- **Testing Standards:** Added `AGENTS.md` with strict guidelines for AI assistants, enforcing real-code testing over mocking internal logic.
- **Documentation:** Updated `README.md` and `docs/DEPLOYMENT.md` with comprehensive deployment guides.
- **Telegram Bot Integration:** Full Telegram bot support with slash commands and message handling.
- **Reminder Scheduling System:** Schedule and manage reminders with natural language date/time parsing.
- **Fitness Tracking:** Persist fitness data with SQLite storage.
- **Web Search:** Brave search integration for real-time information.
- **YouTube Transcripts:** Extract and process YouTube video transcripts.
- **MCP Tools:** Model Context Protocol tool support.

### Changed
- Renamed project to **Garbanzo** with updated README reflecting capabilities.
- Refactored `agent.py` to dynamically load `LiteLlm` for OpenRouter models.
- Standardized CI checks (`ruff`, `mypy`, `pytest`) to run before every build.
- Migrated fitness/reminders to SQLite for persistence.

### Fixed
- Prevent overlapping template replacements in `init_template.py`.
- Mandated explicit sequence for CI checks in `AGENTS.md`.
- Resolved `ValueError: Missing key inputs argument` by ensuring API keys are properly injected into the container environment.
- Addressed interactive prompt issues in `setup.sh` by setting `DEBIAN_FRONTEND=noninteractive`.
- Improved Telegram bot runtime stability.
- Avoid LaTeX in Telegram replies.
- Persist SQLite data in Docker deployments.

[Unreleased]: https://github.com/QueryPlanner/upgraded-garbanzo/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/QueryPlanner/upgraded-garbanzo/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/QueryPlanner/upgraded-garbanzo/releases/tag/v0.0.1
