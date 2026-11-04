"""Canonical memory rows in Postgres, and their embeddings in pgvector."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone

from app.config import postgres_url

log = logging.getLogger("memplug.postgres")

_DIM = 384
_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_schema_ready = False
_schema_lock = threading.Lock()
_embed_lock = threading.Lock()
_embedder = None


def save_memories(
    user_id: str,
    source: str,
    session_id: str,
    project: str,
    memories: list[dict],
    owner_type: str = "user",
    owner_id: str = "",
) -> int:
    if not memories:
        return 0
    url = postgres_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    vectors = _embed([item["content"] for item in memories])
    saved = 0
    with _connect() as conn:
        _ensure_schema(conn)
        for item, vector in zip(memories, vectors, strict=True):
            memory_id = _upsert_memory(
                conn, user_id, source, session_id, project, item, owner_type, owner_id or user_id
            )
            log.info(
                "postgres saved id=%s user=%s source=%s session=%s domain=%s type=%s content=%s embedding_dim=%s",
                memory_id,
                user_id,
                source,
                session_id,
                item["domain"],
                item["memory_type"],
                item["content"],
                len(vector),
            )
            conn.execute(
                """
                INSERT INTO memory_vectors (memory_id, embedding)
                VALUES (%s, %s)
                ON CONFLICT (memory_id) DO UPDATE SET embedding = EXCLUDED.embedding
                """,
                (memory_id, vector),
            )
            saved += 1
        conn.commit()
    return saved


def _upsert_memory(
    conn,
    user_id: str,
    source: str,
    session_id: str,
    project: str,
    item: dict,
    owner_type: str = "user",
    owner_id: str = "",
):
    norm = " ".join(item["content"].casefold().split())
    row = conn.execute(
        """
        INSERT INTO memories (
            id, user_id, owner_type, owner_id, domain, content, content_norm,
            memory_type, source, session_id, project
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (owner_type, owner_id, content_norm) DO UPDATE
        SET domain = EXCLUDED.domain,
            memory_type = EXCLUDED.memory_type,
            source = EXCLUDED.source,
            session_id = EXCLUDED.session_id,
            project = EXCLUDED.project,
            updated_at = now()
        RETURNING id
        """,
        (
            uuid.uuid4(),
            user_id,
            owner_type if owner_type == "team" else "user",
            owner_id or user_id,
            item["domain"],
            item["content"],
            norm,
            item["memory_type"],
            source,
            session_id,
            project,
        ),
    ).fetchone()
    return row[0]


def list_memories(user_id: str, team_ids: list[str]) -> list[dict]:
    """Personal memories, plus every team this account belongs to."""
    if not postgres_url() or not user_id:
        return []
    teams = [team_id for team_id in team_ids if team_id]
    sql = """
        SELECT id::text, owner_type, owner_id, domain, COALESCE(sub_domain, ''),
               content, memory_type, source, project, session_id, created_at, updated_at
        FROM memories
        WHERE owner_type = 'user' AND owner_id = %s
    """
    params: list[object] = [user_id]
    if teams:
        sql += " OR (owner_type = 'team' AND owner_id = ANY(%s))"
        params.append(teams)
    sql += " ORDER BY updated_at DESC, created_at DESC"
    with _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(sql, params).fetchall()
    return [_memory_out(row) for row in rows]


def delete_memory(memory_id: str, user_id: str, team_ids: list[str]) -> bool:
    if not postgres_url() or not user_id:
        return False
    try:
        parsed = uuid.UUID(memory_id)
    except ValueError:
        return False
    teams = {team_id for team_id in team_ids if team_id}
    with _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT owner_type, owner_id FROM memories WHERE id = %s",
            (parsed,),
        ).fetchone()
        if not row or not _memory_allowed(row[0], row[1], user_id, teams):
            return False
        conn.execute("DELETE FROM memories WHERE id = %s", (parsed,))
        conn.commit()
    log.info("postgres deleted id=%s user=%s", memory_id, user_id)
    return True


def _memory_allowed(owner_type: str, owner_id: str, user_id: str, team_ids: set[str]) -> bool:
    if owner_type == "team":
        return owner_id in team_ids
    return owner_type == "user" and owner_id == user_id


def _memory_out(row) -> dict:
    return {
        "id": row[0],
        "owner_type": row[1] if row[1] == "team" else "user",
        "owner_id": row[2],
        "domain": row[3] or "",
        "sub_domain": row[4] or "",
        "content": row[5] or "",
        "memory_type": row[6] or "",
        "source": row[7] or "",
        "project": row[8] or "",
        "session_id": row[9] or "",
        "created_at": _iso(row[10]),
        "updated_at": _iso(row[11]),
    }


def _iso(value) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return "" if value is None else str(value)


def ensure_schema() -> None:
    """Create the memory tables on the Neon database. Safe to call on every boot."""
    if not postgres_url():
        return
    with _connect() as conn:
        _ensure_schema(conn)


def _connect():
    import psycopg
    from pgvector.psycopg import register_vector

    conn = psycopg.connect(postgres_url(), prepare_threshold=None)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.commit()
    register_vector(conn)
    return conn


def _ensure_schema(conn) -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id UUID PRIMARY KEY,
                user_id TEXT NOT NULL,
                owner_type TEXT NOT NULL DEFAULT 'user',
                owner_id TEXT NOT NULL,
                domain TEXT NOT NULL,
                sub_domain TEXT,
                content TEXT NOT NULL,
                content_norm TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                project TEXT NOT NULL DEFAULT '',
                source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS sub_domain TEXT")
        conn.execute(
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb"
        )
        conn.execute(
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        )
        _drop_retired_columns(conn)
        _ensure_owner(conn)
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS memories_owner_domain_idx
            ON memories (owner_type, owner_id, domain)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS memories_content_fts_idx
            ON memories USING GIN (to_tsvector('english', content))
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS memory_vectors (
                memory_id UUID PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
                embedding vector({_DIM}) NOT NULL
            )
            """
        )
        conn.commit()
        _schema_ready = True


