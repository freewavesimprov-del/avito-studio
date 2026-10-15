#!/usr/bin/env bash
# Совместимое имя обёртки; теперь запускает локальный сбор без панели.
set -euo pipefail
cd -- "$(dirname -- "$0")"
exec "${PYTHON:-.venv/bin/python}" collect.py "$@"
