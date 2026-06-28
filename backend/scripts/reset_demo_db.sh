#!/usr/bin/env bash
# reset_demo_db.sh — Wipes all data, then starts fresh (migrations run automatically).
set -euo pipefail

cd "$(dirname "$0")/../.."

./reset-db.sh
