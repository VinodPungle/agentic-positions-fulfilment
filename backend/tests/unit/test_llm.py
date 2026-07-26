"""Unit tests for llm.py: the JSON-extraction helper (pure function, high value to
test directly) and the OpenAI call wrappers' error-logging-then-reraise behavior.
"""
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openai import OpenAIError

import llm


def test_extract_json_parses_embedded_json():
    text = 'Here is the result:\n{"a": 1, "b": [2, 3]}\nEnd.'
    assert llm.extract_json(text) == {"a": 1, "b": [2, 3]}


def test_extract_json_raises_value_error_when_absent():
    with pytest.raises(ValueError):
        llm.extract_json("no json here at all")


def _fake_completion(content):
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


@pytest.mark.asyncio
async def test_complete_returns_message_content(monkeypatch):
    monkeypatch.setattr(llm.client.chat.completions, 'create',
                        AsyncMock(return_value=_fake_completion('hello')))
    result = await llm.complete('system', 'prompt')
    assert result == 'hello'


@pytest.mark.asyncio
async def test_complete_logs_and_reraises_on_api_error(monkeypatch, caplog):
    monkeypatch.setattr(llm.client.chat.completions, 'create',
                        AsyncMock(side_effect=OpenAIError('rate limited')))
    with caplog.at_level(logging.WARNING):
        with pytest.raises(OpenAIError):
            await llm.complete('system', 'prompt')
    assert any('OpenAI API call failed' in r.message for r in caplog.records)
