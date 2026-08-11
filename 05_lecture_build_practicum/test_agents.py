"""КРОК 10. Тести (pytest).

На відміну від конспекту (де схеми дублювались у файл тестів через %%writefile
у Colab), тут схеми імпортуються з step2_tools — код один, дублікатів немає.

Швидкі тести не потребують API-ключа взагалі:
    .venv/bin/python -m pytest test_agents.py -v

Живий тест ReAct-циклу (реальні виклики LLM) вмикається окремо:
    RUN_LIVE_TESTS=1 .venv/bin/python -m pytest test_agents.py -v
"""
import json
import os

import pytest
from pydantic import ValidationError

from step2_tools import (
    CalcInput,
    DateTimeInput,
    FileWriteInput,
    HttpInput,
    WikiInput,
    calculator,
    current_datetime,
    file_write,
)

# ══════════════════════════════════════════════
# Тести валідації Pydantic-схем (без API)
# ══════════════════════════════════════════════


class TestPydanticSchemas:
    def test_calc_input_valid(self):
        inp = CalcInput(expression="2 + 2")
        assert inp.expression == "2 + 2"

    def test_calc_input_invalid_chars(self):
        # Класична спроба ін'єкції коду — валідатор має її відхилити
        with pytest.raises(ValidationError):
            CalcInput(expression="import os; os.system('rm -rf /')")

    def test_calc_input_too_long(self):
        with pytest.raises(ValidationError):
            CalcInput(expression="1+" * 200)

    def test_wiki_input_valid(self):
        inp = WikiInput(query="Python", lang="uk")
        assert inp.lang == "uk"

    def test_wiki_input_invalid_lang(self):
        with pytest.raises(ValidationError):
            WikiInput(query="test", lang="xx")

    def test_wiki_input_query_too_short(self):
        with pytest.raises(ValidationError):
            WikiInput(query="a")

    def test_file_write_path_traversal(self):
        with pytest.raises(ValidationError):
            FileWriteInput(path="../etc/passwd", content="hack")

    def test_file_write_absolute_path(self):
        with pytest.raises(ValidationError):
            FileWriteInput(path="/etc/passwd", content="hack")

    def test_file_write_valid(self):
        inp = FileWriteInput(path="output/report.txt", content="Hello")
        assert inp.path == "output/report.txt"

    def test_http_input_no_scheme(self):
        with pytest.raises(ValidationError):
            HttpInput(url="example.com")

    def test_http_input_valid(self):
        inp = HttpInput(url="https://example.com")
        assert inp.url == "https://example.com"
        assert inp.timeout_sec == 10  # значення за замовчуванням

    def test_http_input_timeout_out_of_range(self):
        with pytest.raises(ValidationError):
            HttpInput(url="https://example.com", timeout_sec=999)

    def test_datetime_input_invalid_format(self):
        with pytest.raises(ValidationError):
            DateTimeInput(format="unix")


# ══════════════════════════════════════════════
# Тести інструментів (без мережі)
# ══════════════════════════════════════════════


class TestTools:
    def test_calculator_ok(self):
        out = json.loads(calculator.invoke({"expression": "1234 * 5678 + 99"}))
        assert out["status"] == "ok"
        assert out["result"] == 7006751

    def test_calculator_power(self):
        out = json.loads(calculator.invoke({"expression": "2^10 + 3^5"}))
        assert out["status"] == "ok"
        assert out["result"] == 1267

    def test_calculator_division_by_zero_is_handled(self):
        # Інструмент не має падати: помилка повертається у полі status
        out = json.loads(calculator.invoke({"expression": "1/0"}))
        assert out["status"] in ("ok", "error")

    def test_calculator_rejects_injection(self):
        with pytest.raises(ValidationError):
            calculator.invoke({"expression": "__import__('os').system('ls')"})

    def test_current_datetime_day(self):
        out = json.loads(current_datetime.invoke({"format": "day"}))
        assert out["status"] == "ok"
        assert out["value"] in {"Понеділок", "Вівторок", "Середа", "Четвер",
                                "П'ятниця", "Субота", "Неділя"}

    def test_file_write_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out = json.loads(file_write.invoke({"path": "out.txt", "content": "привіт"}))
        assert out["status"] == "ok"
        assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "привіт"

    def test_file_write_blocks_traversal(self):
        with pytest.raises(ValidationError):
            file_write.invoke({"path": "../hack.txt", "content": "x"})


# ══════════════════════════════════════════════
# Живий тест ReAct-циклу (потребує API-ключа)
# ══════════════════════════════════════════════


@pytest.mark.skipif(not os.getenv("RUN_LIVE_TESTS"),
                    reason="Живий виклик LLM: запускати з RUN_LIVE_TESTS=1")
class TestReActLive:
    def test_react_uses_calculator(self):
        from langchain_core.messages import HumanMessage, ToolMessage

        from step3_react import react_agent

        # HumanMessage, а не dict: {"role": ..., "content": ...} працює в рантаймі,
        # але не проходить перевірку типів — MessagesState чекає list[AnyMessage].
        result = react_agent.invoke(
            {"messages": [HumanMessage(content="Скільки буде 1234 * 5678 + 99?")]}
        )
        used = [m.name for m in result["messages"] if isinstance(m, ToolMessage)]
        assert "calculator" in used
        assert result["messages"][-1].content  # фінальна відповідь не порожня
