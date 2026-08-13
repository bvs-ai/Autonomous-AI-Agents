"""r2 — fallback як ланцюг пріоритетів (а не «ще один retry»).

  python r2_fallback.py healthy    # основна модель відповідає -> degraded=False
  python r2_fallback.py            # основна модель недоступна -> йдемо ланцюгом
  python r2_fallback.py all-down   # впало все: default-значення з міткою degraded

Ланцюг: основна модель -> дешевша модель -> кеш (TTL) -> default + ескалація.
Головна теза: default НЕ повинен мовчки стати «фактом» для наступного агента,
тому кожен рівень повертає поле confidence/degraded, і воно їде далі в state.
"""
import sys
import time


class TransientError(Exception):
    pass


CACHE = {"vendor-risk:ТОВ «Постачальник Плюс»": {"score": 0.21, "written_at": time.time() - 40}}
CACHE_TTL = 300          # секунд
ALL_DOWN = "all-down" in sys.argv
HEALTHY = "healthy" in sys.argv


def primary_model(query: str) -> dict:
    if not HEALTHY:
        raise TransientError("gpt-4o: 503 Service Unavailable")
    # єдиний рівень без degraded: повноцінне вимірювання
    return {"score": 0.21, "source": "gpt-4o", "degraded": False}


def cheap_model(query: str) -> dict:
    if ALL_DOWN:
        raise TransientError("gpt-4o-mini: 429 Too Many Requests")
    return {"score": 0.18, "source": "gpt-4o-mini", "degraded": True,
            "note": "відповідь резервної моделі, точність нижча"}


def from_cache(query: str) -> dict | None:
    hit = CACHE.get(query)
    if ALL_DOWN or hit is None:
        return None
    age = time.time() - hit["written_at"]
    if age > CACHE_TTL:
        print(f"  [cache] запис протух ({age:.0f}s > {CACHE_TTL}s) — не використовуємо")
        return None
    return {"score": hit["score"], "source": f"cache (вік {age:.0f}s)", "degraded": True}


def safe_default(query: str) -> dict:
    """Останній рівень. Значення свідомо песимістичне + прапорець для наступного вузла."""
    return {"score": None, "source": "default", "degraded": True, "needs_human": True,
            "note": "ризик постачальника НЕ обчислено — рішення не автоматизуємо"}


QUERY = "vendor-risk:ТОВ «Постачальник Плюс»"

CHAIN = [
    ("основна модель", primary_model),
    ("резервна модель", cheap_model),
    ("кеш з TTL", from_cache),
]

print(f"[запит] {QUERY}\n")
result = None
for level, fn in CHAIN:
    print(f"[рівень] {level}")
    try:
        result = fn(QUERY)
    except TransientError as e:
        print(f"  -> впав: {e}  (логуємо ОКРЕМО кожен рівень)\n")
        continue
    if result is None:                       # рівень відпрацював, але даних не дав
        print("  -> порожньо, йдемо далі\n")
        continue
    print(f"  -> успіх: {result}\n")
    break

if result is None:
    print("[рівень] default + ескалація до людини")
    result = safe_default(QUERY)
    print(f"  -> {result}\n")

print("[наступний вузол бачить]")
print(f"  score      = {result['score']}")
print(f"  degraded   = {result['degraded']}   <-- без цього прапорця деградація стає «фактом»")
print(f"  needs_human= {result.get('needs_human', False)}")
if result["score"] is None:
    print("\n[рішення] автоматичний платіж заблоковано, потрібне підтвердження людини")
elif result["degraded"]:
    print("\n[рішення] платіж дозволено, але результат позначено як неповний")
else:
    print("\n[рішення] платіж дозволено, повноцінна оцінка ризику")
