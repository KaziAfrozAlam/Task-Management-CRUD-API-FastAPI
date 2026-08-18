import os
import re
import json
import time
import random
import logging
from pathlib import Path
from openai import OpenAI, APITimeoutError, APIStatusError
from pydantic import ValidationError
from llm.schema import TriageOutput

PROMPT_PATH = Path(__file__).parent / "prompts" / "triage-v1.md"
TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 2  # our own retry logic; SDK retries disabled below

logger = logging.getLogger("llm.cost")


def get_client():
    return OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        timeout=TIMEOUT_SECONDS,
        max_retries=0,  # we handle retries ourselves, explicitly
    )


def load_prompt():
    return PROMPT_PATH.read_text()


def _extract_json(text: str) -> str:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


def _call_raw(client, system_prompt: str, messages_extra: list, prompt_version: str) -> str:
    """One HTTP call, with retry-on-the-right-errors and cost logging."""
    messages = [{"role": "system", "content": system_prompt}] + messages_extra
    attempt = 0
    last_exc = None

    while attempt <= MAX_RETRIES:
        start = time.monotonic()
        try:
            res = client.chat.completions.create(
                model=os.environ["LLM_MODEL"],
                temperature=0.2,
                messages=messages,
            )
            duration_ms = int((time.monotonic() - start) * 1000)

            usage = getattr(res, "usage", None)
            logger.info(json.dumps({
                "prompt_version": prompt_version,
                "model": os.environ["LLM_MODEL"],
                "input_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
                "output_tokens": getattr(usage, "completion_tokens", None) if usage else None,
                "duration_ms": duration_ms,
                "attempt": attempt,
            }))

            return res.choices[0].message.content

        except APITimeoutError as e:
            last_exc = e
        except APIStatusError as e:
            status = e.status_code
            if status in (401, 403) or status == 400:
                raise  # never retry these — bad key/bad request stays bad
            if status == 429 or status >= 500:
                last_exc = e
            else:
                raise

        # backoff with jitter before next attempt
        attempt += 1
        if attempt <= MAX_RETRIES:
            wait = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            time.sleep(wait)

    raise last_exc


def call_triage_model(text: str) -> TriageOutput:
    if os.environ.get("LLM_ENABLED", "true").lower() == "false":
        raise ModelDisabledError()

    client = get_client()
    system_prompt = load_prompt()
    prompt_version = "triage-v1"

    raw = _call_raw(client, system_prompt, [{"role": "user", "content": text}], prompt_version)

    parsed, error = _try_parse(raw)
    if parsed is not None:
        return parsed

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
    raw_repair = _call_raw(client, system_prompt, repair_messages, prompt_version)
    parsed, error2 = _try_parse(raw_repair)
    if parsed is not None:
        return parsed

    raise ModelOutputError(raw_output=raw_repair, error=error2, prompt_version=prompt_version)


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


class ModelDisabledError(Exception):
    pass
    