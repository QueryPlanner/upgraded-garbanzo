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
# - nodejs/npm: global agent-browser CLI
# - chromium: browser for agent-browser (Chrome-for-Testing install has no linux-arm64)
# - curl, ca-certificates: HTTPS for npm and browser downloads
RUN apt-get update && apt-get install -y --no-install-recommends \
    netcat-openbsd \
    ca-certificates \
    curl \
    chromium \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# agent-browser CLI (uses AGENT_BROWSER_EXECUTABLE_PATH + distro Chromium)
RUN npm install -g agent-browser

# Create non-root user for security (matching common host UID 1000)
RUN groupadd -g 1000 app && \
    useradd -u 1000 -g app -s /bin/sh -m app

# Set working directory
WORKDIR /app

# Pre-create directories for volume mounts and set ownership
# - /app/src/.adk: ADK artifacts
# - /app/src/agent/data: Local SQLite fallback and other files when not using Postgres
# - /app/src/.context: Context files (USER.md, IDENTITY.md, SOUL.md)
RUN mkdir -p /app/src/.adk/artifacts \
             /app/src/agent/data \
             /app/src/.context \
    && chown -R app:app /app

# Copy application and virtual environment from builder
COPY --from=builder --chown=app:app /app .

# Playwright: OS deps as root, browsers under a shared path for the app user
ENV PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers
RUN mkdir -p /app/pw-browsers \
    && chown app:app /app/pw-browsers \
    && /app/.venv/bin/playwright install-deps chromium \
    && su -s /bin/sh app -c "/app/.venv/bin/playwright install chromium"

# Copy entrypoint script and set ownership/permissions
COPY --chown=app:app entrypoint.sh .
RUN chmod +x entrypoint.sh

# Copy context files (IDENTITY.md, SOUL.md - USER.md is user-specific)
COPY --chown=app:app .context/*.md /app/src/.context/

# Skill markdown (lazy-loaded via SkillToolset); non-editable installs need this path
COPY --chown=app:app skills /app/skills

# Set environment to use virtual environment
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    AGENT_DIR=/app/src \
    AGENT_SKILLS_DIR=/app/skills \
    HOST=0.0.0.0 \
    PORT=8080 \
    AGENT_BROWSER_EXECUTABLE_PATH=/usr/bin/chromium

# Switch to non-root user
USER app

# Expose port (default 8080)
EXPOSE 8080

# Set the entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

# Run the FastAPI server
CMD ["python", "-m", "agent.server"]
