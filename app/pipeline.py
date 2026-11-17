"""Run one captured batch through extraction, decision, resolution, and writers."""

from __future__ import annotations

import logging

from app.context import build_context
from app.decide import align_decisions, normalize_text
from app.entities import normalize_name, resolve_entities
from app.relations import bind_relationships
from app.retrieve import similar_memories
from app.writer import apply_batch

log = logging.getLogger("memplug.pipeline")


def process_batch(messages: list[dict], job_id: str | None = None, job_ids: list[str] | None = None) -> None:
    tokens = _claim_tokens(messages)
    if not messages:
        _mark_jobs_done(tokens)
        return
    anchor = messages[-1]
    user_id = str(anchor.get("user_id") or "")
    workspace_type = str(anchor.get("workspace_type") or "user")
    workspace_id = str(anchor.get("workspace_id") or user_id)
    if workspace_type == "team":
        from app.users import member_of_team

        if not member_of_team(user_id, workspace_id):
            log.info("skipped team batch user=%s workspace=%s", user_id, workspace_id)
            _mark_jobs_done(tokens)
            return
    owner_type = "team" if workspace_type == "team" else "user"
    owner_id = workspace_id or user_id
    project = str(anchor.get("project_id") or "")
    source = str(anchor.get("source") or "")
    session_id = str(anchor.get("session_id") or "")

    from app.extract import extract_candidates, propose_decisions
    from app.memories import _connect, _ensure_schema, embed_texts

    _store_message_embeddings(messages, embed_texts)
    query_vector = _vector(embed_texts, _batch_text(messages))
    with _connect() as conn:
        _ensure_schema(conn)
        context = build_context(conn, messages, query_vector)
    extracted = extract_candidates(context)
    candidates = extracted["memory_candidates"]
    retrieved = _retrieve_for_candidates(candidates, embed_texts, owner_type, owner_id, project)
    proposals = propose_decisions(candidates, retrieved, context) if candidates else []
    decisions = align_decisions(candidates, proposals, retrieved)
    entity_vectors = _entity_vectors(extracted["entity_candidates"], embed_texts)
    memory_vectors = _memory_vectors(decisions, embed_texts)

    with _connect() as conn:
        _ensure_schema(conn)
        if tokens and not _claim_held(conn, tokens):
            log.info("job claim was lost session=%s", session_id)
            return
        resolutions = resolve_entities(
            conn,
            user_id=user_id,
            workspace_id=workspace_id,
            owner_type=owner_type,
            owner_id=owner_id,
            candidates=extracted["entity_candidates"],
            vectors=entity_vectors,
        )
        relationships = bind_relationships(extracted["relationship_candidates"], resolutions)
        written = apply_batch(
            conn,
            job_id=job_id or (job_ids[0] if job_ids else None),
            user_id=user_id,
            owner_type=owner_type,
            owner_id=owner_id,
            source=source,
            session_id=session_id,
            project=project,
            decisions=decisions,
            resolutions=resolutions,
            relationships=relationships,
            memory_vectors=memory_vectors,
            batch_message_ids=[str(item["id"]) for item in messages if item.get("id")],
        )
        _mark_jobs_done(tokens, conn)
    log.info(
        "pipeline session=%s candidates=%s decisions=%s entities=%s relationships=%s written=%s",
        session_id,
        len(candidates),
        [item["operation"] for item in decisions],
        len(resolutions),
        len(relationships),
        len(written),
    )


def _retrieve_for_candidates(candidates: list[dict], embed_texts, owner_type: str, owner_id: str, project: str) -> dict[str, list[dict]]:
    if not candidates:
        return {}
    from app.memories import _connect, _ensure_schema

    vectors = embed_texts([item["content"] for item in candidates])
    found: dict[str, list[dict]] = {}
    with _connect() as conn:
        _ensure_schema(conn)
        for candidate, vector in zip(candidates, vectors, strict=True):
            found[candidate["candidate_id"]] = similar_memories(
                conn,
                owner_type=owner_type,
                owner_id=owner_id,
                project=project,
                scope=str(candidate.get("scope") or "user"),
                vector=vector,
            )
    return found


