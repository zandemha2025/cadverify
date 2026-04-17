#!/bin/bash
set -e
mkdir -p images
echo "Exporting CadVerify Docker images..."
docker save cadverify-backend:latest > images/cadverify-backend.tar
docker save cadverify-frontend:latest > images/cadverify-frontend.tar
docker save postgres:16-alpine > images/postgres-16-alpine.tar
docker save redis:7-alpine > images/redis-7-alpine.tar
echo "Images exported to images/ directory"
ls -lh images/
