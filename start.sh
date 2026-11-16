#!/usr/bin/env sh
# Set up (first time) and open the LeadScraper dashboard.
# Extra arguments are passed through, e.g.  ./start.sh run --limit 5
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else echo "Python 3.10+ is required: https://www.python.org/downloads/"; exit 1
fi
exec "$PY" start.py "$@"