def _entity_vectors(candidates: list[dict], embed_texts) -> dict[tuple[str, str], list[float]]:
    if not candidates:
        return {}
    texts = [f"{item['name']} ({item['entity_type']})" for item in candidates]
    vectors = embed_texts(texts)
    mapped = {}
    for item, vector in zip(candidates, vectors, strict=True):
        mapped[(item["entity_type"], normalize_name(item["name"]))] = vector
    return mapped


def _memory_vectors(decisions: list[dict], embed_texts) -> dict[str, list[float]]:
    texts = []
    keys = []
    seen = set()
    for decision in decisions:
        if decision.get("operation") == "NOOP":
            continue
        content = decision.get("final_content") or ""
        key = normalize_text(content)
        if not key or key in seen:
            continue
        seen.add(key)
        texts.append(content)
        keys.append(key)
    if not texts:
        return {}
    vectors = embed_texts(texts)
    return dict(zip(keys, vectors, strict=True))


def _store_message_embeddings(messages: list[dict], embed_texts) -> None:
    pending = [item for item in messages if item.get("id") and str(item.get("content") or "").strip()]
    if not pending:
        return
    from app.memories import _connect, _ensure_schema

    ids = [item["id"] for item in pending]
    with _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT message_id::text FROM message_embeddings WHERE message_id = ANY(%s::uuid[])",
            (ids,),
        ).fetchall()
    have = {row[0] for row in rows}
    missing = [item for item in pending if item["id"] not in have]
    if not missing:
        return
    vectors = embed_texts([str(item.get("content") or "") for item in missing])
    with _connect() as conn:
        _ensure_schema(conn)
        for item, vector in zip(missing, vectors, strict=True):
            conn.execute(
                """
                INSERT INTO message_embeddings (message_id, embedding)
                VALUES (%s, %s)
                ON CONFLICT (message_id) DO NOTHING
                """,
                (item["id"], vector),
            )


def _batch_text(messages: list[dict]) -> str:
    parts = [str(item.get("content") or "").strip() for item in messages]
    return "\n".join(part for part in parts if part)[:4000]


def _vector(embed_texts, text: str):
    if not text.strip():
        return None
    return embed_texts([text])[0]


def _claim_tokens(messages: list[dict]) -> dict[str, str]:
    tokens = {}
    for item in messages:
        job_id = str(item.get("job_id") or "")
        token = str(item.get("claim_token") or "")
        if job_id and token:
            tokens[job_id] = token
    return tokens


def _claim_held(conn, tokens: dict[str, str]) -> bool:
    rows = conn.execute(
        """
        SELECT id::text, claim_token::text, status
        FROM processing_jobs
        WHERE id = ANY(%s::uuid[])
        FOR UPDATE
        """,
        (list(tokens),),
    ).fetchall()
    found = {row[0]: (row[1], row[2]) for row in rows}
    for job_id, token in tokens.items():
        current = found.get(job_id)
        if not current or current[0] != token or current[1] != "running":
            return False
    return True


def _mark_jobs_done(tokens: dict[str, str] | None, conn=None) -> None:
    if not tokens:
        return

    def apply(target) -> None:
        for job_id, token in tokens.items():
            target.execute(
                """
                UPDATE processing_jobs
                SET status = 'done', last_error = '', locked_at = NULL, updated_at = now()
                WHERE id = %s AND claim_token = %s AND status = 'running'
                """,
                (job_id, token),
            )

    if conn is not None:
        apply(conn)
        return
    from app.memories import _connect, _ensure_schema

    with _connect() as owned:
        _ensure_schema(owned)
        if not _claim_held(owned, tokens):
            return
        apply(owned)
