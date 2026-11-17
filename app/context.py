"""Assemble the bounded context the extraction model is allowed to see."""

from __future__ import annotations

from datetime import datetime, timezone

from app.retrieve import similar_memories

_RECENT = 8
_SEMANTIC = 4
_MEMORIES = 8
_MAX_MESSAGES = 16


def build_context(conn, messages: list[dict], query_vector: list[float] | None) -> dict:
    """Current batch, a short session window, and a few related memories."""
    if not messages:
        return {"project": "", "workspace_id": "", "workspace_type": "user", "source": "", "messages": [], "memories": []}
    anchor = messages[-1]
    batch_ids = [str(item["id"]) for item in messages]
    earlier = _earlier_messages(conn, anchor, batch_ids, query_vector)
    combined = _dedupe(earlier + [_public_message(item) for item in messages])
    combined.sort(key=lambda item: item.get("created_at") or "")
    if len(combined) > _MAX_MESSAGES:
        combined = combined[-_MAX_MESSAGES:]
    memories = []
    if query_vector is not None:
        memories = similar_memories(
            conn,
            owner_type=_owner_type(anchor),
            owner_id=str(anchor.get("workspace_id") or anchor.get("user_id") or ""),
            project=str(anchor.get("project_id") or ""),
            scope="user",
            vector=query_vector,
            limit=_MEMORIES,
        )
    return {
        "project": str(anchor.get("project_id") or ""),
        "workspace_id": str(anchor.get("workspace_id") or ""),
        "workspace_type": _owner_type(anchor),
        "source": str(anchor.get("source") or ""),
        "messages": combined,
        "memories": memories,
    }


def _earlier_messages(conn, anchor: dict, batch_ids: list[str], query_vector: list[float] | None) -> list[dict]:
    params = (
        anchor.get("user_id"),
        anchor.get("workspace_id"),
        anchor.get("source"),
        anchor.get("session_id"),
        batch_ids,
    )
    rows = conn.execute(
        """
        SELECT id::text, role, content, tool_name, tool_input, tool_status, created_at
        FROM messages
        WHERE user_id = %s AND workspace_id = %s AND source = %s AND session_id = %s
          AND NOT (id = ANY(%s::uuid[]))
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (*params, _RECENT),
    ).fetchall()
    semantic = []
    if query_vector is not None:
        semantic = conn.execute(
            """
            SELECT m.id::text, m.role, m.content, m.tool_name, m.tool_input, m.tool_status, m.created_at
            FROM messages m
            JOIN message_embeddings e ON e.message_id = m.id
            WHERE m.user_id = %s AND m.workspace_id = %s AND m.source = %s AND m.session_id = %s
              AND NOT (m.id = ANY(%s::uuid[]))
            ORDER BY e.embedding <=> %s::vector
            LIMIT %s
            """,
            (*params, query_vector, _SEMANTIC),
        ).fetchall()
    return [_from_row(row) for row in (*rows, *semantic)]


def _from_row(row) -> dict:
    return {
        "id": row[0],
        "role": row[1],
        "content": row[2] or "",
        "tool_name": row[3] or "",
        "tool_input": row[4] or "",
        "tool_status": row[5] or "",
        "created_at": _iso(row[6]),
    }


def _public_message(item: dict) -> dict:
    return {
        "id": str(item.get("id") or ""),
        "role": str(item.get("role") or "user"),
        "content": str(item.get("content") or ""),
        "tool_name": str(item.get("tool_name") or ""),
        "tool_input": str(item.get("tool_input") or ""),
        "tool_status": str(item.get("tool_status") or ""),
        "created_at": _iso(item.get("created_at")),
    }


def _dedupe(messages: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for message in messages:
        message_id = message.get("id") or ""
        if not message_id or message_id in seen:
            continue
        seen.add(message_id)
        unique.append(message)
    return unique


def _owner_type(message: dict) -> str:
    kind = str(message.get("workspace_type") or "user")
    return kind if kind == "team" else "user"


def _iso(value) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return "" if value is None else str(value)
