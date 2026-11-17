"""Resolve extracted names to one entity id per workspace."""

from __future__ import annotations

import uuid

from psycopg.types.json import Jsonb

SEMANTIC_FLAG = 0.86
_VARIANT_MIN = 6
_VARIANT_EXTRA = 4


def normalize_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.casefold().split())


def name_variant_match(left: str, right: str) -> bool:
    """True when two names are the same string with a short suffix, such as Postgres and PostgreSQL."""
    a = normalize_name(left)
    b = normalize_name(right)
    if not a or not b or a == b:
        return False
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < _VARIANT_MIN:
        return False
    if len(long) - len(short) > _VARIANT_EXTRA:
        return False
    if not long.startswith(short):
        return False
    return long[len(short) :].isalpha()


def resolution_action(
    *,
    exact_id: str = "",
    alias_id: str = "",
    variant_id: str = "",
    other_type_ids: list[str] | None = None,
    semantic: list[tuple[str, float]] | None = None,
) -> dict:
    """Pick REUSE or CREATE.

    Semantic similarity never reuses an entity by itself. A close vector match
    is recorded as ambiguous and a new entity is created.
    """
    ambiguous: list[str] = []
    for raw in other_type_ids or []:
        text = str(raw or "")
        if text and text not in ambiguous:
            ambiguous.append(text)
    taken = {exact_id, alias_id, variant_id, ""}
    for entity_id, score in semantic or []:
        if entity_id and entity_id not in taken and float(score) >= SEMANTIC_FLAG and entity_id not in ambiguous:
            ambiguous.append(entity_id)
    match_id = exact_id or alias_id or variant_id
    if match_id:
        return {"action": "REUSE", "match_id": match_id, "ambiguous_with": [item for item in ambiguous if item != match_id]}
    return {"action": "CREATE", "match_id": "", "ambiguous_with": ambiguous}


def resolve_entities(conn, *, user_id: str, workspace_id: str, owner_type: str, owner_id: str, candidates: list[dict], vectors: dict[tuple[str, str], list[float]]) -> list[dict]:
    """Create or reuse entities inside the caller's transaction."""
    resolved = []
    local: dict[tuple[str, str], str] = {}
    for candidate in candidates:
        name = str(candidate.get("name") or "").strip()
        name_norm = normalize_name(name)
        entity_type = str(candidate.get("entity_type") or "concept")
        if not name_norm:
            continue
        key = (entity_type, name_norm)
        if key in local:
            resolved.append(_row(name, name_norm, entity_type, "REUSE", local[key], []))
            continue
        exact_id = _exact(conn, owner_type, owner_id, entity_type, name_norm)
        alias_id = "" if exact_id else _alias(conn, owner_type, owner_id, entity_type, name_norm)
        variant_id = "" if exact_id or alias_id else _variant(conn, owner_type, owner_id, entity_type, name_norm)
        others = _other_types(conn, owner_type, owner_id, entity_type, name_norm)
        vector = vectors.get(key)
        semantic = _semantic(conn, owner_type, owner_id, entity_type, vector) if vector is not None else []
        decision = resolution_action(
            exact_id=exact_id,
            alias_id=alias_id,
            variant_id=variant_id,
            other_type_ids=others,
            semantic=semantic,
        )
        if decision["action"] == "REUSE":
            entity_id = decision["match_id"]
            _fill_description(conn, entity_id, str(candidate.get("description") or ""))
        else:
            entity_id = _create(
                conn,
                user_id=user_id,
                workspace_id=workspace_id,
                owner_type=owner_type,
                owner_id=owner_id,
                name=name,
                name_norm=name_norm,
                entity_type=entity_type,
                description=str(candidate.get("description") or ""),
                ambiguous=decision["ambiguous_with"],
            )
            decision = {**decision, "action": "CREATE" if entity_id else "REUSE"}
            if not entity_id:
                entity_id = _exact(conn, owner_type, owner_id, entity_type, name_norm)
                decision = {**decision, "action": "REUSE", "match_id": entity_id}
        if not entity_id:
            continue
        _alias_insert(conn, entity_id, name, name_norm)
        if vector is not None:
            conn.execute(
                """
                INSERT INTO entity_vectors (entity_id, embedding)
                VALUES (%s, %s)
                ON CONFLICT (entity_id) DO NOTHING
                """,
                (entity_id, vector),
            )
        local[key] = str(entity_id)
        resolved.append(_row(name, name_norm, entity_type, decision["action"], str(entity_id), decision["ambiguous_with"]))
    return resolved


