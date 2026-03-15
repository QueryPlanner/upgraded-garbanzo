## Architecture (minimal, pragmatic)

### Why this repo exists

Google ADK is useful even without Google Cloud:

- You can run the ADK Dev UI locally on your own infrastructure
- You can use a non-Google model provider via `LiteLlm` and `OpenRouter`
- You can persist sessions in a regular database (Postgres)

### Key choices

- **Entry point**: `python -m agent.server`
  - Wraps `google.adk.cli.fast_api.get_fast_api_app(...)`
  - Forces a Postgres-backed session store via `DATABASE_URL`
  - Configures OpenTelemetry for vendor-neutral tracing (Langfuse auto-config included)
- **Agents directory**: `src/`
  - ADK Dev UI lists *directories* under `agents_dir`.
- **Main Agent**: `src/agent/agent.py`
  - Contains `root_agent` to keep ADK discovery simple.
- **DB URL normalization**: Handled in `server.py`
  - Converts standard Postgres URLs (e.g. `postgresql://`) to asyncpg-compatible ones (`postgresql+asyncpg://`)

### Project Structure

```
src/agent/
├── __init__.py              # Public interface
├── agent.py                 # Core agent configuration
├── prompt.py                # Core prompts
├── tools.py                 # Core tools (including reminder tools)
├── callbacks.py             # Core callbacks
├── server.py                # Server entry point
│
├── utils/                   # Utilities
│   ├── __init__.py
│   ├── config.py            # Configuration management
│   └── observability.py     # OpenTelemetry setup
│
├── telegram/                # Telegram integration module
│   ├── __init__.py
│   ├── bot.py               # Bot runner and handlers
│   └── handler.py           # ADK message processing
│
└── reminders/               # Reminder feature module
    ├── __init__.py
    ├── scheduler.py         # APScheduler-based reminder scheduler
    └── storage.py           # SQLite persistence for reminders
```

### What ADK uses the database for

ADK session persistence stores:

- session rows (IDs + state)
- events (conversation history / tool calls)
- app/user state snapshots

This is what makes the Dev UI “remember” conversations across restarts and allows for persistent agent memory.

### Reminder System Architecture

The reminder system allows users to schedule reminders through natural language interaction with the agent.

#### Components

1. **Storage Layer** (`reminders/storage.py`)
   - SQLite-based persistence for reminder data
   - Stores: user_id, message, trigger_time, is_sent status
   - Location: `~/.adk_agent/reminders.db`

2. **Scheduler** (`reminders/scheduler.py`)
   - Uses APScheduler for periodic reminder checks (every 30 seconds)
   - Sends due reminders via Telegram push notifications
   - Manages the reminder lifecycle

3. **Agent Tools** (`tools.py`)
   - `schedule_reminder`: Create new reminders with flexible time parsing
   - `list_reminders`: View scheduled reminders
   - `cancel_reminder`: Delete pending reminders

#### Flow

```
User Message → Agent → schedule_reminder tool → SQLite storage
                                              ↓
APScheduler (every 30s) → Check due reminders → Telegram push
```

#### Time Parsing

The reminder system supports natural language time formats:

- Absolute: `”2026-03-15 14:30”`, `”2026-03-15 at 3pm”`
- Relative: `”in 30 minutes”`, `”in 2 hours”`
- Day-based: `”tomorrow at 9am”`, `”at 5pm today”`