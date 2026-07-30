"""Audit trail -- не те саме, що лог. Лог пишуть для діагностики і спокійно
ротують; audit trail відповідає на питання «хто, що, коли і з яким результатом
зробив» і має бути append-only та незмінним. Для агента це єдиний спосіб потім
довести, який саме виклик списав гроші або змінив дані.

Три деталі, які легко проґавити:
  1. час -- у UTC та в ISO-форматі, інакше журнал не звести з логами інших систем;
  2. get_entries() має віддавати ГЛИБОКУ копію: shallow-копія списку залишає ті
     самі словники, і зовнішній код може мовчки переписати вже записану подію;
  3. у журнал пишемо лише дозволені поля -- інакше в нього поїдуть токени й
     номери карток разом з аргументами інструмента.

Запуск:  python 010_audit_log_append_only.py
"""

import copy
import time
from collections import Counter
from datetime import datetime, timezone

# Що саме дозволено класти в журнал з аргументів інструмента.
AUDITABLE_ARGS = {"order_id", "status"}


class AuditLog:
    """Append-only журнал викликів інструментів."""

    def __init__(self):
        self._entries: list[dict] = []

    def record(self, tool: str, args: dict, result: str, duration: float, **extra) -> None:
        self._entries.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "seq": len(self._entries),
                "tool": tool,
                "args": {k: v for k, v in args.items() if k in AUDITABLE_ARGS},
                "result": result,
                "duration": round(duration, 3),
                **extra,
            }
        )

    def get_entries(self) -> list[dict]:
        # deepcopy, а не list(...): інакше віддані назовні словники -- ті самі
        # обʼєкти, що лежать у журналі, і запис перестає бути незмінним.
        return copy.deepcopy(self._entries)

    def get_summary(self) -> dict:
        durations = [e["duration"] for e in self._entries]
        return {
            "total_calls": len(self._entries),
            "by_result": dict(Counter(e["result"] for e in self._entries)),
            "by_tool": dict(Counter(e["tool"] for e in self._entries)),
            "avg_duration": round(sum(durations) / max(len(durations), 1), 3),
        }


audit_log = AuditLog()


def audited(func):
    """Мінімальна обгортка: будь-який виклик інструмента лишає слід у журналі."""

    def wrapped(**kwargs):
        start = time.time()
        try:
            result = func(**kwargs)
            audit_log.record(func.__name__, kwargs, "success", time.time() - start)
            return result
        except Exception as error:
            audit_log.record(func.__name__, kwargs, "error", time.time() - start, error=str(error))
            raise

    return wrapped


@audited
def check_return_policy(order_id: str, auth_token: str) -> dict:
    if order_id == "A-9999":
        raise KeyError("замовлення не знайдено")
    return {"order_id": order_id, "return_allowed": True}


if __name__ == "__main__":
    check_return_policy(order_id="A-1001", auth_token="secret-token-42")
    try:
        check_return_policy(order_id="A-9999", auth_token="secret-token-42")
    except KeyError:
        pass

    print("[ENTRIES]")
    for entry in audit_log.get_entries():
        print(f"    {entry}")

    print("\n[REDACTION] auth_token не потрапив у журнал -- пишемо лише allowlist полів\n")

    # Спроба переписати історію ззовні.
    stolen = audit_log.get_entries()
    stolen[1]["result"] = "success"
    stolen[1]["error"] = "нічого не сталося"
    print(f"[TAMPERING] зовнішній код виправив копію на: {stolen[1]['result']}")
    print(f"[JOURNAL]   у журналі як було: {audit_log.get_entries()[1]['result']}")
    print("            (з shallow-копією list(...) підробка пройшла б непоміченою)\n")

    print(f"[SUMMARY] {audit_log.get_summary()}")
