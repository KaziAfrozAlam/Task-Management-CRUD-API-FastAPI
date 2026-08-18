import os
import re
import json
from pathlib import Path
from openai import OpenAI
from pydantic import ValidationError
from llm.schema import TriageOutput

PROMPT_PATH = Path(__file__).parent / "prompts" / "triage-v1.md"


def get_client():
    return OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
    )


def load_prompt():
    return PROMPT_PATH.read_text()


def _extract_json(text: str) -> str:
    """Strip code fences / stray text, return the first {...} block."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


def _call_raw(client, system_prompt: str, messages_extra: list) -> str:
    res = client.chat.completions.create(
        model=os.environ["LLM_MODEL"],
        temperature=0.2,
        messages=[{"role": "system", "content": system_prompt}] + messages_extra,
    )
    return res.choices[0].message.content


def call_triage_model(text: str) -> TriageOutput:
    """
    Calls the model, parses + validates the answer.
    On failure, makes one repair call. On second failure, raises ValueError
    with the raw output and error attached for the caller to quarantine.
    """
    client = get_client()
    system_prompt = load_prompt()

    raw = _call_raw(client, system_prompt, [{"role": "user", "content": text}])

    parsed, error = _try_parse(raw)
    if parsed is not None:
        return parsed

    # Repair retry — one extra call only
    repair_messages = [
        {"role": "user", "content": text},
        {"role": "assistant", "content": raw},
        {
            "role": "user",
            "content": (
                f"Your previous answer was rejected for this reason: {error}. "
                "Return only corrected JSON matching the schema."
            ),
        },
    ]
    raw_repair = _call_raw(client, system_prompt, repair_messages)
    parsed, error2 = _try_parse(raw_repair)
    if parsed is not None:
        return parsed

    # Give up cleanly
    raise ModelOutputError(raw_output=raw_repair, error=error2, prompt_version="triage-v1")


def _try_parse(raw: str):
    json_str = _extract_json(raw)
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"

    try:
        return TriageOutput.model_validate(data), None
    except ValidationError as e:
        return None, f"schema validation failed: {e}"


class ModelOutputError(Exception):
    def __init__(self, raw_output, error, prompt_version):
        self.raw_output = raw_output
        self.error = error
        self.prompt_version = prompt_version
        super().__init__(error)