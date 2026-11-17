"""Store one captured message and enqueue processing. The message row is insert-only."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from app.config import meta_api_key, meta_model, postgres_url

log = logging.getLogger("memplug.ingest")

_COALESCE_SECONDS = 5
_MAX_CONTENT = 1_000_000


def dedupe_key(
    *,
    event_id: str = "",
    external_message_id: str = "",
    role: str,
    content: str,
    tool_use_id: str = "",
    tool_name: str = "",
    tool_input: str = "",
    source: str = "",
    session_id: str = "",
    workspace_id: str = "",
) -> str:
    event = event_id.strip()
    if event:
        return "event:" + event[:200]
    external = external_message_id.strip()
    if external:
        return "external:" + external[:200]
    digest = hashlib.sha256()
    digest.update(source.encode("utf-8"))
    digest.update(b"\0")
    digest.update(session_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(workspace_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(role.encode("utf-8"))
    digest.update(b"\0")
    digest.update(content.encode("utf-8"))
    digest.update(b"\0")
    digest.update(tool_use_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(tool_name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(tool_input.encode("utf-8"))
    return "body:" + digest.hexdigest()


def record_captured_message(
    *,
    user_id: str,
    workspace_type: str,
    workspace_id: str,
    source: str,
    session_id: str,
    project_id: str,
    role: str,
    content: str,
    timestamp: str | None = None,
    event_id: str = "",
    external_message_id: str = "",
    tool_name: str = "",
    tool_use_id: str = "",
    tool_input: str = "",
    tool_status: str = "",
) -> None:
    """Insert the immutable message and, when a model is configured, a job."""
    if not user_id or not postgres_url():
        return
    text = content.strip()
    if not text or len(text) > _MAX_CONTENT:
        if text:
            log.warning("message was not copied to postgres session=%s bytes=%s", session_id, len(text))
        return
    kind = workspace_type if workspace_type in {"user", "team"} else "user"
    owner = workspace_id or user_id
    from app.memories import _connect, _ensure_schema

    key = dedupe_key(
        event_id=event_id,
        external_message_id=external_message_id,
        role=role,
        content=text,
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        tool_input=tool_input,
        source=source,
        session_id=session_id,
        workspace_id=owner,
    )
    with _connect() as conn:
        _ensure_schema(conn)
        _touch_registry(conn, user_id, owner, kind, source, session_id, project_id)
        message_id = _insert_message(
            conn,
            key=key,
            user_id=user_id,
            workspace_id=owner,
            workspace_type=kind,
            source=source,
            session_id=session_id,
            project_id=project_id or "",
            role=role,
            content=text,
            timestamp=_parse_time(timestamp),
            event_id=event_id.strip()[:200],
            external_message_id=external_message_id.strip()[:200],
            tool_name=tool_name.strip(),
            tool_use_id=tool_use_id.strip(),
            tool_input=tool_input,
            tool_status=tool_status.strip(),
        )
        if message_id is None:
            return
        if meta_api_key() and meta_model():
            conn.execute(
                """
                INSERT INTO processing_jobs (id, message_id, user_id, workspace_id, status, run_after)
                VALUES (%s, %s, %s, %s, 'pending', now() + make_interval(secs => %s))
                ON CONFLICT (message_id) DO NOTHING
                """,
                (uuid.uuid4(), message_id, user_id, owner, _COALESCE_SECONDS),
            )
        log.info("postgres message id=%s session=%s role=%s", message_id, session_id, role)


def _touch_registry(conn, user_id: str, workspace_id: str, workspace_type: str, source: str, session_id: str, project_id: str) -> None:
    conn.execute(
        """
        INSERT INTO users (id) VALUES (%s)
        ON CONFLICT (id) DO UPDATE SET updated_at = now()
        """,
        (user_id,),
    )
    conn.execute(
        """
        INSERT INTO workspaces (id, workspace_type) VALUES (%s, %s)
        ON CONFLICT (id) DO UPDATE SET workspace_type = EXCLUDED.workspace_type, updated_at = now()
        """,
        (workspace_id, workspace_type),
    )
    conn.execute(
        """
        INSERT INTO sessions (
            id, user_id, workspace_id, workspace_type, source, external_session_id, project_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, source, external_session_id)
        DO UPDATE SET
            workspace_id = EXCLUDED.workspace_id,
            workspace_type = EXCLUDED.workspace_type,
            project_id = EXCLUDED.project_id,
            updated_at = now()
        """,
        (uuid.uuid4(), user_id, workspace_id, workspace_type, source, session_id, project_id or ""),
    )


def _insert_message(conn, *, key: str, user_id: str, workspace_id: str, workspace_type: str, source: str, session_id: str, project_id: str, role: str, content: str, timestamp: datetime, event_id: str, external_message_id: str, tool_name: str, tool_use_id: str, tool_input: str, tool_status: str):
    row = conn.execute(
        """
        INSERT INTO messages (
            id, external_message_id, event_id, dedupe_key, user_id, workspace_id, workspace_type,
            session_id, source, project_id, role, content, tool_name, tool_use_id, tool_input,
            tool_status, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, dedupe_key) DO NOTHING
        RETURNING id
        """,
        (
            uuid.uuid4(),
            external_message_id,
            event_id,
            key,
            user_id,
            workspace_id,
            workspace_type,
            session_id,
            source,
            project_id,
            role,
            content,
            tool_name,
            tool_use_id,
            tool_input,
            tool_status,
            timestamp,
        ),
    ).fetchone()
    if row is not None:
        return row[0]
    existing = conn.execute(
        "SELECT id FROM messages WHERE user_id = %s AND dedupe_key = %s",
        (user_id, key),
    ).fetchone()
    return existing[0] if existing else None


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
