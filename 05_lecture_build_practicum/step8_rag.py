"""КРОК 8. Memory та agentic RAG з ChromaDB.

База знань із 8 документів → Chroma → retriever → інструмент knowledge_search.
Головна ідея agentic RAG: пошук НЕ виконується автоматично на кожен запит,
рішення звертатись до бази знань ухвалює сам агент.

Запуск:  .venv/bin/python step8_rag.py
"""
import json
import os

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, Field

from step1_setup import get_text, llm
from step2_tools import safe_tools
from step3_react import SYSTEM_PROMPT

HERE = os.path.dirname(os.path.abspath(__file__))
CHROMA_DIR = os.path.join(HERE, "chroma_db")

# ── Документи бази знань (у реальному проєкті — завантаження з файлів) ──
documents = [
    Document(
        page_content="LangGraph — це бібліотека для побудови агентних систем як графів станів. "
                     "Вона підтримує цикли, умовні переходи, checkpointing та human-in-the-loop.",
        metadata={"source": "lecture_03", "topic": "langgraph"}
    ),
    Document(
        page_content="ReAct (Reasoning + Acting) — патерн, що чергує кроки міркування та дії. "
                     "Агент аналізує стан, обирає інструмент, отримує результат "
                     "і формує наступне рішення.",
        metadata={"source": "lecture_02", "topic": "react"}
    ),
    Document(
        page_content="Plan-and-Execute розділяє планування та виконання. Planner генерує план, "
                     "executor виконує кроки, replanner адаптує стратегію за результатами.",
        metadata={"source": "lecture_03", "topic": "plan_execute"}
    ),
    Document(
        page_content="Pydantic v2 використовується для створення схем інструментів. BaseModel "
                     "із Field та field_validator забезпечує валідацію входів і виходів.",
        metadata={"source": "lecture_02", "topic": "pydantic"}
    ),
    Document(
        page_content="SqliteSaver — це checkpointer у LangGraph на базі SQLite. "
                     "Зберігає стан після кожного вузла. Потребує контекстного менеджера (with).",
        metadata={"source": "lecture_03", "topic": "checkpointer"}
    ),
    Document(
        page_content="Agentic RAG відрізняється від класичного RAG тим, що агент сам вирішує, "
                     "чи потрібен пошук, як сформулювати запит і чи достатньо результатів.",
        metadata={"source": "lecture_03", "topic": "agentic_rag"}
    ),
    Document(
        page_content="Human-in-the-Loop реалізується через interrupt_before на вузлах графа. "
                     "Виконання зупиняється, стан зберігається, чекає підтвердження оператора.",
        metadata={"source": "lecture_03", "topic": "hitl"}
    ),
    Document(
        page_content="Structured outputs гарантують, що відповідь LLM відповідає Pydantic-схемі. "
                     "Метод with_structured_output повертає типізований об'єкт замість тексту.",
        metadata={"source": "lecture_02", "topic": "structured_outputs"}
    ),
]

# ── Векторне сховище ──
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
vectorstore = Chroma(
    collection_name="course_knowledge",
    embedding_function=embeddings,
    persist_directory=CHROMA_DIR,
)
# Індексуємо лише один раз: інакше при кожному запуску скрипта база
# наповнюється дублікатами тих самих документів.
if vectorstore._collection.count() == 0:
    vectorstore.add_documents(documents)

retriever = vectorstore.as_retriever(search_kwargs={"k": 3})


# ── RAG-інструмент ──
class RAGInput(BaseModel):
    """Вхідні дані для пошуку в базі знань курсу."""
    query: str = Field(..., description="Пошуковий запит до бази знань", min_length=3)


@tool(args_schema=RAGInput)
def knowledge_search(query: str) -> str:
    """Шукає релевантну інформацію в базі знань курсу (лекції, матеріали).
    Використовуй, коли потрібна інформація про LangGraph, ReAct, Plan-and-Execute,
    Pydantic, checkpointer, agentic RAG або HITL."""
    docs = retriever.invoke(query)
    if not docs:
        return json.dumps({"status": "not_found", "query": query})
    results = []
    for d in docs:
        results.append({
            "content": d.page_content,
            "source": d.metadata.get("source", "?"),
            "topic": d.metadata.get("topic", "?"),
        })
    return json.dumps({"status": "ok", "query": query, "results": results}, ensure_ascii=False)


# Розширений набір інструментів із RAG
rag_tools = safe_tools + [knowledge_search]
llm_with_rag_tools = llm.bind_tools(rag_tools)

RAG_SYSTEM_PROMPT = SYSTEM_PROMPT + (
    "\nТакож ти маєш інструмент knowledge_search для пошуку в базі знань курсу. "
    "Використовуй його для питань про LangGraph, ReAct, Plan-and-Execute тощо."
)


def rag_agent_node(state: MessagesState) -> dict:
    """Вузол агента з RAG-можливостями."""
    messages = state["messages"]
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=RAG_SYSTEM_PROMPT)] + messages
    response = llm_with_rag_tools.invoke(messages)
    return {"messages": [response]}


# Побудова RAG-агента
rag_graph = StateGraph(MessagesState)
rag_graph.add_node("agent", rag_agent_node)
rag_graph.add_node("tools", ToolNode(rag_tools))
rag_graph.add_edge(START, "agent")
rag_graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
rag_graph.add_edge("tools", "agent")

rag_agent = rag_graph.compile()


if __name__ == "__main__":
    print(f"✅ ChromaDB: {vectorstore._collection.count()} документів у колекції "
          f"'course_knowledge'.")

    # Спершу — «голий» retriever, без агента: що взагалі повертає пошук
    print("\n🔎 Прямий пошук у сховищі за запитом 'checkpointer':")
    for d in retriever.invoke("checkpointer"):
        print(f"   • [{d.metadata['topic']}] {d.page_content[:70]}...")

    test_rag_queries = [
        "Що таке Plan-and-Execute і чим він відрізняється від ReAct?",
        "Як працює SqliteSaver у LangGraph?",
        "Порахуй 256 * 512 і знайди в базі знань інформацію про structured outputs",
        "Скільки буде 15 * 4?",  # контроль: тут база знань НЕ потрібна
    ]
    for q in test_rag_queries:
        print(f"\n{'='*60}")
        print(f"👤 {q}")
        r = rag_agent.invoke({"messages": [HumanMessage(content=q)]})
        used = [m.name for m in r["messages"] if isinstance(m, ToolMessage)]
        print(f"🔧 Інструменти: {used or '(жодного)'}")
        print(f"🤖 {get_text(r['messages'][-1].content)[:400]}")

    print("\n✅ Agentic RAG працює: у контрольному запиті knowledge_search не викликано — "
          "рішення про пошук ухвалює сам агент.")
