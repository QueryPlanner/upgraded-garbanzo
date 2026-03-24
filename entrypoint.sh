#!/bin/sh
set -e

# Wait for the database if DATABASE_URL is set and looks like a postgres url
if echo "$DATABASE_URL" | grep -q "postgresql://"; then
    echo "Waiting for database..."
    # Extract host and port from DATABASE_URL
    # Assumes format postgresql://user:pass@host:port/dbname
    # This is a basic extraction and might need adjustment for complex URLs
    DB_HOST=$(echo $DATABASE_URL | sed -e 's|^.*@||' -e 's|/.*$||' -e 's|:.*$||')
    DB_PORT=$(echo $DATABASE_URL | sed -e 's|^.*@||' -e 's|/.*$||' -e 's|^.*:||')
    
    # Default port if not specified
    if [ "$DB_HOST" = "$DB_PORT" ]; then
        DB_PORT=5432
    fi

    # Loop until the database is ready
    while ! nc -z $DB_HOST $DB_PORT; do
      sleep 1
    done
    echo "Database started"
fi

# Persisted memory volume may mount an empty directory; restore template once.
if [ ! -f /app/memory/MEMORY.md ] && [ -f /app/.memory-seed/MEMORY.md ]; then
    mkdir -p /app/memory
    cp /app/.memory-seed/MEMORY.md /app/memory/MEMORY.md
fi

# Garbanzo's durable home stores repos, config, caches, and user-installed tools.
if [ -n "$GARBANZO_HOME" ]; then
    mkdir -p \
        "$GARBANZO_HOME/.cache/npm" \
        "$GARBANZO_HOME/.cache/pip" \
        "$GARBANZO_HOME/.cache/uv" \
        "$GARBANZO_HOME/.config" \
        "$GARBANZO_HOME/.local/bin" \
        "$GARBANZO_HOME/.state" \
        "$GARBANZO_HOME/npm-global/bin" \
        "$GARBANZO_HOME/playwright-browsers" \
        "$GARBANZO_HOME/tmp" \
        "$GARBANZO_HOME/tools/bin" \
        "$GARBANZO_HOME/workspace"
fi

# Seed the persistent Playwright browser directory once so browser automation
# survives redeploys without forcing a fresh download every time.
if [ -d /app/pw-browsers ] && [ -n "$PLAYWRIGHT_BROWSERS_PATH" ]; then
    mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"
    if [ -z "$(ls -A "$PLAYWRIGHT_BROWSERS_PATH" 2>/dev/null)" ]; then
        cp -R /app/pw-browsers/. "$PLAYWRIGHT_BROWSERS_PATH"/
    fi
fi

if [ -x /app/scripts/bootstrap_garbanzo_home.sh ]; then
    /app/scripts/bootstrap_garbanzo_home.sh
fi

exec "$@"
