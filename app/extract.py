"""Turn one conversation window into entity memories with a Meta model call."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.config import meta_api_key, meta_model
from app.domains import catalogue_text, resolve_domain

_API_URL = "https://api.meta.ai/v1/chat/completions"
_TYPES = {"fact", "preference", "decision", "plan"}
_MIN_CONFIDENCE = 0.55


def extract_memories(messages: list[dict]) -> list[dict]:
    raw = _complete(_prompt(messages))
    return accepted_memories(raw)


def accepted_memories(payload: dict) -> list[dict]:
    rows = payload.get("memories") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    accepted: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        content = _clip(row.get("content"), 2000)
        entity = _clip(row.get("entity"), 160)
        if not content or not entity:
            continue
        try:
            confidence = float(row.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        if confidence < _MIN_CONFIDENCE:
            continue
        entities = _entities(row.get("entities"), entity)
        memory_type = str(row.get("memory_type") or "").strip().lower()
        accepted.append(
            {
                "entity": entity,
                "entities": entities,
                "content": content,
                "domain": resolve_domain(str(row.get("domain") or "")),
                "memory_type": memory_type if memory_type in _TYPES else "fact",
                "confidence": round(min(confidence, 1.0), 3),
            }
        )
    return accepted


def _prompt(messages: list[dict]) -> str:
    lines = []
    for message in messages:
        role = message.get("role") or "user"
        text = str(message.get("content") or "").strip()
        if text:
            lines.append(f"[{role}]\n{text}")
    transcript = "\n\n".join(lines)
    return (
        "Extract durable memories from this conversation window.\n"
        "A memory is one sentence about one entity: a person, project, tool, place, or preference.\n"
        "Use a fact the user stated, or a decision they accepted. "
        "Do not store the assistant's guesses, questions, or hypotheticals as user facts.\n"
        "Assign exactly one domain from this catalogue:\n"
        f"{catalogue_text()}\n\n"
        "Return JSON only, in this shape:\n"
        '{"memories":[{"entity":"","entities":[""],"content":"","domain":"",'
        '"memory_type":"fact|preference|decision|plan","confidence":0.0}]}\n'
        "confidence is 0 to 1. If nothing should be kept, return {\"memories\":[]}.\n\n"
        f"Conversation:\n{transcript}"
    )


def _complete(prompt: str) -> dict:
    key = meta_api_key()
    model = meta_model()
    if not key or not model:
        raise RuntimeError("META_API_KEY and META_MODEL must be set")
    body = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }
    try:
        payload = _post(key, body)
    except RuntimeError as exc:
        if "returned 400" not in str(exc):
            raise
        body.pop("response_format")
        payload = _post(key, body)
    content = payload["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Meta model returned an empty response")
    return _json_object(content)


def _post(key: str, body: dict) -> dict:
    request = urllib.request.Request(
        _API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Meta model API returned {exc.code}: {detail}") from exc


def _json_object(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("model output was not a JSON object")
    return parsed


def _entities(value: object, entity: str) -> list[str]:
    names = [entity]
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                names.append(item.strip()[:160])
    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
        if len(unique) == 8:
            break
    return unique


def _clip(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]
