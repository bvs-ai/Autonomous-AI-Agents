"""Налаштування. Читаються з `.env` один раз при імпорті."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# Модель для фонового ревʼю пам'яті. Порожньо — та сама, що й основна.
# Сенс окремої змінної: ревʼю не веде діалог, воно лише читає транскрипт і
# вирішує, що зберегти, — на це вистачає дешевшої моделі.
REVIEW_MODEL = os.getenv("REVIEW_MODEL", "") or MODEL

# Каталог, у межах якого агенту дозволено працювати.
WORKSPACE = Path(os.getenv("DEVMATE_WORKSPACE", ROOT)).resolve()

# Запобіжник від нескінченного циклу "модель знову кличе той самий інструмент".
MAX_ITERATIONS = 12

# Друк повного контексту перед кожним викликом моделі: DEBUG_CONTEXT=1 у .env
# або команда /context on у REPL. Показує рівно те, що йде в API, — включно з
# знімком пам'яті, пригаданим блоком і результатами інструментів.
DEBUG_CONTEXT = os.getenv("DEBUG_CONTEXT", "") not in ("", "0", "false")

# Скільки символів кожного повідомлення показувати. 0 — без обрізання.
DEBUG_CONTEXT_CHARS = int(os.getenv("DEBUG_CONTEXT_CHARS", "0"))

if not API_KEY:
    raise SystemExit("Немає OPENAI_API_KEY. Скопіюйте .env.example у .env.")
