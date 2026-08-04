"""Практика R6 — векторна БД замість ручного косинуса: як виглядає API.

`corpus.py::search_semantic()` тримає всі вектори в списку Python і рахує
косинус руками (`cosine()`, `corpus.py:101`) — навмисно, щоб механізм було
видно. Тут той самий корпус і ті самі вектори з `vectors.json` кладуться в
Qdrant (embedded `:memory:`, без сервера й без Docker).

Дивимось на три речі, і саме в такому порядку:

    [API]    з чого складається робота зі сховищем: колекція → upsert → query
    [SWAP]   оцінки збігаються з ручним косинусом, а сигнатура функції — та сама
    [FILTER] фільтр по payload — те, чого список Python не вміє в принципі

Вектори беруться ті самі, без перерахунку: **сховище ембедингів не рахує**.
Воно приймає готовий список чисел, і чия це модель, йому байдуже. Обовʼязкових
умов рівно дві: документи й запити ембеднуті ОДНІЄЮ моделлю (інакше вони в
різних просторах і схожість нічого не означає), а `size` колекції дорівнює
розмірності цієї моделі — у нас bge-m3, тобто 1024. Тому оцінки Qdrant і
ручного косинуса збігаються — це й видно у сцені `[SWAP]`.

Головне не в тому, що БД «швидша» (на девʼяти документах вона не швидша), а в
тому, що пошук стає **запитом до сховища**: вектор плюс умова. Саме умова й
робить це продакшном — нотатка d9 у корпусі про це прямо й написана.

Встановити (лише для цього прикладу):
    pip install qdrant-client
Запуск:
    python r6_vectordb.py
"""
from corpus import DOCS, EmbedUnavailable, embed, search_semantic

QUERY = "таймзони"          # той самий запит, що в r1, сцена «СЛОВОФОРМА»
TOP_K = 3
COLLECTION = "notes"

# Payload — це метадані документа поруч із вектором. Тут проставлені руками;
# у проді вони приїжджають із того ж місця, звідки й текст.
TOPIC = {"d1": "agents", "d2": "infra", "d3": "tests", "d4": "tests",
         "d5": "rag", "d6": "agents", "d7": "agents", "d8": "misc", "d9": "infra"}


def build_collection(client) -> None:
    """Колекція + завантаження точок. Це весь «деплой» векторного сховища."""
    from qdrant_client.models import Distance, PointStruct, VectorParams

    vectors = {d["id"]: embed(d["text"]) for d in DOCS}   # з кешу, без мережі
    dims = len(next(iter(vectors.values())))

    # `size` і `distance` задаються при створенні й потім не міняються: колекція
    # прибита до конкретної моделі ембедингів. Змінили модель — перезаливати всі
    # вектори, іншого шляху немає. Це головне архітектурне обмеження векторних БД.
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=dims, distance=Distance.COSINE),
    )
    client.upsert(
        collection_name=COLLECTION,
        points=[
            # `id` у Qdrant — тільки int або UUID, рядок 'd1' сюди не можна.
            # Тому справжній ідентифікатор документа живе в payload.
            PointStruct(
                id=i,
                vector=list(vectors[d["id"]]),
                payload={"doc_id": d["id"], "text": d["text"], "topic": TOPIC[d["id"]]},
            )
            for i, d in enumerate(DOCS)
        ],
    )


def search_qdrant(client, query: str, k: int = TOP_K, topic: str | None = None
                  ) -> list[tuple[float, dict]]:
    """Пошук у сховищі. **Сигнатура навмисно така сама, як у `search_semantic`**.

    Через це заміна ретрівера нікуди більше не тягнеться: вузол `retrieve()`
    у графі отримує ті самі `(score, doc)` і не знає, звідки вони.

    `query_filter` — те, заради чого БД і ставлять: умова застосовується ДО
    ранжування, тобто чуже до видачі не доходить взагалі, а не відсіюється
    потім. Нотатка d9 каже рівно це: «кожен запит фільтрується по tenant_id,
    інакше дані одного клієнта потраплять іншому» (OWASP LLM08).
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    flt = None
    if topic:
        flt = Filter(must=[FieldCondition(key="topic", match=MatchValue(value=topic))])

    # `query_points` — актуальний API (`search` прибрано в qdrant-client>=1.15).
    hits = client.query_points(
        collection_name=COLLECTION, query=list(embed(query)), limit=k, query_filter=flt
    ).points
    return [(h.score, {"id": h.payload["doc_id"], "text": h.payload["text"]}) for h in hits]


def show(tag: str, hits: list[tuple[float, dict]]) -> None:
    print(f"[{tag}] " + "  ".join(f"{d['id']}={s:.3f}" for s, d in hits))


def main() -> None:
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        print("[ЗУПИНКА] Немає qdrant-client. Постав: pip install qdrant-client")
        return

    # Ембедований режим: увесь Qdrant всередині процесу, ані сервера, ані Docker.
    # Персистентність — заміна одного аргументу: QdrantClient(path="./qdrant_data").
    # Справжній сервер — так само один аргумент: QdrantClient(url="http://...").
    client = QdrantClient(":memory:")

    print(f"[API] колекція '{COLLECTION}': create_collection → upsert → query_points")
    build_collection(client)
    print(f"[API] завантажено точок: {client.count(COLLECTION).count}\n")

    print(f"[QUERY] {QUERY!r}\n")
    show("QDRANT", search_qdrant(client, QUERY))
    show("MANUAL", search_semantic(QUERY, k=TOP_K))
    print("[SWAP] оцінки збігаються: Qdrant не шукає інакше, він рахує той самий")
    print("       косинус за іншим API. І повертає той самий тип — тому підміна")
    print("       ретрівера у графі нічого більше не ламає.\n")

    show("FILTER topic=infra", search_qdrant(client, QUERY, topic="infra"))
    show("FILTER topic=tests", search_qdrant(client, QUERY, topic="tests"))
    print("[FILTER] той самий вектор запиту, різні дозволені множини документів.")
    print("         Ось цього ручний cosine() не вміє в принципі: щоб відсікти")
    print("         чуже, йому довелося б спершу порахувати схожість з чужим.\n")

    print("[ВИСНОВОК] на 9 документах БД не дає ні швидкості, ні кращої видачі —")
    print("           і це чесний результат. Вона дає інше: індекс HNSW замість")
    print("           повного перебору, фільтр як частину запиту, персистентність")
    print("           і конкурентний запис. Усе це видно не тут, а на мільйоні.")


if __name__ == "__main__":
    try:
        main()
    except EmbedUnavailable as e:
        print(f"[ЗУПИНКА] {e}")

    # ── Твоя черга ──
    # 1) Заміни `Distance.COSINE` на `Distance.DOT` і поясни, чому оцінки
    #    зміняться, а порядок документів — майже ні (підказка: подивись,
    #    чи нормовані вектори bge-m3 вже на виході).
    # 2) Постав `QdrantClient(path="./qdrant_data")`, запусти двічі й подивись,
    #    що станеться на `create_collection` вдруге. Полагодь.
    # 3) Прочитай `../03_langgraph/devmate_lg/vector_store.py`: там та сама
    #    колекція, але фільтр по `tenant`, а не по `topic`, і береться він з
    #    `Context` агента. Поясни, чому фільтр не можна брати з тексту питання.
