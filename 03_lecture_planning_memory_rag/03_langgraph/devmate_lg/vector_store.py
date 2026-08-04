"""Векторне сховище корпусу: Qdrant замість списку в памʼяті процесу.

У `../02_rag/` ретрівер — це `search_semantic()`: список векторів і косинус руками
(`corpus.py:101`). Так зроблено навмисно, щоб механізм було видно. Але для
блоку, який називається «умовно-продакшн», перебір списку — найслабше місце:
у ньому немає ні індексу, ні фільтра, ні персистентності.

Тут той самий корпус і ті самі вектори з `../02_rag/vectors.json` лежать у Qdrant
(embedded `:memory:`: ані сервера, ані Docker, ані мережі — див. `../02_rag/r6_vectordb.py`,
де цей самий API розібраний окремо й повільно).

Змінилося рівно одне, зате принципове: **пошук став запитом до сховища —
вектор плюс умова**. Умова тут — `tenant`, і береться вона з `Context` агента,
а не з тексту питання. Це та сама ізоляція адресою, що в `memory_tools.facts_ns()`
для памʼяті (`04:1683`, OWASP LLM08), тільки для корпусу: памʼять ізолюється
простором імен, корпус — фільтром по payload.

Щоб фільтр було видно, а не тільки згадано, у сховищі лежить чужа нотатка `g1`:
дослівна копія `d3` (тести запускаються через pytest -q), але з `tenant="globex"`.
Текст той самий, тому за схожістю вона завжди поруч із `d3` — і не потрапляє у
видачу **тільки** через фільтр. Її вектор береться з кеша від `d3`: окремий
рахувати нема чим і не треба.
"""
from qdrant_client import QdrantClient
from qdrant_client.models import (Distance, FieldCondition, Filter, MatchValue,
                                  PointStruct, VectorParams)

# `.config` уже поклав `../rag` у `sys.path`.
from corpus import DOCS, embed

COLLECTION = "notes"
TENANT = "acme"          # тенант, якому належать нотатки нашого проєкту
FOREIGN_ID = "g1"        # чужа копія d3 — щоб фільтр було на чому перевірити

_client: QdrantClient | None = None


def _points() -> list[PointStruct]:
    """Точки колекції: вектор + payload. `id` у Qdrant — лише int або UUID,
    тому справжній ідентифікатор документа живе в payload."""
    points = [
        PointStruct(id=i, vector=list(embed(d["text"])),
                    payload={"doc_id": d["id"], "text": d["text"], "tenant": TENANT})
        for i, d in enumerate(DOCS)
    ]
    twin = next(d for d in DOCS if d["id"] == "d3")
    points.append(
        PointStruct(id=len(points), vector=list(embed(twin["text"])),
                    payload={"doc_id": FOREIGN_ID, "text": twin["text"], "tenant": "globex"})
    )
    return points


def store() -> QdrantClient:
    """Клієнт зі створеною й наповненою колекцією. Створюється один раз.

    `:memory:` — увесь Qdrant усередині процесу. Персистентність і справжній
    сервер — заміна одного аргументу: `QdrantClient(path="./qdrant_data")` або
    `QdrantClient(url="http://localhost:6333")`. Решта коду не змінюється.
    """
    global _client
    if _client is not None:
        return _client

    client = QdrantClient(":memory:")
    dims = len(embed(DOCS[0]["text"]))
    # `size` і `distance` прибиті до моделі ембедингів назавжди: змінили модель —
    # перезаливайте колекцію. Це головне архітектурне обмеження векторних БД.
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=dims, distance=Distance.COSINE),
    )
    client.upsert(collection_name=COLLECTION, points=_points())
    _client = client
    return client


def _hits(client, qv: list[float], k: int, tenant: str | None):
    flt = (Filter(must=[FieldCondition(key="tenant", match=MatchValue(value=tenant))])
           if tenant else None)
    return client.query_points(collection_name=COLLECTION, query=qv,
                               limit=k, query_filter=flt).points


def search(query: str, k: int, tenant: str) -> tuple[list[tuple[float, dict]], list[str]]:
    """Пошук по корпусу тенанта.

    Повертає те саме, що `search_semantic()` — список `(score, doc)`, — тому
    вузол `retrieve()` від заміни ретрівера не змінився ніде, крім одного рядка.

    Другим значенням іде перелік чужих документів, які фільтр відсік. У проді
    цього немає (там просто нікого не цікавить, чого ти не побачив), тут воно
    друкується на екран: інакше про фільтр доводиться вірити на слово.
    """
    client = store()
    qv = list(embed(query))
    allowed = _hits(client, qv, k, tenant)
    kept = {h.payload["doc_id"] for h in allowed}
    cut = [h.payload["doc_id"] for h in _hits(client, qv, k, None)
           if h.payload["doc_id"] not in kept]
    return ([(h.score, {"id": h.payload["doc_id"], "text": h.payload["text"]})
             for h in allowed], cut)
