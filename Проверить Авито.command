#!/bin/bash
set -eu
cd -- "$(dirname -- "$0")"
trap 'printf "\nНажмите Enter, чтобы закрыть окно."; read -r answer || true' EXIT
if [ ! -x .venv/bin/python ]; then
  printf 'Сначала откройте «Установить.command».\n'
  exit 1
fi
.venv/bin/python collect.py --pilot --diagnose
