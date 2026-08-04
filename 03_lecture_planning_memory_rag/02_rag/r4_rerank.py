"""Практика R4 — САМОСТІЙНА. Reranking: другий, уважніший погляд на видачу.

Ембединг рахує вектор документа НАОСЛІП, не знаючи запиту: один вектор на
всі майбутні питання. Cross-encoder читає пару «запит + документ» разом і
тому бачить те, чого не бачить косинус. Ціна — швидкість, тому його пускають
не на весь корпус, а на 20-50 кандидатів від векторного пошуку (див. d5).

Запит той самий, на якому спіткнувся r3: правильна нотатка d1 у top-5 є,
але лежить не першою. Питання завдання — чи підніме її reranker, і чи
вистачило б цього замість дорогої гілки [REWRITE].

Корпус тут АНГЛІЙСЬКИЙ. Локальні reranker'и FlashRank
навчені на англійських парах ms-marco: на українському тексті модель видає
всім кандидатам майже однакову оцінку (~0.999) і порядку не змінює взагалі.
Це замір, а не здогад — повтори його в завданні 2.

Встановити (лише для цього завдання, на лекції не потрібно):
    pip install flashrank
Запуск:
    python r4_rerank.py
"""
from corpus import EmbedUnavailable, search_semantic

# Ті самі девʼять нотаток, що в corpus.py, англійською — під мову моделі.
EN_DOCS = [
    {"id": "d1", "text": "A checkpointer saves a snapshot of the state after every "
                         "step, so the agent resumes from where it stopped instead "
                         "of starting over."},
    {"id": "d2", "text": "The report scheduler computes deadlines using the user's timezones."},
    {"id": "d3", "text": "Project tests are run with the command pytest -q."},
    {"id": "d4", "text": "The old unittest runner is no longer supported, do not run "
                         "tests with it."},
    {"id": "d5", "text": "Reranking with a cross-encoder reorders results: the vector "
                         "store returns 20-50 candidates, the reranker keeps 3-5."},
    {"id": "d6", "text": "Plan-and-execute separates planning from execution: a strong "
                         "model plans rarely, a cheap one runs the steps."},
    {"id": "d7", "text": "Long message history is compressed into a summary, but the "
                         "head and tail of the dialogue stay intact."},
    {"id": "d8", "text": "Python is a general-purpose programming language."},
    {"id": "d9", "text": "Every request to the store must be filtered by tenant_id, "
                         "otherwise one client's data leaks to another."},
]
EN_QUERY = "how do I make a long running task survive a service restart"


def main() -> None:
    try:
        from flashrank import Ranker, RerankRequest
    except ImportError:
        print("[ЗУПИНКА] Немає flashrank. Постав: pip install flashrank")
        return

    hits = search_semantic(EN_QUERY, k=5, docs=EN_DOCS)
    print(f"[QUERY] {EN_QUERY}\n")
    print("[ДО]    " + "  ".join(f"{d['id']}={s:.3f}" for s, d in hits))

    # max_length підбирається під реальну довжину query+passage: завищений
    # (512 замість потрібних 128-256) просто уповільнює роботу.
    ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2", max_length=256,
                    cache_dir="./flashrank_cache")
    ranked = ranker.rerank(RerankRequest(
        query=EN_QUERY, passages=[{"id": d["id"], "text": d["text"]} for _, d in hits]))

    print("[ПІСЛЯ] " + "  ".join(f"{r['id']}={float(r['score']):.1e}" for r in ranked))
    print("\nОцінки двох етапів НЕ порівнюються між собою: косинус — це кут між")
    print("векторами, оцінка reranker'а — вихід класифікатора (тут вона крихітна")
    print("в абсолютних числах). Порівнювати можна тільки ПОРЯДОК.")


if __name__ == "__main__":
    try:
        main()
    except EmbedUnavailable as e:
        print(f"[ЗУПИНКА] {e}")

    # ── Твоя черга ──
    # 1) Постав max_length=32, потім 512. Що змінилось у порядку, а що в часі
    #    роботи? Заміряй time.perf_counter(), не вір відчуттю.
    # 2) Підстав у EN_DOCS український корпус з corpus.py, не міняючи більше
    #    нічого. Подивись на оцінки — і сформулюй, чому «локальний reranker»
    #    у резюме архітектури треба одразу писати з назвою мови.
    # 3) Порахуй, скільки коштував би rerank усіх 9 документів проти 5, і
    #    прикинь цю різницю на корпус у 100 000 нотаток.
    # 4) Головне: r3 витратив на це саме питання 5 викликів LLM. Скільки
    #    коштує reranking — і що дешевше при стабільному корпусі?
