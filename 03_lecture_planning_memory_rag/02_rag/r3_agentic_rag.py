"""Практика R3 — agentic RAG: агент сам вирішує, шукати і чи годиться знайдене.

Traditional RAG (r2):  query -> top-k -> generate. Один прохід, завжди шукає.
Agentic RAG:           route -> retrieve -> grade -> rewrite -> generate,
                       з лімітом спроб.

Ретрівер той самий, що в r2 (`search_semantic`), інакше порівняння нечесне.
Дивимось на [COST] у кінці: за гнучкість платять викликами.

Запуск:  python r3_agentic_rag.py
"""
from corpus import EmbedUnavailable, search_semantic
from llm import LLMUnavailable, call_llm, cost

# Питання те саме по суті, що в r2, але сказане «як у житті»: без жодного
# терміна з нотаток. Перший пошук через це промахується — і видно, за що
# саме agentic RAG бере свою ціну.
QUESTION = "Як зробити, щоб довга задача переживала перезапуск сервісу?"
MAX_ATTEMPTS = 2

# Роутер і rewriter мають знати, що лежить у базі й якими словами воно там
# записане, інакше перший вирішує навмання, а другий переписує запит у
# терміни, яких у корпусі немає. У проді цей опис беруть з метаданих колекції.
KB = ("нотатки про внутрішній проєкт-агент. Теми і терміни: checkpointer і "
      "знімок стану, plan-and-execute, стиснення історії, reranking через "
      "cross-encoder, таймзони дедлайнів, tenant_id, запуск тестів pytest")


def ask_one_word(prompt: str) -> str:
    return call_llm([{"role": "user", "content": prompt}]).strip().lower()


def agentic_rag(question: str) -> None:
    print(f"[QUESTION] {question}\n")

    route = ask_one_word(f"База знань: {KB}.\n"
                         "Чи варто шукати в ній, щоб відповісти? "
                         f"Одне слово: retrieve або generate.\nПитання: {question}")
    print(f"[ROUTE] {route}")
    if "generate" in route:
        print(f"[GENERATE] {call_llm([{'role': 'user', 'content': question}])}")
        return

    query = question
    for attempt in range(1, MAX_ATTEMPTS + 1):
        hits = search_semantic(query, k=2)
        context = "\n".join(d["text"] for _, d in hits)
        print(f"[RETRIEVE] спроба {attempt}: {query!r} -> "
              + "  ".join(f"{d['id']}={s:.3f}" for s, d in hits))

        grade = ask_one_word(
            "Чи містить контекст пряму відповідь на питання? "
            "Одне слово: relevant або irrelevant.\n"
            f"Питання: {question}\nКонтекст:\n{context}")
        print(f"[GRADE] {grade}")

        if "irrelevant" in grade and attempt < MAX_ATTEMPTS:
            query = call_llm([{"role": "user", "content":
                f"База знань: {KB}.\nПерепиши питання як короткий запит для "
                "векторного пошуку: 4-7 слів, лише ключові технічні терміни, "
                "без речень і переліків. Поверни ЛИШЕ запит.\n"
                f"Питання: {question}"}]).strip()
            print(f"[REWRITE] {query!r}")
            continue

        print(f"[GENERATE] {call_llm([
            {'role': 'system', 'content': f'Відповідай ЛИШЕ за контекстом:\n{context}'},
            {'role': 'user', 'content': question}])}")
        return

    print("[CLARIFY] Релевантного контексту не знайшов — уточни питання.")


if __name__ == "__main__":
    try:
        agentic_rag(QUESTION)
        print(f"\n{cost()}  <- у r2 було 1. Agentic RAG не «краще», а дорожче:")
        print("      при стабільному корпусі traditional + reranking дешевший (див. r4).")
    except (LLMUnavailable, EmbedUnavailable) as e:
        print(f"[ЗУПИНКА] {e}")

    # ── Твоя черга ──
    # 1) Постав питання, на яке корпус відповідає одразу, — і подивись, як
    #    зникає гілка [REWRITE], а [COST] падає до рівня r2.
    # 2) Підніми MAX_ATTEMPTS до 4. Скільки коштує впертість і де вона
    #    перестає допомагати?