def _row(name: str, name_norm: str, entity_type: str, action: str, entity_id: str, ambiguous: list[str]) -> dict:
    return {
        "input_name": name,
        "name_norm": name_norm,
        "entity_type": entity_type,
        "action": action,
        "entity_id": entity_id,
        "ambiguous_with": ambiguous,
    }


def _exact(conn, owner_type: str, owner_id: str, entity_type: str, name_norm: str) -> str:
    row = conn.execute(
        """
        SELECT id::text
        FROM entities
        WHERE owner_type = %s AND owner_id = %s AND entity_type = %s AND name_norm = %s
        """,
        (owner_type, owner_id, entity_type, name_norm),
    ).fetchone()
    return row[0] if row else ""


def _alias(conn, owner_type: str, owner_id: str, entity_type: str, name_norm: str) -> str:
    row = conn.execute(
        """
        SELECT e.id::text
        FROM entity_aliases a
        JOIN entities e ON e.id = a.entity_id
        WHERE e.owner_type = %s AND e.owner_id = %s AND e.entity_type = %s AND a.alias_norm = %s
        LIMIT 1
        """,
        (owner_type, owner_id, entity_type, name_norm),
    ).fetchone()
    return row[0] if row else ""


def _variant(conn, owner_type: str, owner_id: str, entity_type: str, name_norm: str) -> str:
    rows = conn.execute(
        """
        SELECT id::text, name_norm
        FROM entities
        WHERE owner_type = %s AND owner_id = %s AND entity_type = %s
          AND char_length(name_norm) >= %s
          AND (
            name_norm LIKE %s ESCAPE '\\'
            OR left(%s, char_length(name_norm)) = name_norm
          )
        LIMIT 10
        """,
        (owner_type, owner_id, entity_type, _VARIANT_MIN, _like_prefix(name_norm), name_norm),
    ).fetchall()
    for entity_id, existing in rows:
        if name_variant_match(name_norm, existing):
            return entity_id
    return ""


def _other_types(conn, owner_type: str, owner_id: str, entity_type: str, name_norm: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT id::text
        FROM entities
        WHERE owner_type = %s AND owner_id = %s AND name_norm = %s AND entity_type <> %s
        LIMIT 5
        """,
        (owner_type, owner_id, name_norm, entity_type),
    ).fetchall()
    return [row[0] for row in rows]


def _semantic(conn, owner_type: str, owner_id: str, entity_type: str, vector: list[float]) -> list[tuple[str, float]]:
    rows = conn.execute(
        """
        SELECT e.id::text, 1 - (v.embedding <=> %s::vector) AS similarity
        FROM entity_vectors v
        JOIN entities e ON e.id = v.entity_id
        WHERE e.owner_type = %s AND e.owner_id = %s AND e.entity_type = %s
        ORDER BY v.embedding <=> %s::vector
        LIMIT 3
        """,
        (vector, owner_type, owner_id, entity_type, vector),
    ).fetchall()
    return [(row[0], float(row[1])) for row in rows]


def _create(conn, *, user_id: str, workspace_id: str, owner_type: str, owner_id: str, name: str, name_norm: str, entity_type: str, description: str, ambiguous: list[str]) -> str:
    metadata = {"resolution": "ambiguous", "ambiguous_with": ambiguous} if ambiguous else {"resolution": "created"}
    row = conn.execute(
        """
        INSERT INTO entities (
            id, user_id, workspace_id, owner_type, owner_id, name, name_norm,
            entity_type, description, canonical_name, metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (owner_type, owner_id, entity_type, name_norm) DO NOTHING
        RETURNING id::text
        """,
        (
            uuid.uuid4(),
            user_id,
            workspace_id,
            owner_type,
            owner_id,
            name,
            name_norm,
            entity_type,
            description,
            name,
            Jsonb(metadata),
        ),
    ).fetchone()
    return row[0] if row else ""


def _fill_description(conn, entity_id: str, description: str) -> None:
    if not description:
        return
    conn.execute(
        """
        UPDATE entities
        SET description = %s, updated_at = now()
        WHERE id = %s AND description = ''
        """,
        (description, entity_id),
    )


def _alias_insert(conn, entity_id: str, alias: str, alias_norm: str) -> None:
    conn.execute(
        """
        INSERT INTO entity_aliases (id, entity_id, alias, alias_norm)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (entity_id, alias_norm) DO NOTHING
        """,
        (uuid.uuid4(), entity_id, alias, alias_norm),
    )


def _like_prefix(name: str) -> str:
    escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"
