"""Apply validated memory operations and graph edges in one transaction."""

from __future__ import annotations

import re
import uuid

from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from app.decide import normalize_text
from app.relations import plan_relationship


def mentions(content: str, name_norm: str) -> bool:
    if len(name_norm) < 3:
        return False
    hay = normalize_text(content)
    return re.search(rf"(?<![a-z0-9]){re.escape(name_norm)}(?![a-z0-9])", hay) is not None


def apply_batch(
    conn,
    *,
    job_id: str | None,
    user_id: str,
    owner_type: str,
    owner_id: str,
    source: str,
    session_id: str,
    project: str,
    decisions: list[dict],
    resolutions: list[dict],
    relationships: list[dict],
    memory_vectors: dict[str, list[float]],
    batch_message_ids: list[str],
) -> list[dict]:
    written: list[dict] = []
    for decision in decisions:
        _store_candidate(conn, job_id, user_id, owner_type, owner_id, decision)
        if decision["operation"] == "NOOP":
            continue
        memory_id = _apply_memory(
            conn,
            user_id=user_id,
            owner_type=owner_type,
            owner_id=owner_id,
            source=source,
            session_id=session_id,
            project=project,
            decision=decision,
            vector=memory_vectors.get(normalize_text(decision["final_content"])),
        )
        if not memory_id:
            continue
        evidence_ids = decision.get("source_message_ids") or batch_message_ids
        _memory_evidence(conn, memory_id, evidence_ids, user_id)
        _link_entities(conn, memory_id, decision["final_content"], resolutions)
        written.append({"id": memory_id, "content": decision["final_content"]})
    _apply_relationships(conn, relationships, resolutions, written, batch_message_ids, user_id)
    return written


def _apply_memory(conn, *, user_id: str, owner_type: str, owner_id: str, source: str, session_id: str, project: str, decision: dict, vector: list[float] | None) -> str:
    content = decision["final_content"]
    content_norm = normalize_text(content)
    if not content_norm:
        return ""
    project = project if decision.get("scope") == "project" else ""
    existing = _memory_by_norm(conn, owner_type, owner_id, content_norm)
    targets = [item for item in decision.get("target_memory_ids") or [] if item]
    if existing is not None:
        memory_id = _prefer_active(conn, existing)
        _supersede(conn, targets, memory_id, owner_type, owner_id)
        if vector is not None and memory_id == str(existing[0]):
            _upsert_vector(conn, memory_id, vector)
        return memory_id
    memory_id = str(uuid.uuid4())
    conn.execute("SAVEPOINT memory_insert")
    try:
        conn.execute(
            """
            INSERT INTO memories (
                id, user_id, owner_type, owner_id, domain, content, content_norm, memory_type,
                source, session_id, project, source_event_ids, confidence, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
            """,
            (
                memory_id,
                user_id,
                owner_type,
                owner_id,
                decision.get("domain") or "Uncategorised",
                content,
                content_norm,
                decision.get("memory_type") or "fact",
                source,
                session_id,
                project or "",
                Jsonb(list(decision.get("source_message_ids") or [])),
                decision.get("confidence"),
            ),
        )
        conn.execute("RELEASE SAVEPOINT memory_insert")
    except UniqueViolation:
        conn.execute("ROLLBACK TO SAVEPOINT memory_insert")
        conn.execute("RELEASE SAVEPOINT memory_insert")
        raced = _memory_by_norm(conn, owner_type, owner_id, content_norm)
        if raced is None:
            raise
        memory_id = _prefer_active(conn, raced)
        _supersede(conn, targets, memory_id, owner_type, owner_id)
        return memory_id
    if vector is not None:
        _upsert_vector(conn, memory_id, vector)
    _supersede(conn, targets, memory_id, owner_type, owner_id)
    return memory_id


def _memory_by_norm(conn, owner_type: str, owner_id: str, content_norm: str):
    return conn.execute(
        """
        SELECT id::text, status, superseded_by::text
        FROM memories
        WHERE owner_type = %s AND owner_id = %s AND content_norm = %s
        LIMIT 1
        """,
        (owner_type, owner_id, content_norm),
    ).fetchone()


def _prefer_active(conn, row) -> str:
    """Keep the current fact when this exact text was already superseded."""
    memory_id, status, superseded_by = row
    if status == "superseded" and superseded_by:
        active = conn.execute(
            "SELECT id::text FROM memories WHERE id = %s AND status = 'active'",
            (superseded_by,),
        ).fetchone()
        if active:
            return active[0]
    if status != "active":
        conn.execute(
            """
            UPDATE memories
            SET status = 'active', superseded_by = NULL, updated_at = now()
            WHERE id = %s
            """,
            (memory_id,),
        )
    return memory_id


def _supersede(conn, targets: list[str], keeper: str, owner_type: str, owner_id: str) -> None:
    doomed = [target for target in targets if target and target != keeper]
    if not doomed:
        return
    conn.execute(
        """
        UPDATE memories
        SET status = 'superseded', superseded_by = %s, updated_at = now()
        WHERE id = ANY(%s::uuid[])
          AND owner_type = %s
          AND owner_id = %s
          AND status = 'active'
          AND id <> %s
        """,
        (keeper, doomed, owner_type, owner_id, keeper),
    )


