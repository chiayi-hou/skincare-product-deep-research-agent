import json

HEADERS = {"User-Agent": "SkincareResearchAgent/0.1 (contact: ch4123@columbia.edu)"}


def as_text(result: dict) -> str:
    """A tool result as JSON text, which is what the model reads best."""
    return json.dumps(result, ensure_ascii=False, default=str)
