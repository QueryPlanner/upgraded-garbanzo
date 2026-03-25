# =============================================================================
# Garbanzo Multi-Environment Docker Management
# =============================================================================
# Quick commands for managing development and production environments.
#
# Service Profiles:
#   --profile bot   - Telegram bot only (polls Telegram, no port needed)
#   --profile api   - FastAPI web server only (exposes port)
#   --profile all   - Both bot and API services
#
# Usage:
#   make dev          - Start dev bot (default)
#   make dev-api      - Start dev API server on port 3001
#   make dev-all      - Start dev bot + API
#   make prod         - Start prod bot (default)
#   make prod-api     - Start prod API server on port 3000
#   make prod-all     - Start prod bot + API
# =============================================================================

.PHONY: help dev dev-bot dev-api dev-all prod prod-bot prod-api prod-all
.PHONY: dev-stop prod-stop dev-logs prod-logs dev-build prod-build
.PHONY: all-up all-down status clean dev-clean prod-clean

# Default target
help:
	@echo "Garbanzo Multi-Environment Docker Commands"
	@echo "=========================================="
	@echo ""
	@echo "Development Environment (DEBUG logging, port 3001 for API):"
	@echo "  make dev          - Start development bot (default)"
	@echo "  make dev-bot      - Start development bot only"
	@echo "  make dev-api      - Start development API only (port 3001)"
	@echo "  make dev-all      - Start both dev bot and API"
	@echo "  make dev-stop     - Stop development environment"
	@echo "  make dev-logs     - View development logs (follow mode)"
	@echo "  make dev-build    - Rebuild development image"
	@echo "  make dev-shell    - Open shell in development container"
	@echo ""
	@echo "Production Environment (INFO logging, port 3000 for API):"
	@echo "  make prod         - Start production bot (default)"
	@echo "  make prod-bot     - Start production bot only"
	@echo "  make prod-api     - Start production API only (port 3000)"
	@echo "  make prod-all     - Start both prod bot and API"
	@echo "  make prod-stop    - Stop production environment"
	@echo "  make prod-logs    - View production logs (follow mode)"
	@echo "  make prod-build   - Rebuild production image"
	@echo "  make prod-shell   - Open shell in production container"
	@echo ""
	@echo "Both Environments:"
	@echo "  make all-up       - Start dev and prod bots"
	@echo "  make all-down     - Stop both environments"
	@echo "  make status       - Show container status"
	@echo ""
	@echo "Cleanup (WARNING: destroys data):"
	@echo "  make dev-clean    - Remove dev containers and volumes"
	@echo "  make prod-clean   - Remove prod containers and volumes"
	@echo "  make clean        - Remove ALL containers and volumes"

# =============================================================================
# Development Environment
# =============================================================================
dev: dev-bot

dev-bot:
	@echo "🚀 Starting development bot..."
	docker compose -f docker-compose.dev.yml --profile bot up -d
	@echo "✅ Development bot running"
	@echo "📊 View logs: make dev-logs"

dev-api:
	@echo "🚀 Starting development API on port 3001..."
	docker compose -f docker-compose.dev.yml --profile api up -d
	@echo "✅ Development API running"
	@echo "🔍 Health check: curl http://localhost:3001/health"

dev-all:
	@echo "🚀 Starting development bot and API..."
	docker compose -f docker-compose.dev.yml --profile all up -d
	@echo "✅ Development environment running (bot + API)"
	@echo "📊 View logs: make dev-logs"
	@echo "🔍 API Health: curl http://localhost:3001/health"

dev-stop:
	@echo "🛑 Stopping development environment..."
	docker compose -f docker-compose.dev.yml down
	@echo "✅ Development environment stopped"

dev-logs:
	docker compose -f docker-compose.dev.yml logs -f

dev-build:
	@echo "🔨 Building development image..."
	docker compose -f docker-compose.dev.yml build --no-cache
	@echo "✅ Development image built"

dev-shell:
	docker compose -f docker-compose.dev.yml exec telegram-bot /bin/sh 2>/dev/null || \
	docker compose -f docker-compose.dev.yml exec api /bin/sh

# =============================================================================
# Production Environment
# =============================================================================
prod: prod-bot

prod-bot:
	@echo "🚀 Starting production bot..."
	docker compose -f docker-compose.prod.yml --profile bot up -d
	@echo "✅ Production bot running"
	@echo "📊 View logs: make prod-logs"

prod-api:
	@echo "🚀 Starting production API on port 3000..."
	docker compose -f docker-compose.prod.yml --profile api up -d
	@echo "✅ Production API running"
	@echo "🔍 Health check: curl http://localhost:3000/health"

prod-all:
	@echo "🚀 Starting production bot and API..."
	docker compose -f docker-compose.prod.yml --profile all up -d
	@echo "✅ Production environment running (bot + API)"
	@echo "📊 View logs: make prod-logs"
	@echo "🔍 API Health: curl http://localhost:3000/health"

prod-stop:
	@echo "🛑 Stopping production environment..."
	docker compose -f docker-compose.prod.yml down
	@echo "✅ Production environment stopped"

prod-logs:
	docker compose -f docker-compose.prod.yml logs -f

prod-build:
	@echo "🔨 Building production image..."
	docker compose -f docker-compose.prod.yml build --no-cache
	@echo "✅ Production image built"

prod-shell:
	docker compose -f docker-compose.prod.yml exec telegram-bot /bin/sh 2>/dev/null || \
	docker compose -f docker-compose.prod.yml exec api /bin/sh

# =============================================================================
# Both Environments
# =============================================================================
all-up: dev-bot prod-bot
	@echo "✅ Both bot environments running"
	@echo "   Dev bot:  polling Telegram"
	@echo "   Prod bot: polling Telegram"

all-down: dev-stop prod-stop
	@echo "✅ Both environments stopped"

status:
	@echo "📊 Container Status"
	@echo "=================="
	@docker ps -a --filter "label=project=garbanzo" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "No containers found"
	@echo ""
	@echo "📦 Volumes"
	@echo "========="
	@docker volume ls --filter "name=garbanzo-" --format "{{.Name}}" 2>/dev/null || echo "No volumes found"

# =============================================================================
# Cleanup
# =============================================================================
dev-clean:
	@echo "⚠️  WARNING: This will delete all development data!"
	@echo "Press Ctrl+C to cancel, or Enter to continue..."
	@read confirm
	docker compose -f docker-compose.dev.yml down -v --remove-orphans
	@echo "✅ Development environment and volumes removed"

prod-clean:
	@echo "⚠️  WARNING: This will delete all production data!"
	@echo "Press Ctrl+C to cancel, or Enter to continue..."
	@read confirm
	docker compose -f docker-compose.prod.yml down -v --remove-orphans
	@echo "✅ Production environment and volumes removed"

clean: dev-clean prod-clean
	@echo "✅ All environments and volumes removed"
