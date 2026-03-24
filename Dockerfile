# syntax=docker/dockerfile:1

# ============================================================================
# Builder Stage: Install dependencies with optimal caching
# ============================================================================
FROM python:3.13-slim AS builder

# Install uv
RUN pip install uv==0.9.26

# Set working directory
WORKDIR /app

# Environment variables for optimal uv behavior
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# Copy dependency files - explicit cache invalidation when either file changes
COPY pyproject.toml uv.lock ./

# Install dependencies (cache mount provides the performance optimization)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

# Copy only source code
COPY src ./src

# Install project (create empty README to satisfy package metadata requirements)
RUN --mount=type=cache,target=/root/.cache/uv \
    touch README.md && \
    uv sync --locked --no-editable --no-dev

# ============================================================================
# Runtime Stage: Minimal production image
# ============================================================================
FROM python:3.13-slim AS runtime

# Install system dependencies
# - netcat-openbsd: for checking DB readiness (used in entrypoint.sh)
# - git: branch, commit, and worktree support for delegated coding tasks
# - GitHub CLI: create PRs and inspect GitHub state from inside the container
# - Node.js 22+ (NodeSource): required by agent-browser, Gemini CLI, and MCP CLIs
# - build deps: native addons during npm install (purged after install)
# - chromium: browser for agent-browser (Chrome-for-Testing install has no linux-arm64)
# - curl, ca-certificates, gnupg: HTTPS plus package signing keys
RUN apt-get update && apt-get install -y --no-install-recommends \
    netcat-openbsd \
    git \
    ca-certificates \
    curl \
    gnupg \
    chromium \
    build-essential \
    cmake \
    libsqlite3-dev \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | gpg --dearmor -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs gh \
    && pip install --no-cache-dir uv==0.9.26 \
    && npm install -g \
        agent-browser \
        @google/gemini-cli \
        @notionhq/notion-mcp-server \
        @tobilu/qmd \
    && apt-get purge -y build-essential cmake libsqlite3-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# qmd global CLI available as `qmd` (see agent prompt for MEMORY.md + indexing)

# Create non-root user for security (matching common host UID 1000)
RUN groupadd -g 1000 app && \
    useradd -u 1000 -g app -s /bin/sh -m app

# Set working directory
WORKDIR /app

# Pre-create directories for volume mounts and set ownership
# - /app/src/.adk: ADK artifacts
# - /app/src/agent/data: Local SQLite fallback and other files when not using Postgres
# - /app/src/.context: Context files (USER.md, IDENTITY.md, SOUL.md)
# - /app/memory: durable agent memory (MEMORY.md); seed copied in entrypoint if empty
# - /home/app/garbanzo-home: durable coding home for repos, configs, caches, and tools
RUN mkdir -p /app/src/.adk/artifacts \
             /app/src/agent/data \
             /app/src/.context \
             /app/memory \
             /home/app/garbanzo-home \
    && chown -R app:app /app /home/app/garbanzo-home

# Copy application and virtual environment from builder
COPY --from=builder --chown=app:app /app .

# Playwright: OS deps as root, browsers seeded in-image and copied to garbanzo-home
# on first boot when the persistent home volume is empty.
ENV PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers
RUN mkdir -p /app/pw-browsers \
    && chown app:app /app/pw-browsers \
    && /app/.venv/bin/playwright install-deps chromium \
    && su -s /bin/sh app -c "/app/.venv/bin/playwright install chromium"

# Copy entrypoint script and set ownership/permissions
COPY --chown=app:app entrypoint.sh .
RUN chmod +x entrypoint.sh

# Utility scripts for Garbanzo bootstrap and delegated coding workflows
COPY --chown=app:app scripts /app/scripts
RUN find /app/scripts -type f -name '*.sh' -exec chmod +x {} \;

# Copy context files (IDENTITY.md, SOUL.md - USER.md is user-specific)
COPY --chown=app:app .context/*.md /app/src/.context/

# Skill markdown (lazy-loaded via SkillToolset); non-editable installs need this path
COPY --chown=app:app skills /app/skills

# Default MEMORY.md template (entrypoint copies into /app/memory when volume is empty)
COPY --chown=app:app memory/MEMORY.md /app/.memory-seed/MEMORY.md

# Set environment to use virtual environment
ENV VIRTUAL_ENV=/app/.venv \
    GARBANZO_HOME=/home/app/garbanzo-home \
    HOME=/home/app/garbanzo-home \
    XDG_CONFIG_HOME=/home/app/garbanzo-home/.config \
    XDG_CACHE_HOME=/home/app/garbanzo-home/.cache \
    XDG_STATE_HOME=/home/app/garbanzo-home/.state \
    NPM_CONFIG_PREFIX=/home/app/garbanzo-home/npm-global \
    NPM_CONFIG_CACHE=/home/app/garbanzo-home/.cache/npm \
    PIP_CACHE_DIR=/home/app/garbanzo-home/.cache/pip \
    UV_CACHE_DIR=/home/app/garbanzo-home/.cache/uv \
    PLAYWRIGHT_BROWSERS_PATH=/home/app/garbanzo-home/playwright-browsers \
    PATH="/home/app/garbanzo-home/tools/bin:/home/app/garbanzo-home/npm-global/bin:/home/app/garbanzo-home/.local/bin:/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    AGENT_DIR=/app/src \
    AGENT_SKILLS_DIR=/app/skills \
    HOST=0.0.0.0 \
    PORT=8080 \
    AGENT_BROWSER_EXECUTABLE_PATH=/usr/bin/chromium

# Switch to non-root user
USER app

# Install Claude Code for in-container developer workflows and MCP support.
RUN mkdir -p "$HOME/.claude" "$HOME/.local/bin" "$HOME/.local/share" \
    && curl -fsSL https://claude.ai/install.sh | bash \
    && claude --version

# Expose port (default 8080)
EXPOSE 8080

# Set the entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

# Run the FastAPI server
CMD ["python", "-m", "agent.server"]
