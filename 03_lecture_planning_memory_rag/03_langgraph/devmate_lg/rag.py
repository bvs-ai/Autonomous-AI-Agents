"""Внутрішній цикл: це `../02_rag/r3_agentic_rag.py`, але графом.

Там був `while` у функції — тут `StateGraph` із пʼятьма вузлами. Механіку RAG
пояснювати заново не треба, вона розібрана на r1–r5; дивимось тільки на те, що
змінив фреймворк.

    retrieve → judge ─(ok)──────────→ generate → check_support ─(ok)→ END
                 │                                    │
                 └─(needs_web)→ web_fallback ─────────┘
                                                      │
                       (не підтверджено, спроб < 2) ──┘ назад у retrieve

Чого тут **немає** — вузла «а чи треба взагалі шукати». Self-RAG-токен
`Retrieve: yes/no` (`04:1146`) — це і є рішення моделі покликати інструмент
`search_kb`. Ручний `decide_retrieval` не пишеться: він сховався у фреймворк.

Найцінніший вузол — `check_support`: він дивиться **на відповідь проти
контексту**, а не на контекст проти питання. Це різні перевірки, і першої немає
в жодному з 27 прикладів курсу.
"""
import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.output_parsers import PydanticOutputParser
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .config import MAX_ATTEMPTS, chat_model
from .safety import scan
from .vector_store import search as store_search
from .web_corpus import WEB_DOCS

TOP_K = 3
LAST_TRACE: list[str] = []   # траєкторія останнього виклику, для /trace


# ── Вердикти ──────────────────────────────────────────────────────────────
# Поле з обґрунтуванням мусить бути **actionable**: `missing` іде прямо в
# наступну спробу пошуку, інакше друга спроба не відрізняється від першої.
class DocsVerdict(BaseModel):
    relevant_ids: list[str] = Field(description="id документів, які справді відповідають на питання")
    needs_web: bool = Field(description="true, якщо в нотатках відповіді немає взагалі")
    reason: str = Field(description="одне речення, чому саме так")


class SupportVerdict(BaseModel):
    supported: Literal["yes", "partial", "no"] = Field(description="чи спирається відповідь на контекст")
    missing: str = Field(description="яких саме фактів бракує; порожньо, якщо yes")


class RAGState(TypedDict):
    query: str
    attempts: int
    # Тенант їде у стані підграфа, а не береться з рантайму: підграф — окремий
    # `Runnable`, і залежати від контексту виклику він не повинен. Хто питає,
    # вирішує зовнішній агент (`search_kb`), а не текст питання.
    tenant: str
    docs: list[dict]
    answer: str
    citations: list[str]
    supported: str
    # Стан підграфа нагору не піднімається (див. README), тому траєкторію
    # він веде сам: інакше цикл — чорний ящик. `operator.add` дописує.
    history: Annotated[list[str], operator.add]


def ask(prompt: str, schema: type[BaseModel]) -> BaseModel:
    """Вердикт за схемою.

    `with_structured_output()` тут не використовується свідомо: він примусово
    ставить `tool_choice`, а наш провайдер відповідає «Thinking mode does not
    support this tool_choice». Парсер робить те саме руками — і заодно видно,
    що структурований вивід це просто схема в промпті плюс розбір відповіді.
    """
    parser = PydanticOutputParser(pydantic_object=schema)
    return (chat_model() | parser).invoke(f"{prompt}\n\n{parser.get_format_instructions()}")


def context_of(docs: list[dict]) -> str:
    return "\n".join(f"[{d['id']}] {d['text']}" for d in docs)


# ── Вузли ─────────────────────────────────────────────────────────────────
def retrieve(state: RAGState) -> dict:
    """0 викликів LLM. Запит до векторного сховища: вектор + умова по тенанту.

    У `../02_rag/` тут стояв `search_semantic()` — перебір списку й косинус руками.
    Заміна на Qdrant коштувала одного рядка: сигнатура та сама, `(score, doc)`
    на виході ті самі. Змінилося те, чого в списку не було, — **фільтр як
    частина запиту**: чуже відсікається до ранжування, а не після.
    """
    hits, cut = store_search(state["query"], k=TOP_K, tenant=state["tenant"])
    # Гейт на вході: знайдене — недовірений ввід, як і памʼять (r5).
    docs = [d for _, d in hits if not scan(d["text"])]
    line = "  ".join(f"{d['id']}={s:.3f}" for s, d in hits)
    print(f"[RETRIEVE] {state['query']!r} -> {line}  (tenant={state['tenant']}"
          + (f"; фільтр відсік: {', '.join(cut)}" if cut else "") + ")")
    return {"docs": docs}


