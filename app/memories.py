"""Canonical memory rows in Postgres, and their embeddings in pgvector."""

from __future__ import annotations

import logging
import threading
import uuid

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
            memory_id = _upsert_memory(conn, user_id, source, session_id, project, item)
            log.info(
                "postgres saved id=%s user=%s source=%s session=%s domain=%s entity=%s type=%s confidence=%s content=%s embedding_dim=%s",
                memory_id,
                user_id,
                source,
                session_id,
                item["domain"],
                item["entity"],
                item["memory_type"],
                item["confidence"],
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


def _upsert_memory(conn, user_id: str, source: str, session_id: str, project: str, item: dict):
    from psycopg.types.json import Jsonb

    norm = " ".join(item["content"].casefold().split())
    row = conn.execute(
        """
        INSERT INTO memories (
            id, user_id, domain, entity, entities, content, content_norm,
            memory_type, confidence, source, session_id, project
        )
        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, content_norm) DO UPDATE
        SET domain = EXCLUDED.domain,
            entity = EXCLUDED.entity,
            entities = EXCLUDED.entities,
            confidence = EXCLUDED.confidence
        RETURNING id
        """,
        (
            uuid.uuid4(),
            user_id,
            item["domain"],
            item["entity"],
            Jsonb(item["entities"]),
            item["content"],
            norm,
            item["memory_type"],
            item["confidence"],
            source,
            session_id,
            project,
        ),
    ).fetchone()
    return row[0]


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
                domain TEXT NOT NULL,
                entity TEXT NOT NULL,
                entities JSONB NOT NULL DEFAULT '[]'::jsonb,
                content TEXT NOT NULL,
                content_norm TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                confidence REAL,
                source TEXT NOT NULL,
                session_id TEXT NOT NULL,
                project TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (user_id, content_norm)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS memories_user_domain_idx
            ON memories (user_id, domain)
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
