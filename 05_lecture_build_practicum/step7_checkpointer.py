"""КРОК 7. Checkpointer (SqliteSaver) та відновлення.

Checkpointer зберігає стан графа після кожного вузла. Сесія ідентифікується
thread_id; get_state() дає знімок стану; «відновлення» — це просто новий
екземпляр агента з тим самим checkpointer і тим самим thread_id.

Запуск:  .venv/bin/python step7_checkpointer.py
"""
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from step1_setup import get_text
from step3_react import react_graph


def demo_checkpointer():
    """Демонстрація checkpointer: запуск, збереження, відновлення."""

    # ВАЖЛИВО: SqliteSaver використовується як контекстний менеджер,
    # інакше з'єднання з базою не буде коректно відкрито/закрито.
    with SqliteSaver.from_conn_string("checkpoints.db") as checkpointer:
        
        # Чистий старт демонстрації: прибираємо сліди попередніх запусків,
        # інакше агент «пам'ятає» ім'я ще до Запиту 1 і демо втрачає сенс.
        checkpointer.delete_thread("demo-thread-001")
        checkpointer.delete_thread("demo-thread-002")
        
        # Компілюємо ReAct-граф із Кроку 3, але вже з checkpointer
        persistent_agent = react_graph.compile(checkpointer=checkpointer)

        thread_id = "demo-thread-001"
        config = {"configurable": {"thread_id": thread_id}}

        # 1) Перший запит — стан зберігається
        print("=" * 60)
        print("📌 Запит 1: починаємо діалог")
        result1 = persistent_agent.invoke(
            {"messages": [HumanMessage(content="Мене звати Олексій. Запам'ятай це.")]},
            config=config
        )
        print(f"🤖 {get_text(result1['messages'][-1].content)}")

        # 2) Другий запит — агент має доступ до попереднього контексту
        print("\n📌 Запит 2: перевіряємо, що контекст збережено")
        result2 = persistent_agent.invoke(
            {"messages": [HumanMessage(content="Як мене звати?")]},
            config=config
        )
        print(f"🤖 {get_text(result2['messages'][-1].content)}")

        # 3) Отримуємо знімок стану
        snapshot = persistent_agent.get_state(config)
        print("\n📊 Стан checkpointer:")
        print(f"   Thread: {thread_id}")
        print(f"   Кількість повідомлень: {len(snapshot.values.get('messages', []))}")
        print(f"   Конфігурація: {snapshot.config}")
        print(f"   Наступний вузол: {snapshot.next or '(граф завершено)'}")

        # 3b) Історія чекпоінтів — по одному запису на крок графа
        history = list(persistent_agent.get_state_history(config))
        print(f"   Збережених чекпоінтів у гілці: {len(history)}")

        # 4) Симуляція відновлення: НОВИЙ екземпляр агента
        # з тим самим checkpointer та thread_id
        print("\n🔄 Симуляція відновлення (новий екземпляр агента)...")
        restored_agent = react_graph.compile(checkpointer=checkpointer)
        result3 = restored_agent.invoke(
            {"messages": [HumanMessage(content="Нагадай, як мене звати, і порахуй 42 * 58")]},
            config=config
        )
        print(f"🤖 {get_text(result3['messages'][-1].content)}")

        # 5) Інший thread_id — інша сесія, спільної пам'яті немає
        print("\n🧪 Контроль: той самий агент, але thread_id інший")
        other = {"configurable": {"thread_id": "demo-thread-002"}}
        result4 = restored_agent.invoke(
            {"messages": [HumanMessage(content="Як мене звати?")]},
            config=other
        )
        print(f"🤖 {get_text(result4['messages'][-1].content)}")

    print("\n✅ Демонстрація checkpointer завершена.")


if __name__ == "__main__":
    demo_checkpointer()
