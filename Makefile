# Makefile — Sushi Shop developer convenience commands
#
# All operations go through docker-compose so the environment is always consistent.
# Run `make up` first — most targets require the stack to be running.
#
# Usage:
#   make up        Start all services in the background
#   make down      Stop and remove containers (volumes are preserved)
#   make logs      Follow logs for all services
#   make migrate   Run Alembic migrations inside the running api container
#   make test      Run the pytest suite against the test database
#   make worker    Tail Celery worker logs
#   make shell     Open a bash shell inside the api container

.PHONY: up down logs migrate test worker shell

# Start the full stack in detached mode
up:
	docker-compose up -d

# Stop and remove containers. Volumes (postgres_data, redis_data) are preserved.
# To also remove volumes: docker-compose down -v
down:
	docker-compose down

# Follow logs for all services. Ctrl+C to stop.
logs:
	docker-compose logs -f

# Run Alembic migrations inside the running api container.
# Requires: make up (api container must be running)
migrate:
	docker-compose exec api alembic upgrade head

# Run the pytest suite against the test database.
# Spins up the test DB container, runs tests, then stops the test DB container.
test:
	docker-compose -f docker-compose.test.yml up -d
	docker-compose run --rm \
		-e DATABASE_URL=postgresql+asyncpg://sushi:sushi@db_test:5432/sushi_test \
		-e TEST_DATABASE_URL=postgresql+asyncpg://sushi:sushi@db_test:5432/sushi_test \
		--network sushi-shop_default \
		api pytest
	docker-compose -f docker-compose.test.yml down

# Tail Celery worker logs. Ctrl+C to stop.
worker:
	docker-compose logs -f worker

# Open an interactive bash shell inside the api container.
# Useful for running one-off commands, inspecting the filesystem, or debugging.
shell:
	docker-compose exec api bash
