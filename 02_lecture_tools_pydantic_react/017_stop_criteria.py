"""Стоп-критерії -- обовʼязковий елемент архітектури агента, а не опція.

Це продовження 011 лекції 1 (agent_limits_guardrails), де вже були ліміт
ітерацій і no-progress detector. Що змінюється тут:

  було (011)                          стало (StopController)
  ------------------------------      ------------------------------------
  два if усередині while              окремий компонент -> його можна тестувати
                                      (див. 012) і перевикористати в графі (018)
  MAX_ITERATIONS                      + token budget і timeout, яких у 011 не було
  seen_calls: set усіх викликів       вікно з max_repeats підряд

Про останній рядок варто сказати окремо, бо політика змінилася НАВМИСНО.
`set` у 011 забороняє будь-який повтор -- у тому числі законний: модель
виправила аргументи й хоче перевірити те саме замовлення ще раз. Вікно
«N однакових ПІДРЯД» пропускає таку перевірку, але ловить справжнє тупцювання.
Строгіший варіант із 011 нікуди не подівся -- він просто інша політика,
доречна там, де кожен виклик коштує грошей.

Дивимось на критерії окремо від графа: без LLM, детерміновано, з можливістю
натиснути кожну кнопку руками. Природний спосіб зупинки лише один --
Sufficiency: модель більше не викликає інструментів, бо відповідь готова.
Решта -- аварійні гальма, і кожне ловить свій клас збою (див. stop_controller.py).

Запуск:  python 017_stop_criteria.py
"""

from stop_controller import StopController


def probe(title: str, controller: StopController, calls: list[tuple[int, int, list[str]]]) -> None:
    """Проганяє послідовність кроків (step, tokens, tool_calls) через контролер."""
    print(f"[{title}]")
    for step, tokens, tool_calls in calls:
        stop, reason = controller.should_stop(step, tokens, tool_calls)
        state = f"СТОП -- {reason}" if stop else "продовжуємо"
        print(f"    крок={step} токенів={tokens} виклики={tool_calls} -> {state}")
        if stop:
            break
    print()


if __name__ == "__main__":
    probe(
        "MAX STEPS -- модель не збирається зупинятись сама",
        StopController(max_steps=3),
        [(1, 100, ["query_orders:{}"]), (2, 200, ["query_orders:{}"]), (3, 300, ["check_return_policy:{}"])],
    )

    probe(
        "TOKEN BUDGET -- кроків мало, але кожен тягне пів контексту",
        StopController(max_steps=10, max_tokens=5_000),
        [(1, 2_000, ["query_orders:{}"]), (2, 4_800, ["query_orders:{}"]), (3, 9_100, ["query_orders:{}"])],
    )

    probe(
        "LOOP DETECTION -- інструмент повертає порожній список, модель пробує те саме",
        StopController(max_steps=10, max_repeats=3),
        [
            (1, 100, ["query_orders:{'status': 'скасовано'}"]),
            (2, 200, ["query_orders:{'status': 'скасовано'}"]),
            (3, 300, ["query_orders:{'status': 'скасовано'}"]),
        ],
    )

    probe(
        "SUFFICIENCY -- нормальне завершення: жодне гальмо не знадобилось",
        StopController(max_steps=10),
        [(1, 100, ["query_orders:{}"]), (2, 200, ["check_return_policy:{'order_id': 'A-1001'}"]), (3, 300, [])],
    )

    print("Останній випадок -- єдиний «здоровий»: цикл завершився сам, бо на кроці 3")
    print("модель не попросила жодного інструмента. Решта -- аварійні зупинки,")
    print("і кожна повертає користувачу зрозумілу причину замість зависання.")
