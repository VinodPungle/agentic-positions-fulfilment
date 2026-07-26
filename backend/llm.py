import os
import re
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAIError

load_dotenv(Path(__file__).parent / '.env')

logger = logging.getLogger(__name__)

_OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
if not _OPENAI_API_KEY:
    logger.critical('OPENAI_API_KEY environment variable is required')
    raise RuntimeError('OPENAI_API_KEY environment variable is required')

client = AsyncOpenAI(api_key=_OPENAI_API_KEY)

EVAL_MODEL = os.environ.get('EVAL_MODEL', 'gpt-4o')
CHAT_MODEL = os.environ.get('CHAT_MODEL', 'gpt-4o-mini')


async def complete(system: str, prompt: str, model: str = None) -> str:
    chosen_model = model or EVAL_MODEL
    # Log length, not content — prompts routinely contain candidate CVs/JD text,
    # which we don't want landing in App Insights.
    logger.debug('LLM complete() call: model=%s prompt_chars=%d', chosen_model, len(prompt))
    try:
        resp = await client.chat.completions.create(
            model=chosen_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
    except OpenAIError:
        # Re-raised, not swallowed: callers decide how to degrade (fallback value,
        # HTTP 502, etc.) — this layer's job is just to make the failure visible.
        logger.warning('OpenAI API call failed: model=%s', chosen_model, exc_info=True)
        raise
    return resp.choices[0].message.content or ""


def extract_json(text: str):
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        raise ValueError("no JSON found in LLM output")
    return json.loads(m.group(0))


async def stream_chat(system: str, prompt: str, model: str = None):
    chosen_model = model or CHAT_MODEL
    logger.debug('LLM stream_chat() call: model=%s prompt_chars=%d', chosen_model, len(prompt))
    try:
        stream = await client.chat.completions.create(
            model=chosen_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except OpenAIError:
        logger.warning('OpenAI streaming call failed: model=%s', chosen_model, exc_info=True)
        raise
