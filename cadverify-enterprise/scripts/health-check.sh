#!/bin/bash
echo "Checking CadVerify services..."
echo ""
curl -sf http://localhost:8000/health && echo " Backend: OK" || echo "Backend: FAIL"
curl -sf http://localhost:3000 > /dev/null && echo "Frontend: OK" || echo "Frontend: FAIL"
docker compose exec postgres pg_isready -U cadverify && echo "Postgres: OK" || echo "Postgres: FAIL"
docker compose exec redis redis-cli ping | grep -q PONG && echo "Redis: OK" || echo "Redis: FAIL"
echo ""
echo "Health check complete."
