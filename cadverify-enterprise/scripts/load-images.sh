#!/bin/bash
set -e
echo "Loading CadVerify Docker images..."
for tar in images/*.tar; do
  echo "Loading $tar..."
  docker load < "$tar"
done
echo "All images loaded successfully."
docker images | grep -E "cadverify|postgres|redis"
