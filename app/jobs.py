"""Postgres job queue. Claim with SKIP LOCKED, then process outside the lock."""

from __future__ import annotations

import logging
import threading
import time
import uuid

log = logging.getLogger("memplug.jobs")

_MAX_ATTEMPTS = 5
_STALE_MINUTES = 15
_BATCH = 20
_started = False


def start_worker() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="memory-jobs").start()


def run_once() -> bool:
    """Claim one session batch. Return False when the queue is empty."""
    from app.memories import _connect, _ensure_schema

    with _connect() as conn:
        _ensure_schema(conn)
        _reclaim(conn)
        claimed = _claim(conn)
    if not claimed:
        return False
    job_ids = [item["job_id"] for item in claimed]
    try:
        from app.pipeline import process_batch

        process_batch(claimed, job_ids=job_ids)
    except Exception as exc:
        log.exception("memory job failed")
        _settle(job_ids, error=str(exc))
        return True
    return True


def _loop() -> None:
    while True:
        try:
            worked = run_once()
        except Exception:
            log.exception("memory job worker failed")
            worked = False
        if not worked:
            time.sleep(1)


def _reclaim(conn) -> None:
    conn.execute(
        """
        UPDATE processing_jobs
        SET status = 'failed',
            last_error = 'worker stopped before the job finished',
            locked_at = NULL,
            updated_at = now()
        WHERE status = 'running'
          AND attempts >= %s
          AND locked_at < now() - make_interval(mins => %s)
        """,
        (_MAX_ATTEMPTS, _STALE_MINUTES),
    )
    conn.execute(
        """
        UPDATE processing_jobs
        SET status = 'pending',
            locked_at = NULL,
            claim_token = NULL,
            run_after = now(),
            updated_at = now()
        WHERE status = 'running'
          AND attempts < %s
          AND locked_at < now() - make_interval(mins => %s)
        """,
        (_MAX_ATTEMPTS, _STALE_MINUTES),
    )


def _claim(conn) -> list[dict]:
    token = uuid.uuid4()
    row = conn.execute(
        """
        WITH next_job AS (
            SELECT id
            FROM processing_jobs
            WHERE status = 'pending' AND run_after <= now()
            ORDER BY run_after, created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        UPDATE processing_jobs AS job
        SET status = 'running',
            attempts = job.attempts + 1,
            locked_at = now(),
            claim_token = %s,
            updated_at = now()
        FROM next_job
        WHERE job.id = next_job.id
        RETURNING job.id, job.message_id
        """,
        (token,),
    ).fetchone()
    if row is None:
        return []
    anchor = _load_messages(conn, [row[1]])
    if not anchor:
        conn.execute(
            """
            UPDATE processing_jobs
            SET status = 'failed', last_error = 'message is missing', locked_at = NULL, updated_at = now()
            WHERE id = %s
            """,
            (row[0],),
        )
        return []
    first = anchor[0]
    sibling_rows = conn.execute(
        """
        SELECT job.id, job.message_id
        FROM processing_jobs AS job
        JOIN messages AS message ON message.id = job.message_id
        WHERE job.status = 'pending'
          AND message.user_id = %s
          AND message.workspace_id = %s
          AND message.source = %s
          AND message.session_id = %s
        ORDER BY message.created_at
        LIMIT %s
        FOR UPDATE OF job SKIP LOCKED
        """,
        (first["user_id"], first["workspace_id"], first["source"], first["session_id"], _BATCH - 1),
    ).fetchall()
    tokens_by_message = {str(row[1]): str(token)}
    if sibling_rows:
        for sibling_id, message_id in sibling_rows:
            sibling_token = uuid.uuid4()
            updated = conn.execute(
                """
                UPDATE processing_jobs
                SET status = 'running',
                    attempts = attempts + 1,
                    locked_at = now(),
                    claim_token = %s,
                    updated_at = now()
                WHERE id = %s AND status = 'pending'
                RETURNING id
                """,
                (sibling_token, sibling_id),
            ).fetchone()
            if updated is not None:
                tokens_by_message[str(message_id)] = str(sibling_token)
    message_ids = list(tokens_by_message)
    job_by_message = {str(row[1]): str(row[0])}
    for sibling_id, message_id in sibling_rows:
        job_by_message[str(message_id)] = str(sibling_id)
    messages = _load_messages(conn, message_ids)
    for message in messages:
        message["job_id"] = job_by_message.get(message["id"], str(row[0]))
        message["claim_token"] = tokens_by_message.get(message["id"], "")
    return messages


def _load_messages(conn, message_ids: list) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id::text, user_id, workspace_id, workspace_type, session_id, source, project_id,
               role, content, tool_name, tool_use_id, tool_input, tool_status, created_at
        FROM messages
        WHERE id = ANY(%s::uuid[])
        ORDER BY created_at, inserted_at
        """,
        (message_ids,),
    ).fetchall()
    loaded = []
    for row in rows:
        loaded.append(
            {
                "id": row[0],
                "user_id": row[1],
                "workspace_id": row[2],
                "workspace_type": row[3],
                "session_id": row[4],
                "source": row[5],
                "project_id": row[6] or "",
                "role": row[7],
                "content": row[8] or "",
                "tool_name": row[9] or "",
                "tool_use_id": row[10] or "",
                "tool_input": row[11] or "",
                "tool_status": row[12] or "",
                "created_at": row[13],
            }
        )
    return loaded


def _settle(job_ids: list[str], error: str) -> None:
    from app.memories import _connect, _ensure_schema

    with _connect() as conn:
        _ensure_schema(conn)
        if not error:
            conn.execute(
                """
                UPDATE processing_jobs
                SET status = 'done', last_error = '', locked_at = NULL, updated_at = now()
                WHERE id = ANY(%s::uuid[])
                """,
                (job_ids,),
            )
            return
        rows = conn.execute(
            "SELECT id::text, attempts FROM processing_jobs WHERE id = ANY(%s::uuid[])",
            (job_ids,),
        ).fetchall()
        for job_id, attempts in rows:
            if attempts >= _MAX_ATTEMPTS:
                status = "failed"
                delay = 0
            else:
                status = "pending"
                delay = min(int(attempts) * 30, 900)
            conn.execute(
                """
                UPDATE processing_jobs
                SET status = %s,
                    last_error = %s,
                    locked_at = NULL,
                    run_after = now() + make_interval(secs => %s),
                    updated_at = now()
                WHERE id = %s AND status = 'running'
                """,
                (status, error[:500], delay, job_id),
            )