def _drop_retired_columns(conn) -> None:
    """Remove columns the product no longer stores. Safe on every boot."""
    has_status = conn.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'memories' AND column_name = 'status'
        """
    ).fetchone()
    if has_status:
        conn.execute("DELETE FROM memories WHERE status = 'superseded'")
    for column in ("entities", "entity", "confidence", "sub_domain_norm", "status", "superseded_by"):
        conn.execute(f"ALTER TABLE memories DROP COLUMN IF EXISTS {column}")


def _ensure_owner(conn) -> None:
    """A memory belongs to one user or one team. Existing rows become personal."""
    conn.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS owner_type TEXT")
    conn.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS owner_id TEXT")
    conn.execute("UPDATE memories SET owner_type = 'user' WHERE owner_type IS NULL")
    conn.execute("UPDATE memories SET owner_id = user_id WHERE owner_id IS NULL")
    conn.execute("ALTER TABLE memories ALTER COLUMN owner_type SET DEFAULT 'user'")
    conn.execute("ALTER TABLE memories ALTER COLUMN owner_type SET NOT NULL")
    conn.execute("ALTER TABLE memories ALTER COLUMN owner_id SET NOT NULL")
    conn.execute("ALTER TABLE memories DROP CONSTRAINT IF EXISTS memories_user_id_content_norm_key")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS memories_owner_content_idx
        ON memories (owner_type, owner_id, content_norm)
        """
    )


def _embed(texts: list[str]) -> list[list[float]]:
    global _embedder
    with _embed_lock:
        if _embedder is None:
            from fastembed import TextEmbedding

            _embedder = TextEmbedding(model_name=_MODEL_NAME)
        rows = [vector.tolist() for vector in _embedder.embed(texts)]
    if any(len(vector) != _DIM for vector in rows):
        raise RuntimeError("embedding size does not match the vector column")
    return rows
