"""Parse extraction and decision JSON into the shapes the pipeline stores."""

from __future__ import annotations

import uuid

from app.decide import clip_text
from app.domains import resolve_domain

_MEMORY_TYPES = {"fact", "preference", "decision", "plan"}
_SCOPES = {"user", "project"}
_ENTITY_TYPES = {"person", "project", "company", "technology", "product", "location", "concept"}
_ENTITY_ALIASES = {
    "tool": "technology",
    "tech": "technology",
    "organization": "company",
    "org": "company",
    "place": "location",
    "people": "person",
}
_MAX_CANDIDATES = 12
_MAX_ENTITIES = 24
_MAX_RELATIONSHIPS = 24
_MIN_CONFIDENCE = 0.55


def parse_extraction(payload: dict, allowed_message_ids: set[str]) -> dict:
    if not isinstance(payload, dict):
        return {"memory_candidates": [], "entity_candidates": [], "relationship_candidates": []}
    memories = _memories(payload, allowed_message_ids)
    entities = _entities(payload)
    relationships = _relationships(payload, allowed_message_ids)
    return {
        "memory_candidates": memories,
        "entity_candidates": entities,
        "relationship_candidates": relationships,
    }


def parse_decisions(payload: dict) -> list[dict]:
    rows = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    parsed = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate_id = clip_text(str(row.get("candidate_id") or ""), 40)
        if not candidate_id:
            continue
        operation = str(row.get("operation") or "").strip().upper()
        targets = []
        for raw in row.get("target_memory_ids") or []:
            text = str(raw or "").strip()
            if text and text not in targets:
                targets.append(text)
        parsed.append(
            {
                "candidate_id": candidate_id,
                "operation": operation,
                "target_memory_ids": targets[:8],
                "final_content": clip_text(row.get("final_content"), 2000),
                "confidence": row.get("confidence", 0),
            }
        )
    return parsed


def canonical_entity_type(value: object) -> str:
    key = str(value or "").strip().casefold().replace("-", " ")
    key = " ".join(key.split())
    key = _ENTITY_ALIASES.get(key, key)
    return key if key in _ENTITY_TYPES else "concept"


def canonical_relationship(value: object) -> str:
    raw = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch == "_")
    parts = [part for part in cleaned.split("_") if part]
    cleaned = "_".join(parts)
    if not cleaned or cleaned[0].isdigit():
        return ""
    return cleaned[:64]


def _memories(payload: dict, allowed_message_ids: set[str]) -> list[dict]:
    rows = payload.get("memory_candidates")
    if not isinstance(rows, list):
        rows = payload.get("memories") if isinstance(payload.get("memories"), list) else []
    accepted = []
    seen = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or len(accepted) >= _MAX_CANDIDATES:
            continue
        content = clip_text(row.get("content"), 2000)
        if not content:
            continue
        try:
            confidence = float(row.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        if confidence < _MIN_CONFIDENCE:
            continue
        memory_type = str(row.get("memory_type") or "").strip().lower()
        scope = str(row.get("scope") or "user").strip().lower()
        candidate_id = clip_text(str(row.get("candidate_id") or ""), 40) or f"cand_{index:03d}"
        if candidate_id in seen:
            candidate_id = f"cand_{index:03d}"
        seen.add(candidate_id)
        accepted.append(
            {
                "candidate_id": candidate_id,
                "content": content,
                "memory_type": memory_type if memory_type in _MEMORY_TYPES else "fact",
                "domain": resolve_domain(str(row.get("domain") or "")),
                "scope": scope if scope in _SCOPES else "user",
                "confidence": max(0.0, min(1.0, confidence)),
                "source_message_ids": _message_ids(row.get("source_message_ids"), allowed_message_ids),
            }
        )
    return accepted


def _entities(payload: dict) -> list[dict]:
    rows = payload.get("entity_candidates")
    if not isinstance(rows, list):
        return []
    accepted = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or len(accepted) >= _MAX_ENTITIES:
            continue
        name = clip_text(row.get("name"), 160)
        if not name:
            continue
        entity_type = canonical_entity_type(row.get("type") or row.get("entity_type"))
        key = (entity_type, " ".join(name.casefold().split()))
        if key in seen:
            continue
        seen.add(key)
        accepted.append(
            {
                "name": name,
                "entity_type": entity_type,
                "description": clip_text(row.get("description"), 500),
            }
        )
    return accepted


def _relationships(payload: dict, allowed_message_ids: set[str]) -> list[dict]:
    rows = payload.get("relationship_candidates")
    if not isinstance(rows, list):
        return []
    accepted = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or len(accepted) >= _MAX_RELATIONSHIPS:
            continue
        source = clip_text(row.get("source"), 160)
        target = clip_text(row.get("target"), 160)
        relationship = canonical_relationship(row.get("relationship") or row.get("relationship_type"))
        if not source or not target or not relationship:
            continue
        if " ".join(source.casefold().split()) == " ".join(target.casefold().split()):
            continue
        action = str(row.get("action") or "create").strip().lower()
        if action not in {"create", "supersede"}:
            action = "create"
        key = (source.casefold(), relationship, target.casefold(), action)
        if key in seen:
            continue
        seen.add(key)
        accepted.append(
            {
                "source": source,
                "relationship": relationship,
                "target": target,
                "action": action,
                "source_message_ids": _message_ids(row.get("source_message_ids"), allowed_message_ids),
            }
        )
    return accepted


def _message_ids(value: object, allowed: set[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = []
    for raw in value:
        try:
            parsed = str(uuid.UUID(str(raw)))
        except (ValueError, TypeError, AttributeError):
            continue
        if parsed in allowed and parsed not in cleaned:
            cleaned.append(parsed)
        if len(cleaned) >= 20:
            break
    return cleaned
