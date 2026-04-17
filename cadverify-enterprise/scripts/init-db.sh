#!/bin/bash
set -e
echo "Running database migrations..."
docker compose exec backend alembic upgrade head
echo "Migrations complete."
