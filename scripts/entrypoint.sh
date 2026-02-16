#!/bin/bash
set -e

echo "==> Starting Code Metrics Service"
echo "==> Initializing database..."

python -c "from app.database import init_db; init_db()"

echo "==> Database ready"
echo "==> Launching server on port 8080"

exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 2
