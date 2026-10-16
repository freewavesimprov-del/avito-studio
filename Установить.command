#!/bin/bash
set -eu
cd -- "$(dirname -- "$0")"
trap 'status=$?; if [ "$status" -ne 0 ]; then printf "\nУстановка остановлена. Скопируйте сообщение об ошибке выше.\n"; fi; printf "\nНажмите Enter, чтобы закрыть окно."; read -r answer || true' EXIT
if ! command -v python3 >/dev/null 2>&1; then
  printf 'Установите Python 3.9 или новее с https://www.python.org/downloads/macos/\n'
  exit 1
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else "Нужен Python 3.9 или новее")'
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
printf '\nУстановка завершена. Откройте «Проверить Авито.command».\n'
