#!/usr/bin/bash
#
# Запит з 000_http_request.txt, надісланий по-справжньому: curl + jq.
# Виклик LLM не потребує ні SDK, ні Python — це звичайний HTTP POST.

# Читає змінні з файлу .env у змінні оточення (env variables).
set -a; source .env; set +a

# jq — консольна утиліта - форматер для JSON. Установка: apt/brew install jq. Не обов'язкова
curl -sS "$OPENAI_BASE_URL/chat/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $OPENAI_API_KEY" \
    -d '{
      "model": "'$LLM_MODEL'",
      "stream": false,
      "messages": [{"role": "user", "content": "Відповідай коротко без роздумів: що таке LLM "}]
    }' | jq

