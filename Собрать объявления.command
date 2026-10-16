#!/bin/bash
set -eu
cd -- "$(dirname -- "$0")"
trap 'printf "\nНажмите Enter, чтобы закрыть окно."; read -r answer || true' EXIT
if [ ! -x .venv/bin/python ]; then
  printf 'Сначала откройте «Установить.command».\n'
  exit 1
fi
if [ -f results/progress.json ]; then
  .venv/bin/python collect.py --pages 2 --interval 900 --resume
else
  .venv/bin/python collect.py --pages 2 --interval 900
fi
