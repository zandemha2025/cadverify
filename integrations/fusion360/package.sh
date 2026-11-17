#!/usr/bin/env bash
# Build the distributable add-in zip (direct distribution, v1).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p dist
rm -f dist/scalecad-fusion-addin.zip
zip -q dist/scalecad-fusion-addin.zip \
  ScaleCADCheck.py step_export.py scalecad_client.py view_model.py \
  palette.html README.md
echo "dist/scalecad-fusion-addin.zip"
unzip -l dist/scalecad-fusion-addin.zip
