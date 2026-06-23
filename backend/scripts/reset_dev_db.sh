#!/usr/bin/env bash
# reset_dev_db.sh — Delegate to reset_demo_db.sh for backward compatibility.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
echo "reset_dev_db.sh delegates to reset_demo_db.sh"
echo "See also: reset_empty_db.sh (no seed)"
echo ""
exec "$DIR/reset_demo_db.sh"
