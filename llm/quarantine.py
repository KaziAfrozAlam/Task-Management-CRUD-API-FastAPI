import json
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "logs" / "quarantine.jsonl"


def log_quarantine(input_text: str, error: str, raw_output: str, prompt_version: str):
    LOG_PATH.parent.mkdir(exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input": input_text,
        "error": error,
        "raw_output": raw_output,
        "prompt_version": prompt_version,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")