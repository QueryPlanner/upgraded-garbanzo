# Deployment Guide

You can deploy this Agent Platform using **Docker** (easiest compatibility) or **Bare Metal** (lowest resource usage).

## Option 0: Automated Server Setup (Infrastructure as Code)

To prepare a fresh Ubuntu/Debian server for production, run the included `setup.sh` script. This script automates:
1.  **System Updates**: Ensures the OS is patched.
2.  **Dependencies**: Installs Docker, Docker Compose, Git, UFW, and Fail2Ban.
3.  **Security**: Configures a basic firewall (UFW) allowing SSH (22), HTTP (80/443), and the Agent port (8080).
4.  **Log Rotation**: Prevents Docker logs from filling up the disk.
5.  **Dedicated User**: Creates an `agent-runner` user for secure operation.

**Run on your server (as root):**

> [!WARNING]
> Piping scripts directly from the internet to `bash` can be dangerous. Please review the script's contents before executing it to understand the actions it will perform on your server.

```bash
curl -fsSL https://raw.githubusercontent.com/<your-username>/google-adk-on-bare-metal/main/setup.sh | bash
# OR if you have cloned the repo:
sudo ./setup.sh
```

---

## Prerequisites (Both Methods)

1.  **Managed Postgres Database**: You need a connection string (e.g., from Neon, AWS RDS, Supabase).
2.  **OpenRouter or Google API Key**.
3.  **AGENT_NAME**: A unique identifier for your agent service.
4.  **Server**: A Linux server (Ubuntu/Debian recommended).

---

## CI with GitHub Actions

Pushes and pull requests to **`main`** (and version tags) run **code quality** only: `ruff`, `mypy`, and `pytest` via `.github/workflows/docker-publish.yml` calling `code-quality.yml`. **Nothing is deployed from CI** — you update the server yourself when ready.

## Manual deploy (recommended)

On the machine that runs Docker, from your clone of this repo (with `.env` beside `compose.yaml`):

```bash
git pull origin main
docker compose -f compose.yaml up -d --build
```

**Rollback** (if you still tag images locally, e.g. `adk-agent:previous`):

```bash
cd /path/to/repo
docker tag adk-agent:previous adk-agent:current
docker compose -f compose.yaml up -d
```

### Optional: GHCR pull-only deploy

If you prefer a registry image instead of building on the server, use **`compose.image.yaml`**, set `IMAGE=ghcr.io/<org>/<repo>:<tag>` in `.env`, and run `docker compose pull && docker compose up -d`. The default CI workflow does **not** push to GHCR on `main`; add a separate workflow if you need automated registry publishes.

### Server without a git clone (image only)

The application runs **inside the image**; you do **not** need Python source on the VM. You still need a tiny directory with:

1. **`compose.image.yaml`** — copy from this repo (or download the same file from GitHub raw), and  
2. **`.env`** — secrets and config (same variables as in CI: `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `OPENROUTER_API_KEY` or `GOOGLE_API_KEY`, etc.).

Set the image explicitly in `.env`:

```bash
IMAGE=ghcr.io/<your-org>/<your-repo>:main
```

Deploy or update:

```bash
docker compose -f compose.image.yaml pull
docker compose -f compose.image.yaml up -d
```

**Logs** do not require Compose or the repo — use the container name from `docker ps`:

```bash
docker logs -f --timestamps <container_name>
```

Example: `docker logs -f --timestamps upgraded-garbanzo-telegram-bot-1`.

If you use the default `compose.yaml` on a host that has **no** `Dockerfile`, Compose may try to build and fail; use **`compose.image.yaml`** on those hosts instead.

---

## Option 1: Docker (Recommended for Ease)

Best if you don't want to manage Python versions on the host.

1.  **Clone & Config**
    ```bash
    git clone <your-repo-url>
    cd google-adk-on-bare-metal
    cp .env.example .env
    # Edit .env with your DATABASE_URL and API Keys
    ```

2.  **Run**
    ```bash
    docker compose up --build -d
    ```

3.  **Update**
    ```bash
    git pull
    docker compose up --build -d
    ```

---

## Option 2: Bare Metal (Lowest Resources)

Best for small servers (e.g., 512MB RAM) since you avoid Docker overhead.

### 1. Install Dependencies
```bash
sudo apt update
sudo apt install -y python3-venv git
# Ensure Python 3.13+ is installed (e.g., via deadsnakes PPA on Ubuntu)
# sudo add-apt-repository ppa:deadsnakes/ppa
# sudo apt install python3.13 python3.13-venv

# Install uv (fast python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
```

### 2. Clone & Setup
```bash
git clone <your-repo-url>
cd google-adk-on-bare-metal

# Install Python dependencies
uv sync

# Configure Env
cp .env.example .env
# Edit .env with your real keys!
```

### 3. Setup Systemd (Keep it running)

1.  Edit `systemd/agent.service` and check the paths (User, WorkingDirectory).
2.  Install the service:
    ```bash
    sudo cp systemd/agent.service /etc/systemd/system/agent.service
    sudo systemctl daemon-reload
    sudo systemctl enable agent
    sudo systemctl start agent
    ```

### 4. Logs & Status
```bash
sudo systemctl status agent
sudo journalctl -u agent -f
```

## SQLite persistence (reminders, fitness)

Local SQLite files live under the container path `/app/src/agent/data`, backed by the Compose named volume `agent_data`. That survives `docker compose pull` and `docker compose up -d`.

**If data disappears after each deploy**, the usual cause is a **changing Compose project name**: Docker names volumes `{project}_agent_data`, and the project name defaults to the directory that holds `compose.yaml`. A different clone path or CI workspace layout then mounts a **new empty** volume.

This repo pins the project name (`name: adk-agent` in `compose.yaml`, and `COMPOSE_PROJECT_NAME=adk-agent` in the deploy workflow `.env`) so the same volumes are reused every time.

**On the VM you should:**

1. Deploy with `docker compose` from this repo’s `compose.yaml` (not a bare `docker run` without `-v` mounts — that uses the container filesystem and loses data on every new container).
2. Avoid `docker compose down -v` and any prune that removes volumes (for example `docker system prune --volumes`).
3. Optional hardening: bind-mount a fixed host directory instead of a named volume, for example create `/var/lib/adk-agent/data`, `chown` it to UID/GID `1000` (the image’s `app` user), and replace the `agent_data` volume line with `- /var/lib/adk-agent/data:/app/src/agent/data`.

If you already have data in an older volume (from a previous folder name), list volumes with `docker volume ls`, identify the old `*_agent_data` volume, and copy its files into the new volume or bind mount once.

## Troubleshooting

### Telegram: `Conflict: terminated by other getUpdates request`

Only **one** process may long-poll `getUpdates` per bot token. If you see this error after changing the Compose project name or redeploying, an **old** bot container is probably still running alongside the new one (`docker ps` will show two `telegram-bot` containers).

Stop and remove the duplicate (example):

```bash
docker stop upgraded-garbanzo-telegram-bot-1
docker rm upgraded-garbanzo-telegram-bot-1
```

`docker compose down` must be run from the directory that contains **that** stack’s `compose.yaml`; it does not accept a container ID.

### Permission Errors with Artifacts
If you encounter `PermissionError: [Errno 13] Permission denied: '/app/src/.adk'` when running with Docker:
1.  This usually happens because the container user (UID 1000) cannot write to the host volume mounted at `./src`.
2.  **Fix:** Ensure you have rebuilt the image to include the latest permission fixes:
    ```bash
    docker compose up -d --build
    ```
3.  If that fails, ensure your host user has UID 1000 (run `id -u`).