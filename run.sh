#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
fi

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

echo "=========================================================="
echo " Starting CineTracks: Movie Soundtrack & Song Exporter"
echo " Access the web app at: http://localhost:${PORT}"
echo "=========================================================="

exec .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" --reload

