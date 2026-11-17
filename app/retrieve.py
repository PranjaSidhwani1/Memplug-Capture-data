"""Rank vector rows, lexical rows, and graph rows, and read both retrieval paths."""

from __future__ import annotations

import re

_RRF_K = 60
_GRAPH_POOL = 30
_HOPS = 2
_MAX_ENTITIES = 24
_ENTITY_SIMILARITY = 0.58


def fuse_rows(groups: list, limit: int) -> list[str]:
    """Reciprocal rank fusion. A memory that appears in more than one list ranks higher."""
    scores: dict[str, float] = {}
    content: dict[str, str] = {}
    order: list[str] = []
    for rows in groups:
        for rank, row in enumerate(rows or [], start=1):
            memory_id = str(row[0])
            scores[memory_id] = scores.get(memory_id, 0.0) + (1.0 / (_RRF_K + rank))
            text = row[1] if len(row) > 1 and isinstance(row[1], str) else ""
            content[memory_id] = text
            if memory_id not in order:
                order.append(memory_id)
    ranked = sorted(order, key=lambda memory_id: (-scores[memory_id], order.index(memory_id)))
    texts: list[str] = []
    for memory_id in ranked:
        piece = " ".join(content[memory_id].split())
        if piece:
            texts.append(piece)
        if len(texts) >= limit:
            break
    return texts


def similar_memories(conn, *, owner_type: str, owner_id: str, project: str, scope: str, vector: list[float], limit: int = 5) -> list[dict]:
    project_sql = ""
    params: list[object] = [owner_type, owner_id]
    if scope == "project" and project:
        project_sql = " AND m.project = %s"
        params.append(project)
    rows = conn.execute(
        f"""
        SELECT m.id::text, m.content, 1 - (v.embedding <=> %s::vector) AS similarity
        FROM memories m
        JOIN memory_vectors v ON v.memory_id = m.id
        WHERE m.owner_type = %s
          AND m.owner_id = %s
          AND m.status = 'active'
          {project_sql}
        ORDER BY v.embedding <=> %s::vector
        LIMIT %s
        """,
        (vector, *params, vector, limit),
    ).fetchall()
    return [
        {"memory_id": row[0], "content": row[1] or "", "similarity": round(float(row[2]), 4)}
        for row in rows
    ]


