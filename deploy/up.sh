#!/usr/bin/env bash
# One command: provision the AWS box, then build + deploy the app onto it.
set -euo pipefail
cd "$(dirname "$0")"
bash provision.sh
bash deploy.sh