def _upsert_vector(conn, memory_id: str, vector: list[float]) -> None:
    conn.execute(
        """
        INSERT INTO memory_vectors (memory_id, embedding)
        VALUES (%s, %s)
        ON CONFLICT (memory_id) DO UPDATE SET embedding = EXCLUDED.embedding
        """,
        (memory_id, vector),
    )


def _memory_evidence(conn, memory_id: str, message_ids: list[str], user_id: str) -> None:
    if not message_ids:
        return
    rows = conn.execute(
        """
        SELECT id::text
        FROM messages
        WHERE id = ANY(%s::uuid[]) AND user_id = %s
        """,
        (list(message_ids), user_id),
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT INTO memory_evidence (id, memory_id, message_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (memory_id, message_id) DO NOTHING
            """,
            (uuid.uuid4(), memory_id, row[0]),
        )


def _link_entities(conn, memory_id: str, content: str, resolutions: list[dict]) -> None:
    for item in resolutions:
        name = str(item.get("name_norm") or "")
        entity_id = str(item.get("entity_id") or "")
        if not entity_id or not mentions(content, name):
            continue
        conn.execute(
            """
            INSERT INTO memory_entities (memory_id, entity_id, role)
            VALUES (%s, %s, 'mentioned')
            ON CONFLICT (memory_id, entity_id) DO NOTHING
            """,
            (memory_id, entity_id),
        )


def _apply_relationships(conn, relationships: list[dict], resolutions: list[dict], written: list[dict], batch_message_ids: list[str], user_id: str) -> None:
    names = {str(item.get("entity_id") or ""): str(item.get("name_norm") or "") for item in resolutions}
    for item in relationships:
        source_id = item["source_entity_id"]
        target_id = item["target_entity_id"]
        relationship_type = item["relationship_type"]
        active = _active_edges(conn, source_id, target_id)
        plan = plan_relationship(set(active), relationship_type, item.get("action") or "create")
        if plan["close_types"]:
            conn.execute(
                """
                UPDATE entity_relationships
                SET valid_until = now(), updated_at = now()
                WHERE source_entity_id = %s
                  AND target_entity_id = %s
                  AND valid_until IS NULL
                  AND relationship_type = ANY(%s)
                """,
                (source_id, target_id, plan["close_types"]),
            )
        if plan["create"]:
            relationship_id = _insert_relationship(conn, source_id, target_id, relationship_type, item.get("action") or "create")
        else:
            relationship_id = active.get(relationship_type, "")
        if not relationship_id:
            continue
        message_ids = item.get("source_message_ids") or batch_message_ids
        memory_id = _supporting_memory(written, names.get(source_id, ""), names.get(target_id, ""))
        _relationship_evidence(conn, relationship_id, message_ids, memory_id, user_id)


def _active_edges(conn, source_id: str, target_id: str) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT relationship_type, id::text
        FROM entity_relationships
        WHERE source_entity_id = %s AND target_entity_id = %s AND valid_until IS NULL
        """,
        (source_id, target_id),
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def _insert_relationship(conn, source_id: str, target_id: str, relationship_type: str, action: str) -> str:
    row = conn.execute(
        """
        INSERT INTO entity_relationships (
            id, source_entity_id, target_entity_id, relationship_type, properties, valid_from
        )
        VALUES (%s, %s, %s, %s, %s, now())
        ON CONFLICT (source_entity_id, target_entity_id, relationship_type) WHERE valid_until IS NULL
        DO NOTHING
        RETURNING id::text
        """,
        (uuid.uuid4(), source_id, target_id, relationship_type, Jsonb({"action": action})),
    ).fetchone()
    if row:
        return row[0]
    existing = _active_edges(conn, source_id, target_id)
    return existing.get(relationship_type, "")


def _supporting_memory(written: list[dict], source_name: str, target_name: str) -> str | None:
    if not source_name or not target_name:
        return None
    for memory in written:
        content = memory.get("content") or ""
        if mentions(content, source_name) and mentions(content, target_name):
            return memory["id"]
    return None


def _relationship_evidence(conn, relationship_id: str, message_ids: list[str], memory_id: str | None, user_id: str) -> None:
    if not message_ids:
        return
    rows = conn.execute(
        """
        SELECT id::text
        FROM messages
        WHERE id = ANY(%s::uuid[]) AND user_id = %s
        """,
        (list(message_ids), user_id),
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT INTO relationship_evidence (id, relationship_id, message_id, memory_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (relationship_id, message_id) DO NOTHING
            """,
            (uuid.uuid4(), relationship_id, row[0], memory_id),
        )


def _store_candidate(conn, job_id: str | None, user_id: str, owner_type: str, owner_id: str, decision: dict) -> None:
    conn.execute(
        """
        INSERT INTO memory_candidates (
            id, candidate_key, job_id, user_id, owner_type, owner_id, content, memory_type,
            domain, scope, confidence, operation, final_content, target_ids, source_message_ids, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'applied')
        """,
        (
            uuid.uuid4(),
            decision.get("candidate_id") or "",
            job_id,
            user_id,
            owner_type,
            owner_id,
            decision.get("candidate_content") or decision.get("final_content") or "",
            decision.get("memory_type") or "fact",
            decision.get("domain") or "Uncategorised",
            decision.get("scope") or "user",
            decision.get("confidence"),
            decision.get("operation") or "NOOP",
            decision.get("final_content") or "",
            Jsonb(list(decision.get("target_memory_ids") or [])),
            Jsonb(list(decision.get("source_message_ids") or [])),
        ),
    )
