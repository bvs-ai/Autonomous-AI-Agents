"""m1 — MCP-сервер на FastMCP: один tool, один resource, один prompt.

    python m1_server.py            # запуск по stdio (так його стартують клієнти з m0/m2/m3)
    python m1_server.py schema     # що саме з цього файлу бачить модель

Уся «база даних» — список нижче. Сенс демо не в даних, а в тому, що з коду
нижче автоматично народжується протокол: type hints стають JSON Schema,
докстрінги — описом для LLM.
"""
import asyncio
import json
import sys

from mcp.server.fastmcp import FastMCP

# ── «База даних»: продажі у тис. грн ─────────────────────────────────────────
SALES = [
    {"region": "Північ", "quarter": "Q1", "revenue": 1200},
    {"region": "Північ", "quarter": "Q2", "revenue": 1310},
    {"region": "Південь", "quarter": "Q1", "revenue": 980},
    {"region": "Південь", "quarter": "Q2", "revenue": 1040},
    {"region": "Захід", "quarter": "Q1", "revenue": 1500},
    {"region": "Захід", "quarter": "Q2", "revenue": 870},   # обвал, його шукає агент у m3
    {"region": "Схід", "quarter": "Q1", "revenue": 640},
    {"region": "Схід", "quarter": "Q2", "revenue": 700},
]

mcp = FastMCP("sales", log_level="WARNING")   # інакше сервер сипле INFO у stderr клієнта


# ── Tool: дія, яку вирішує викликати МОДЕЛЬ ──────────────────────────────────
@mcp.tool()
def revenue(region: str, quarter: str) -> int:
    """Продажі одного регіону за квартал, у тис. грн.

    region: Північ | Південь | Захід | Схід
    quarter: Q1 | Q2
    """
    rows = [r for r in SALES if r["region"] == region and r["quarter"] == quarter]
    if not rows:
        # Помилку віддаємо як дані, а не як виняток: агент має шанс виправитись.
        raise ValueError(f"немає даних: {region} / {quarter}")
    return rows[0]["revenue"]


@mcp.tool()
def compare_quarters(quarter_a: str, quarter_b: str) -> dict:
    """Порівняти два квартали по всіх регіонах: приріст продажів у відсотках.

    Повертає {регіон: зміна у %}. Відʼємне значення — падіння.
    """
    out = {}
    for region in sorted({r["region"] for r in SALES}):
        a = revenue(region, quarter_a)
        b = revenue(region, quarter_b)
        out[region] = round((b - a) / a * 100, 1)
    return out


# ── Resource: дані, які підтягує ЗАСТОСУНОК (модель їх не «викликає») ────────
@mcp.resource("sales://schema")
def schema() -> str:
    """Опис набору даних: які є регіони, квартали й одиниці виміру."""
    return json.dumps({
        "regions": sorted({r["region"] for r in SALES}),
        "quarters": sorted({r["quarter"] for r in SALES}),
        "units": "тис. грн",
        "rows": len(SALES),
    }, ensure_ascii=False)


# ── Prompt: шаблон, який обирає КОРИСТУВАЧ ───────────────────────────────────
@mcp.prompt()
def quarter_report(quarter: str) -> str:
    """Шаблон запиту на квартальний звіт."""
    return (f"Склади звіт по продажах за {quarter}. Спочатку подивись sales://schema, "
            f"потім візьми цифри інструментами. Познач регіони з падінням.")


if __name__ == "__main__":
    if sys.argv[1:2] == ["schema"]:
        # Те саме, що клієнт отримає у відповідь на tools/list.
        for t in asyncio.run(mcp.list_tools()):
            print(json.dumps(t.model_dump(include={"name", "description", "inputSchema"}),
                             ensure_ascii=False, indent=2))
    else:
        mcp.run()   # запуск по stdio (так його стартують клієнти з m0/m2/m3)