def judge(state: RAGState) -> dict:
    """1 виклик LLM. Self-RAG **IsRel** і CRAG **evaluator** злиті в один вузол.

    Порізно це +1 виклик моделі й +1 питання «а чим вони відрізняються», на яке
    в масштабі демо чесної відповіді немає. Розвести назад (`04:1180`) — +25
    рядків і ще один вузол.
    """
    v: DocsVerdict = ask(
        f"Питання: {state['query']}\n\nЗнайдені нотатки:\n{context_of(state['docs'])}\n\n"
        "Які нотатки справді відповідають на питання? Якщо жодна навіть близько "
        "не про це — постав needs_web.", DocsVerdict)
    keep = [d for d in state["docs"] if d["id"] in v.relevant_ids]
    print(f"[JUDGE] relevant={v.relevant_ids} needs_web={v.needs_web} — {v.reason}")
    return {"docs": keep, "history": [f"пошук {state['query']!r} → {v.reason}"]}


def route_after_judge(state: RAGState) -> Literal["web_fallback", "generate"]:
    return "generate" if state["docs"] else "web_fallback"


def web_fallback(state: RAGState) -> dict:
    """0 викликів LLM. CRAG-корекція джерела — і розширення поверхні атаки.

    `scan()` стоїть саме тут, на межі із зовнішнім світом. Заблокований
    документ друкується: студент має побачити, що корекція принесла не лише
    відповідь.
    """
    clean = []
    for d in WEB_DOCS:
        why = scan(d["text"])
        print(f"[WEB] {d['id']}: " + (f"ЗАБЛОКОВАНО — {why}" if why else "ok"))
        if not why:
            clean.append(d)
    return {"docs": clean, "history": ["нотаток не вистачило → зовнішнє джерело"]}


def generate(state: RAGState) -> dict:
    """1 виклик LLM. Відповідь строго за контекстом, з цитатами."""
    docs = state["docs"]
    answer = chat_model().invoke(
        [{"role": "system", "content":
          "Відповідай ЛИШЕ за контекстом нижче. Після кожного твердження став "
          f"цитату у форматі [id]. Якщо контексту бракує — скажи це прямо.\n{context_of(docs)}"},
         {"role": "user", "content": state["query"]}]).content
    print(f"[GENERATE] {len(answer)} символів за {[d['id'] for d in docs]}")
    return {"answer": answer, "citations": [d["id"] for d in docs]}


def check_support(state: RAGState) -> dict:
    """1 виклик LLM. Self-RAG **IsSup**: відповідь проти контексту."""
    v: SupportVerdict = ask(
        f"Контекст:\n{context_of(state['docs'])}\n\nВідповідь:\n{state['answer']}\n\n"
        "Чи кожне твердження відповіді спирається на контекст?", SupportVerdict)
    print(f"[SUPPORT] {v.supported}" + (f" — бракує: {v.missing}" if v.missing else ""))
    # Наступна спроба шукає з дописаним `missing`. Окремого вузла `rewrite` з
    # викликом моделі немає навмисно: чого бракує, вже сказав критик.
    query = f"{state['query']} {v.missing}".strip() if v.supported != "yes" else state["query"]
    return {"attempts": state["attempts"] + 1, "query": query, "supported": v.supported,
            "history": [f"підтвердження: {v.supported} {v.missing}".strip()]}


def route_after_support(state: RAGState) -> Literal["retrieve", "__end__"]:
    """Бюджет замість впертості: вичерпали спроби — віддаємо як є, чесно."""
    if state["supported"] == "yes" or state["attempts"] >= MAX_ATTEMPTS:
        return END
    return "retrieve"


def build_rag_graph():
    g = StateGraph(RAGState)
    for node in (retrieve, judge, web_fallback, generate, check_support):
        g.add_node(node.__name__, node)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "judge")
    g.add_conditional_edges("judge", route_after_judge)
    g.add_edge("web_fallback", "generate")
    g.add_edge("generate", "check_support")
    g.add_conditional_edges("check_support", route_after_support)
    # Ні checkpointer, ні store: підграф живе один виклик інструмента.
    return g.compile()
