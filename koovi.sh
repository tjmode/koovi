#!/bin/sh
# Koovi launcher. Claude Code hooks call this file, and so does the /koovi command.
# Koovi needs nothing but Python 3.8 or newer. No packages to install.
DIR="$(cd "$(dirname "$0")" && pwd)"
for PY in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 2>/dev/null)" /usr/bin/python3; do
  [ -n "$PY" ] && [ -x "$PY" ] || continue
  "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1 || continue
  exec "$PY" "$DIR/koovi.py" "$@"
done
echo "Koovi needs Python 3.8 or newer. Install it with: brew install python3" >&2
exit 1
