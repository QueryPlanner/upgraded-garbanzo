# syntax=docker/dockerfile:1.14

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

# Install base system packages (rarely changes - good cache layer)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    netcat-openbsd \
    git \
    ca-certificates \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Add Node.js repository (rarely changes)
RUN curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list

# Add GitHub CLI repository (rarely changes)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | gpg --dearmor -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list

# Install Node.js, GitHub CLI, and chromium (changes rarely)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    gh \
    chromium \
    && rm -rf /var/lib/apt/lists/*

# Install global npm packages with cache (changes occasionally)
RUN --mount=type=cache,target=/root/.npm \
    npm install -g \
        agent-browser \
        @google/gemini-cli \
        @notionhq/notion-mcp-server \
        @tobilu/qmd

# Install uv for runtime use
RUN pip install --no-cache-dir uv==0.9.26

# Create non-root user for security (matching common host UID 1000)
RUN groupadd -g 1000 app && \
    useradd -u 1000 -g app -s /bin/sh -m app

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

# Switch to app user temporarily to install Claude
USER app
# Install Claude Code for in-container developer workflows and MCP support.
RUN --mount=type=cache,target=/home/app/.cache \
    mkdir -p "$HOME/.claude" "$HOME/.local/bin" "$HOME/.local/share" \
    && curl -fsSL https://claude.ai/install.sh | bash \
    && claude --version
# Switch back to root to finish setup
USER root

# Set working directory
WORKDIR /app

# Playwright: Install OS deps only (browser is system chromium via apt)
# We do this before copying code so it caches perfectly.
RUN npx -y playwright@1.58.0 install-deps chromium


# Pre-create directories for volume mounts and set ownership
RUN mkdir -p /app/src/.adk/artifacts \
             /app/src/agent/data \
             /app/src/.context \
             /app/memory \
             /home/app/garbanzo-home \
    && chown -R app:app /app /home/app/garbanzo-home

# Copy application and virtual environment from builder
COPY --from=builder --chown=app:app /app .


# Copy entrypoint script and set ownership/permissions
COPY --chown=app:app entrypoint.sh .
RUN chmod +x entrypoint.sh

# Utility scripts for Garbanzo bootstrap and delegated coding workflows
COPY --chown=app:app scripts /app/scripts
RUN find /app/scripts -type f -name '*.sh' -exec chmod +x {} \;

# Global Claude Code instructions (~/.claude/CLAUDE.md with HOME=garbanzo-home)
COPY --chown=app:app docker/garbanzo-home/.claude/CLAUDE.md \
    /home/app/garbanzo-home/.claude/CLAUDE.md

# Copy context files (IDENTITY.md, SOUL.md - USER.md is user-specific)
COPY --chown=app:app .context/*.md /app/src/.context/

# Skill markdown (lazy-loaded via SkillToolset); non-editable installs need this path
COPY --chown=app:app skills /app/skills

# Default MEMORY.md template (entrypoint copies into /app/memory when volume is empty)
COPY --chown=app:app memory/MEMORY.md /app/.memory-seed/MEMORY.md


# Switch to non-root user
USER app


# Expose port (default 8080)
EXPOSE 8080

# Set the entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

# Run the FastAPI server
CMD ["python", "-m", "agent.server"]
