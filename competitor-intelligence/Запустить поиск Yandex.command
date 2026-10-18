#!/bin/zsh
set -e
cd "$(dirname "$0")"

echo "Автоматический поиск сайтов и юридических лиц через Yandex Search API"
echo "API-ключ будет запрошен следующим шагом скрыто и не сохранится."
echo
read "RESEARCH_FOLDER_ID?Введите folder ID Яндекс Облака: "

python3 enrich_yandex.py \
  --registry output/competitors.csv \
  --folder-id "$RESEARCH_FOLDER_ID" \
  --output-dir output/yandex-search \
  --limit 20 \
  --max-queries 4

open output/yandex-search/review.html
