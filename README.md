# Garbanzo 🌱

A **personal AI assistant** built on Google ADK with Telegram integration. Deploy anywhere—bare metal, VPS, or private cloud—without the complexity or lock-in of heavy cloud providers.

> **Note:** This project uses a context system for agent identity and bootstrapping. See `.context/` directory for details.

## What Can Garbanzo Do?

- **💬 Chat via Telegram** - Natural conversations with your personal AI assistant
- **⏰ Smart Reminders** - Schedule one-time or recurring reminders using natural language
- **🏋️ Fitness Tracking** - Log calories, workouts, and view statistics
- **🔍 Web Search** - Search the web with Brave Search integration
- **📄 Context Files** - Secure read/write operations for notes and documents
- **🎬 YouTube Transcripts** - Extract transcripts from YouTube videos
- **🛠️ Shell Commands** - Execute bash commands (Docker environment)
- **🔌 MCP Tools** - Extensible via Model Context Protocol

## Key Features

- 🐳 **Deploy Anywhere**: Pre-configured Docker setup. Runs on Hetzner, DigitalOcean, or your basement server.
- 🔄 **Multi-Environment**: Run dev and prod simultaneously with isolated configs and volumes.
- 🔭 **Open Observability**: Built-in OpenTelemetry instrumentation with Langfuse support.
- 🚀 **Modern Stack**: Python 3.13, `uv`, `fastapi`, `asyncpg`.
- 💾 **Production Persistence**: Postgres-backed sessions with SQLite for reminders and fitness data.

## Quickstart

### Prerequisites
- Python **3.13+**
- [`uv`](https://github.com/astral-sh/uv)
- A Postgres connection string
- An LLM API Key (OpenRouter or Google)

### 1) Configure Environment

Copy `.env.example` to `.env`:

- **`AGENT_NAME`**: Unique ID for your agent.
- **`DATABASE_URL`**: Postgres connection string (sessions plus `agent_reminders`, `agent_calories`, `agent_workouts` tables).
- **`AGENT_TIMEZONE`**: IANA zone for reminders and fitness “today” (default `Asia/Kolkata` / IST).
- **`OPENROUTER_API_KEY`**: Recommended for accessing varied models.
- **`GOOGLE_API_KEY`**: Optional. Required only if using Gemini models directly.

### 2) Install Dependencies

```bash
uv sync
```

### 3) Run Locally

```bash
uv run python -m agent.server
```
Visit `http://127.0.0.1:8080`.

## Deployment: It's Just One Command

We've simplified deployment to the absolute basics. No Kubernetes required.

### Option 1: Using the Pre-built Image (Recommended)

Since we include CI/CD, every push to `main` builds a fresh image. On your server:

```bash
# 1. Pull the latest image
docker pull ghcr.io/queryplanner/google-adk-on-bare-metal:main

# 2. Start the service
docker compose up -d
```

### Option 2: Build Yourself

```bash
git pull
docker compose up --build -d
```

👉 **[Read the Full Deployment Guide](docs/DEPLOYMENT.md)**

## Multi-Environment Setup

Run **development** and **production** environments simultaneously on the same machine with complete isolation.

### Features

- ✅ **Separate Ports**: Dev on `3001`, Prod on `3000`
- ✅ **Isolated Data**: Separate volumes for each environment
- ✅ **Independent Configs**: `.env.dev` and `.env.prod` files
- ✅ **No Shared Secrets**: Each environment has its own API keys
- ✅ **Independent Control**: Start/stop each environment separately

### Quick Start

1. **Create environment files:**
   ```bash
   cp .env.example .env.dev   # Development config
   cp .env.example .env.prod  # Production config
   ```

2. **Edit each file with environment-specific values:**
   - `.env.dev` - Use test API keys, DEBUG logging, dev database
   - `.env.prod` - Use production keys, INFO logging, prod database

3. **Start environments:**
   ```bash
   # Development (port 3001)
   make dev

   # Production (port 3000)
   make prod

   # Both simultaneously
   make all-up
   ```

### Available Commands

| Command | Description |
| :--- | :--- |
| `make dev` | Start development bot |
| `make dev-all` | Start dev bot + API (port 3001) |
| `make prod` | Start production bot |
| `make prod-all` | Start prod bot + API (port 3000) |
| `make dev-stop` | Stop development environment |
| `make prod-stop` | Stop production environment |
| `make dev-logs` | View development logs (follow mode) |
| `make prod-logs` | View production logs (follow mode) |
| `make all-up` | Start both dev and prod bots |
| `make all-down` | Stop both environments |
| `make status` | Show container and volume status |
| `make dev-clean` | Remove dev containers and volumes ⚠️ |
| `make prod-clean` | Remove prod containers and volumes ⚠️ |

### Manual Docker Commands

If you prefer direct Docker Compose commands:

```bash
# Development Bot
docker compose -f docker-compose.dev.yml --profile bot up -d

# Development Bot + API (port 3001)
docker compose -f docker-compose.dev.yml --profile all up -d

# Production Bot
docker compose -f docker-compose.prod.yml --profile bot up -d

# Production Bot + API (port 3000)
docker compose -f docker-compose.prod.yml --profile all up -d

# Stop any environment
docker compose -f docker-compose.dev.yml down
docker compose -f docker-compose.prod.yml down
```

### Environment Isolation

| Aspect | Development | Production |
| :--- | :--- | :--- |
| Port | 3001 | 3000 |
| Log Level | DEBUG | INFO |
| Restart Policy | `no` (manual) | `unless-stopped` |
| Volume Prefix | `garbanzo-dev_*` | `garbanzo-prod_*` |
| Container Name | `garbanzo-dev-bot` | `garbanzo-prod-bot` |

### Safety Guarantees

- **No shared volumes**: Each environment uses separate Docker volumes
- **No shared ports**: Different host ports prevent conflicts
- **No shared configs**: Independent `.env` files for credentials
- **Independent lifecycle**: Start/stop/rebuild without affecting the other

## Observability

The template comes pre-wired with **OpenTelemetry**. By default, it's set up to export traces to **Langfuse** for beautiful, actionable insights into your agent's performance and costs.

To change the backend, simply update the OTel exporter configuration in your `.env`. You are not locked into any specific observability vendor.

## Telegram Bot Integration

This project includes a Telegram bot integration that allows users to interact with the ADK agent through Telegram.

### Setup

1. **Create a Telegram Bot:**
   - Open Telegram and search for `@BotFather`
   - Send `/newbot` and follow the prompts
   - Save the bot token you receive

2. **Configure Environment:**
   ```bash
   # Add to your .env file
   TELEGRAM_BOT_TOKEN=your-telegram-bot-token-here
   ```

3. **Run the Bot:**
   ```bash
   uv run telegram-bot
   ```

### Available Commands

| Command | Description |
| :--- | :--- |
| `/start` | Show welcome message |
| `/help` | Display help information |
| `/reset` | Clear conversation and start fresh |
| `/reminders` | List your scheduled reminders |

### Reminder Features

Ask the bot to schedule reminders using natural language:

- `"Remind me to take a break in 30 minutes"`
- `"Remind me about the meeting at 3pm today"`
- `"Remind me tomorrow at 9am to check emails"`
- `"Remind me every day at 9am to review my tasks"`
- `"Remind me every Monday at 8:30 to plan the week"`
- `"Remind me every 15 minutes to stretch"`

One-time and recurring reminders are stored persistently in SQLite and sent via
Telegram push notifications.

## Documentation

- [Development Guide](docs/development.md)
- [Architecture](docs/architecture.md)
- [Observability Setup](docs/base-infra/observability.md)
