#!/bin/bash
# Double-click to start autojob on a Mac (close the Terminal window to stop).
cd "$(dirname "$0")" || exit 1
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
if [ "$1" = "fetch" ]; then
  "$PY" autojob.py fetch
else
  echo "Starting the dashboard in your browser (close this window to stop)"
  "$PY" autojob.py serve
fi
