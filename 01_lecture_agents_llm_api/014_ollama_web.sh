#!/usr/bin/bash
#
# Та сама локальна модель, але по HTTP — через РІДНЕ API Ollama (/api/chat).
# Формат свій, не OpenAI: наші демо з ним працювати не будуть (див. 015).
curl http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.5:4b",
    "messages": [
      {
        "role": "user",
        "content": "Hello"
      }
    ],
    "think": false,
    "stream": false
  }' | jq
