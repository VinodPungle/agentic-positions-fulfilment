"""Unit tests for extract_name_email — covers the two fallback branches added in
the exception-handling pass (OpenAIError and unparseable-output) to prove the
function degrades gracefully instead of breaking CV upload for the whole batch.
"""
import logging
import pytest
from openai import OpenAIError

import llm
import server


@pytest.mark.asyncio
async def test_uses_llm_result_when_available(monkeypatch):
    async def fake_complete(system, prompt, model=None):
        return '{"name": "Ada Lovelace", "email": "ada@example.com"}'
    monkeypatch.setattr(llm, 'complete', fake_complete)

    result = await server.extract_name_email('some cv text', fallback_name='fallback')
    assert result == {'name': 'Ada Lovelace', 'email': 'ada@example.com'}


@pytest.mark.asyncio
async def test_falls_back_to_regex_and_filename_on_api_error(monkeypatch, caplog):
    async def failing_complete(system, prompt, model=None):
        raise OpenAIError('service unavailable')
    monkeypatch.setattr(llm, 'complete', failing_complete)

    cv_text = 'Contact: jane.doe@example.com for more info.'
    with caplog.at_level(logging.WARNING):
        result = await server.extract_name_email(cv_text, fallback_name='Jane Fallback')

    assert result == {'name': 'Jane Fallback', 'email': 'jane.doe@example.com'}
    assert any('LLM identity extraction call failed' in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_falls_back_when_llm_output_has_no_json(monkeypatch, caplog):
    async def unparseable_complete(system, prompt, model=None):
        return "I couldn't determine the candidate's name."
    monkeypatch.setattr(llm, 'complete', unparseable_complete)

    cv_text = 'No email address in this CV at all.'
    with caplog.at_level(logging.WARNING):
        result = await server.extract_name_email(cv_text, fallback_name='No Email Fallback')

    assert result == {'name': 'No Email Fallback', 'email': ''}
    assert any('unparseable output' in r.message for r in caplog.records)
