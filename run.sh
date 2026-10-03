#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Create the Python environment first; see README.md."
  exit 1
fi
exec .venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 4321 --no-access-log
