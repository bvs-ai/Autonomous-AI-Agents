"""Прогін усіх кроків підряд — перевірка перед лекцією, що все живе.

    .venv/bin/python run_all.py           # усі кроки
    .venv/bin/python run_all.py 3 5 9     # тільки вибрані

Під час лекції зручніше запускати кроки поодинці:
    .venv/bin/python step3_react.py
"""
import subprocess
import sys
import time

STEPS = {
    1: ("step1_setup.py", "Середовище і модель"),
    2: ("step2_tools.py", "Інструменти з Pydantic-схемами"),
    3: ("step3_react.py", "ReAct-агент у LangGraph"),
    4: ("step4_structured.py", "Structured outputs і лог траєкторії"),
    5: ("step5_guards.py", "max_steps, timeout, детекція повторів"),
    6: ("step6_plan_execute.py", "Plan-and-Execute"),
    7: ("step7_checkpointer.py", "SqliteSaver і відновлення"),
    8: ("step8_rag.py", "Agentic RAG з ChromaDB"),
    9: ("step9_hitl.py", "Human-in-the-Loop"),
    10: ("-m pytest test_agents.py -v", "Тести"),
}

wanted = [int(a) for a in sys.argv[1:]] or sorted(STEPS)
failed = []

for n in wanted:
    script, title = STEPS[n]
    print(f"\n{'#'*70}\n# КРОК {n}. {title}\n{'#'*70}")
    t0 = time.time()
    code = subprocess.call([sys.executable, *script.split()])
    print(f"— крок {n}: {'OK' if code == 0 else 'ПОМИЛКА'} за {time.time()-t0:.1f}с")
    if code != 0:
        failed.append(n)

print("\n" + "=" * 70)
print("❌ Впали кроки:", failed) if failed else print("✅ Усі кроки пройшли.")
sys.exit(1 if failed else 0)
