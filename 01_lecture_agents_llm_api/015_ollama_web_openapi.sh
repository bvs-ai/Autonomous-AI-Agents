#!/usr/bin/bash
#
# Ollama через OpenAI-СУМІСНИЙ ендпоінт (/v1/chat/completions) — той самий контракт,
# що в 001. Саме тому демо 002-012 їдуть на локальній моделі без правок коду:
# достатньо змінити OPENAI_BASE_URL (див. .env.ollama).
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:7b",
    "messages": [
      {
        "role": "user",
        "content": "Hello"
      }
    ],
    "stream": false
  }' | jq

