import os
import re
import json
import uuid
from pathlib import Path
from dotenv import load_dotenv
from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone

load_dotenv(Path(__file__).parent / '.env')
KEY = os.environ['EMERGENT_LLM_KEY']

EVAL_MODEL = "gpt-4o"
CHAT_MODEL = "gpt-5.4-mini"


async def complete(system: str, prompt: str, model: str = EVAL_MODEL) -> str:
    chat = LlmChat(api_key=KEY, session_id=str(uuid.uuid4()), system_message=system).with_model("openai", model)
    resp = await chat.send_message(UserMessage(text=prompt))
    return str(resp)


def extract_json(text: str):
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        raise ValueError("no JSON found in LLM output")
    return json.loads(m.group(0))


async def stream_chat(system: str, prompt: str, model: str = CHAT_MODEL):
    chat = LlmChat(api_key=KEY, session_id=str(uuid.uuid4()), system_message=system).with_model("openai", model)
    async for ev in chat.stream_message(UserMessage(text=prompt)):
        if isinstance(ev, TextDelta):
            yield ev.content
        elif isinstance(ev, StreamDone):
            break
