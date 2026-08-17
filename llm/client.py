import os
from pathlib import Path
from openai import OpenAI

PROMPT_PATH = Path(__file__).parent / "prompts" / "triage-v1.md"


def get_client():
    return OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
    )


def load_prompt():
    return PROMPT_PATH.read_text()


def call_triage_model(text: str) -> str:
    client = get_client()
    system_prompt = load_prompt()

    res = client.chat.completions.create(
        model=os.environ["LLM_MODEL"],
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
    )
    return res.choices[0].message.content