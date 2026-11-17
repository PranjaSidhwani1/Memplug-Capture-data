"""Decide whether a relationship is new, already active, or replaces an older edge."""

from __future__ import annotations


def plan_relationship(active_types: set[str], new_type: str, action: str) -> dict:
    """Avoid a second active edge of the same type.

    Supersede closes other active types between the same directed pair, then
    the caller inserts the new edge. The closed rows keep valid_until.
    """
    if not new_type:
        return {"create": False, "close_types": []}
    if new_type in active_types:
        return {"create": False, "close_types": []}
    if action == "supersede" and len(active_types) == 1:
        return {"create": True, "close_types": sorted(active_types)}
    return {"create": True, "close_types": []}


def bind_relationships(candidates: list[dict], resolutions: list[dict]) -> list[dict]:
    by_name: dict[str, str] = {}
    ambiguous: set[str] = set()
    for item in resolutions:
        name = str(item.get("name_norm") or "")
        entity_id = str(item.get("entity_id") or "")
        if not name or not entity_id:
            continue
        previous = by_name.get(name)
        if previous and previous != entity_id:
            ambiguous.add(name)
        else:
            by_name[name] = entity_id
    bound = []
    for candidate in candidates:
        source_name = " ".join(str(candidate.get("source") or "").casefold().split())
        target_name = " ".join(str(candidate.get("target") or "").casefold().split())
        if source_name in ambiguous or target_name in ambiguous:
            continue
        source_id = by_name.get(source_name, "")
        target_id = by_name.get(target_name, "")
        relationship = str(candidate.get("relationship") or "")
        if not source_id or not target_id or source_id == target_id or not relationship:
            continue
        action = candidate.get("action") if candidate.get("action") in {"create", "supersede"} else "create"
        bound.append(
            {
                "source_entity_id": source_id,
                "target_entity_id": target_id,
                "relationship_type": relationship,
                "action": action,
                "source_message_ids": list(candidate.get("source_message_ids") or []),
            }
        )
    return bound