def graph_hits(
    conn,
    *,
    owner_type: str,
    owner_id: str,
    domains: list[str],
    query: str,
    vector: list[float] | None,
    limit: int = _GRAPH_POOL,
    sub_domain: str = "",
    memory_type: str = "",
) -> list[tuple[str, str]]:
    """Memories reached by entity name and a short walk across active relationships."""
    if not domains:
        return []
    entity_ids = _seed_entities(conn, owner_type, owner_id, query, vector)
    if not entity_ids:
        return []
    entity_ids = _walk(conn, entity_ids)
    extra = ""
    params: list[object] = [entity_ids, owner_type, owner_id, domains]
    if sub_domain:
        extra += " AND lower(regexp_replace(coalesce(m.sub_domain, ''), '\\s+', ' ', 'g')) = %s"
        params.append(sub_domain)
    if memory_type:
        extra += " AND m.memory_type = %s"
        params.append(memory_type)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT m.id::text, m.content
        FROM memories m
        JOIN memory_entities me ON me.memory_id = m.id
        WHERE me.entity_id = ANY(%s::uuid[])
          AND m.owner_type = %s
          AND m.owner_id = %s
          AND m.domain = ANY(%s)
          AND m.status = 'active'
          {extra}
        GROUP BY m.id, m.content, m.updated_at
        ORDER BY count(*) DESC, m.updated_at DESC
        LIMIT %s
        """,
        params,
    ).fetchall()
    return [(row[0], row[1] or "") for row in rows]


def _seed_entities(conn, owner_type: str, owner_id: str, query: str, vector: list[float] | None) -> list[str]:
    tokens = [token for token in re.findall(r"[a-z0-9]+", query.casefold()) if len(token) >= 3]
    found: list[str] = []
    found.extend(_phrase_matches(conn, owner_type, owner_id, query))
    if tokens:
        rows = conn.execute(
            """
            SELECT e.id::text
            FROM entities e
            LEFT JOIN entity_aliases a ON a.entity_id = e.id
            WHERE e.owner_type = %s
              AND e.owner_id = %s
              AND (e.name_norm = ANY(%s) OR a.alias_norm = ANY(%s))
            LIMIT %s
            """,
            (owner_type, owner_id, tokens, tokens, _MAX_ENTITIES),
        ).fetchall()
        found.extend(row[0] for row in rows)
    phrase = " ".join(query.casefold().split())
    if phrase:
        rows = conn.execute(
            """
            SELECT e.id::text
            FROM entities e
            LEFT JOIN entity_aliases a ON a.entity_id = e.id
            WHERE e.owner_type = %s
              AND e.owner_id = %s
              AND (e.name_norm = %s OR a.alias_norm = %s)
            LIMIT 8
            """,
            (owner_type, owner_id, phrase, phrase),
        ).fetchall()
        found.extend(row[0] for row in rows)
    if vector is not None:
        rows = conn.execute(
            """
            SELECT e.id::text, 1 - (v.embedding <=> %s::vector) AS similarity
            FROM entity_vectors v
            JOIN entities e ON e.id = v.entity_id
            WHERE e.owner_type = %s AND e.owner_id = %s
            ORDER BY v.embedding <=> %s::vector
            LIMIT 8
            """,
            (vector, owner_type, owner_id, vector),
        ).fetchall()
        for entity_id, similarity in rows:
            if float(similarity) >= _ENTITY_SIMILARITY:
                found.append(entity_id)
    unique = []
    for entity_id in found:
        if entity_id not in unique:
            unique.append(entity_id)
        if len(unique) >= _MAX_ENTITIES:
            break
    return unique


def _phrase_matches(conn, owner_type: str, owner_id: str, query: str) -> list[str]:
    phrase = " ".join(query.casefold().split())
    if len(phrase) < 3:
        return []
    rows = conn.execute(
        """
        SELECT e.id::text, e.name_norm
        FROM entities e
        WHERE e.owner_type = %s AND e.owner_id = %s
          AND char_length(e.name_norm) >= 3
          AND position(e.name_norm in %s) > 0
        UNION
        SELECT e.id::text, a.alias_norm
        FROM entity_aliases a
        JOIN entities e ON e.id = a.entity_id
        WHERE e.owner_type = %s AND e.owner_id = %s
          AND char_length(a.alias_norm) >= 3
          AND position(a.alias_norm in %s) > 0
        LIMIT 50
        """,
        (owner_type, owner_id, phrase, owner_type, owner_id, phrase),
    ).fetchall()
    return [entity_id for entity_id, name in rows if name and _has_name(phrase, name)]


def _has_name(phrase: str, name: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", phrase) is not None


def _walk(conn, seeds: list[str]) -> list[str]:
    seen = list(seeds)
    frontier = list(seeds)
    for _hop in range(_HOPS):
        if not frontier or len(seen) >= _MAX_ENTITIES:
            break
        rows = conn.execute(
            """
            SELECT source_entity_id::text, target_entity_id::text
            FROM entity_relationships
            WHERE valid_until IS NULL
              AND (source_entity_id = ANY(%s::uuid[]) OR target_entity_id = ANY(%s::uuid[]))
            LIMIT 80
            """,
            (frontier, frontier),
        ).fetchall()
        frontier = []
        for source_id, target_id in rows:
            for entity_id in (source_id, target_id):
                if entity_id not in seen and len(seen) < _MAX_ENTITIES:
                    seen.append(entity_id)
                    frontier.append(entity_id)
    return seen
