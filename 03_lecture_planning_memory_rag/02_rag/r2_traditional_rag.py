"""Практика R2 — класичний RAG цілком: query -> top-k -> generate з цитатами.

Один прохід, один виклик LLM. Головне тут — не відповідь, а її перевірка:
модель зобовʼязана процитувати джерело дослівно, і код звіряє цитату з
текстом документа. Вигадане посилання ловить `assert`, а не людина.

Цитата — це адреса (`doc_id`), а не ввічливість.

Запуск:  python r2_traditional_rag.py
"""
import json

from corpus import EmbedUnavailable, DOCS, search_semantic
from llm import LLMUnavailable, call_llm, cost

QUESTION = "Як агент не втрачає прогрес після падіння процесу?"
SYSTEM = """Відповідай ЛИШЕ за наданими джерелами, стисло, українською.
Кожне твердження познач маркером [N] — номером джерела.
Поверни ЛИШЕ JSON: {"answer": "...", "citations": [{"n": 1, "quote": "..."}]}
`quote` — ДОСЛІВНИЙ фрагмент джерела N, не переказ."""


def main() -> None:
    print(f"[QUESTION] {QUESTION}\n")

    hits = search_semantic(QUESTION, k=3)
    print("[RETRIEVE] top-3:", "  ".join(f"{d['id']}={s:.3f}" for s, d in hits))

    sources = "\n".join(f"[{i}] doc_id={d['id']} | {d['text']}"
                        for i, (_, d) in enumerate(hits, 1))
    print(f"[PROMPT] у промпт пішло {len(hits)} джерел:\n{sources}\n")

    raw = call_llm([{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"Джерела:\n{sources}\n\nПитання: {QUESTION}"}])
    data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    print(f"[ANSWER] {data['answer']}\n")

    by_num = {i: d for i, (_, d) in enumerate(hits, 1)}

    def check(c: dict) -> None:
        doc = by_num.get(c["n"])
        ok = doc is not None and c["quote"].strip(' "') in doc["text"]
        print(f"[CITE] {'ok  ' if ok else 'FAIL'} [{c['n']}] -> "
              f"{doc['id'] if doc else '???'}: «{c['quote']}»")

    for c in data["citations"]:
        check(c)

    # Підставна цитата — щоб перевірка показала й другий свій бік. Речення
    # правдоподібне і про ту саму тему, але в джерелі його немає.
    check({"n": 1, "quote": "агент автоматично відкочує транзакцію"})
    print("       ^ вигадану цитату спіймав код, а не читач")

    print(f"\n{cost()}  <- один прохід, один виклик. Порівняй з r3.")


if __name__ == "__main__":
    try:
        main()
    except (LLMUnavailable, EmbedUnavailable) as e:
        print(f"[ЗУПИНКА] {e}")

    # ── Твоя черга ──
    # 1) Прибери з промпту вимогу дослівності — і подивись, скільки цитат
    #    стануть FAIL. Це і є вимірювання галюцинацій, а не суперечка про них.
    # 2) Спитай те, чого в корпусі немає («яка версія Python?»). Модель має
    #    відмовитись, а не вигадати: додай це правило в SYSTEM і перевір.
