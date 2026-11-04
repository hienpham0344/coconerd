#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Node loads dotenv without executing its contents as shell code.
exec node --env-file-if-exists=.env scripts/run-python.mjs bridge
