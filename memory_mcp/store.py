"""Memories in the same Neon database the capture service writes.

Search is hybrid: keyword rank and pgvector cosine similarity, inside the
domains this process is allowed to see.
"""

from __future__ import annotations

import logging
import uuid

import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from memory_mcp.domains import UNCATEGORISED, resolve_domain
from memory_mcp.embed import embed

log = logging.getLogger("memplug.mcp")

_MAX_CONTENT = 8_000
_MAX_LIMIT = 50
_DEFAULT_LIMIT = 10
_SUPERSEDE_SIMILARITY = 0.92
_TYPES = {"fact", "preference", "decision", "plan"}


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


class MemoryStore:
    def __init__(self, database_url: str, user_id: str, granted_domains: frozenset[str]) -> None:
        self.user_id = user_id
        self.granted_domains = granted_domains
        self._url = database_url
        with self._connect() as conn:
            self._ensure_schema(conn)
            conn.commit()

    def save(
        self,
        content: str,
        domain: str | None = None,
        sub_domain: str | None = None,
        memory_type: str | None = None,
        source_event_ids: list[str] | None = None,
    ) -> dict:
        text = content.strip() if isinstance(content, str) else ""
        if not text:
            return {"status": "rejected", "reason": "content is required"}
        if len(text) > _MAX_CONTENT:
            return {"status": "rejected", "reason": "content is too long"}

        suggested = domain.strip() if isinstance(domain, str) else ""
        resolved = resolve_domain(suggested) if suggested else None
        needs_review = False
        reason = None
        if suggested and resolved is None:
            resolved = UNCATEGORISED if UNCATEGORISED in self.granted_domains else None
            needs_review = True
            reason = "domain could not be resolved; stored as Uncategorised"
        elif resolved is None:
            resolved = UNCATEGORISED if UNCATEGORISED in self.granted_domains else None
        if resolved is None or resolved not in self.granted_domains:
            return {"status": "rejected", "reason": "domain is not granted"}

        sub = sub_domain.strip()[:120] if isinstance(sub_domain, str) and sub_domain.strip() else None
        kind = memory_type.strip().lower() if isinstance(memory_type, str) else ""
        if kind not in _TYPES:
            kind = "fact"
        sources = _clean_list(source_event_ids, limit=50, item_length=200)
        entity = sub or text[:160]
        content_norm = _norm(text)

        try:
            vector = embed([text])[0]
            with self._connect() as conn:
                saved = self._upsert(
                    conn,
                    content=text,
                    content_norm=content_norm,
                    domain=resolved,
                    sub_domain=sub,
                    entity=entity,
                    memory_type=kind,
                    source_event_ids=sources,
                    vector=vector,
                )
                conn.commit()
        except Exception:
            log.exception("save_memory failed")
            return {"status": "retryable_error", "reason": "memory could not be stored"}

        log.info("mcp saved id=%s domain=%s content=%s", saved["id"], resolved, text)
        if needs_review:
            saved["status"] = "needs_review"
            saved["reason"] = reason
        return saved

    def search(
        self,
        query: str,
        domains: list[str] | None = None,
        sub_domain: str | None = None,
        memory_type: str | None = None,
        limit: int | None = None,
    ) -> dict:
        text = query.strip() if isinstance(query, str) else ""
        if not text:
            return {"status": "rejected", "reason": "query is required", "query": "", "memories": []}

        selected = self._filter_domains(domains)
        cap = _DEFAULT_LIMIT if limit is None else max(1, min(int(limit), _MAX_LIMIT))
        if not selected:
            return {"query": text, "memories": []}

        sub = sub_domain.strip() if isinstance(sub_domain, str) else ""
        kind = memory_type.strip().lower() if isinstance(memory_type, str) else ""
        try:
            vector = embed([text])[0]
            with self._connect() as conn:
                rows = self._search_rows(conn, text, vector, selected, sub, kind, cap)
        except Exception:
            log.exception("search_memory failed")
            return {"status": "retryable_error", "reason": "search failed", "query": text, "memories": []}

        log.info("mcp search query=%s hits=%s", text, len(rows))
        return {"query": text, "memories": rows}

    def list_domains(self) -> dict:
        from memory_mcp.domains import catalogue

        visible = [item for item in catalogue() if item["name"] in self.granted_domains]
        return {"domains": visible}

    def list_sub_domains(self, domain: str) -> dict:
        suggested = domain.strip() if isinstance(domain, str) else ""
        if not suggested:
            return {"status": "rejected", "reason": "domain is required"}
        resolved = resolve_domain(suggested)
        if resolved is None:
            return {"status": "rejected", "reason": "unknown domain"}
        if resolved not in self.granted_domains:
            return {"status": "rejected", "reason": "domain is not granted"}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT sub_domain
                FROM memories
                WHERE user_id = %s
                  AND domain = %s
                  AND status = 'active'
                  AND sub_domain IS NOT NULL
                  AND sub_domain <> ''
                ORDER BY sub_domain
                """,
                (self.user_id, resolved),
            ).fetchall()
        return {"domain": resolved, "sub_domains": [row[0] for row in rows]}

    def _connect(self):
        conn = psycopg.connect(self._url, prepare_threshold=None)
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
        register_vector(conn)
        return conn

    def _ensure_schema(self, conn) -> None:
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
                source TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                project TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (user_id, content_norm)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_vectors (
                memory_id UUID PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
                embedding vector(384) NOT NULL
            )
            """
        )
        conn.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS sub_domain TEXT")
        conn.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS sub_domain_norm TEXT")
        conn.execute(
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb"
        )
        conn.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'")
        conn.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS superseded_by UUID")
        conn.execute(
            "ALTER TABLE memories ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        )

    def _upsert(
        self,
        conn,
        *,
        content: str,
        content_norm: str,
        domain: str,
        sub_domain: str | None,
        entity: str,
        memory_type: str,
        source_event_ids: list[str],
        vector: list[float],
    ) -> dict:
        sub_norm = _norm(sub_domain) if sub_domain else None
        existing = conn.execute(
            """
            SELECT id
            FROM memories
            WHERE user_id = %s AND status = 'active' AND content_norm = %s
            LIMIT 1
            """,
            (self.user_id, content_norm),
        ).fetchone()
        if existing is not None:
            memory_id = existing[0]
            conn.execute(
                """
                UPDATE memories
                SET domain = %s,
                    sub_domain = %s,
                    sub_domain_norm = %s,
                    entity = %s,
                    memory_type = %s,
                    source_event_ids = COALESCE(
                        (
                            SELECT jsonb_agg(DISTINCT item)
                            FROM jsonb_array_elements_text(
                                COALESCE(source_event_ids, '[]'::jsonb) || %s::jsonb
                            ) AS item
                        ),
                        '[]'::jsonb
                    ),
                    updated_at = now()
                WHERE id = %s
                """,
                (domain, sub_domain, sub_norm, entity, memory_type, Jsonb(source_event_ids), memory_id),
            )
            conn.execute(
                """
                INSERT INTO memory_vectors (memory_id, embedding)
                VALUES (%s, %s)
                ON CONFLICT (memory_id) DO UPDATE SET embedding = EXCLUDED.embedding
                """,
                (memory_id, vector),
            )
            return {"status": "saved", "id": str(memory_id), "domain": domain, "sub_domain": sub_domain}

        near = conn.execute(
            """
            SELECT m.id, 1 - (v.embedding <=> %s) AS similarity
            FROM memories m
            JOIN memory_vectors v ON v.memory_id = m.id
            WHERE m.user_id = %s
              AND m.domain = %s
              AND m.status = 'active'
            ORDER BY v.embedding <=> %s
            LIMIT 1
            """,
            (vector, self.user_id, domain, vector),
        ).fetchone()

        memory_id = uuid.uuid4()
        if near is not None and float(near[1]) >= _SUPERSEDE_SIMILARITY:
            conn.execute(
                """
                UPDATE memories
                SET status = 'superseded', superseded_by = %s, updated_at = now()
                WHERE id = %s
                """,
                (memory_id, near[0]),
            )

        conn.execute(
            """
            INSERT INTO memories (
                id, user_id, domain, sub_domain, sub_domain_norm, entity, entities,
                content, content_norm, memory_type, confidence, source, session_id,
                project, source_event_ids, status, created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s::jsonb,
                %s, %s, %s, %s, 'mcp', '',
                '', %s::jsonb, 'active', now(), now()
            )
            """,
            (
                memory_id,
                self.user_id,
                domain,
                sub_domain,
                sub_norm,
                entity,
                Jsonb([entity]),
                content,
                content_norm,
                memory_type,
                1.0,
                Jsonb(source_event_ids),
            ),
        )
        conn.execute(
            "INSERT INTO memory_vectors (memory_id, embedding) VALUES (%s, %s)",
            (memory_id, vector),
        )
        return {"status": "saved", "id": str(memory_id), "domain": domain, "sub_domain": sub_domain}

    def _search_rows(self, conn, query: str, vector: list[float], domains: list[str], sub: str, kind: str, limit: int):
        sql = """
            SELECT
                m.id::text,
                m.content,
                m.domain,
                m.sub_domain,
                COALESCE(m.confidence, 0),
                m.updated_at,
                m.source_event_ids,
                (
                    0.5 * CASE WHEN v.embedding IS NULL THEN 0 ELSE 1 - (v.embedding <=> %s) END
                    + 0.5 * LEAST(
                        ts_rank_cd(to_tsvector('english', m.content), plainto_tsquery('english', %s)),
                        1
                    )
                ) AS score
            FROM memories m
            LEFT JOIN memory_vectors v ON v.memory_id = m.id
            WHERE m.user_id = %s
              AND m.status = 'active'
              AND m.domain = ANY(%s)
        """
        params: list[object] = [vector, query, self.user_id, domains]
        if sub:
            sql += " AND m.sub_domain_norm = %s"
            params.append(_norm(sub))
        if kind:
            sql += " AND m.memory_type = %s"
            params.append(kind)
        sql += " ORDER BY score DESC LIMIT %s"
        params.append(limit)
        memories = []
        for row in conn.execute(sql, params).fetchall():
            sources = row[6] if isinstance(row[6], list) else []
            updated = row[5]
            memories.append(
                {
                    "id": row[0],
                    "content": row[1],
                    "domain": row[2],
                    "sub_domain": row[3],
                    "confidence": round(float(row[7]), 3),
                    "updated_at": updated.isoformat().replace("+00:00", "Z") if updated is not None else "",
                    "sources": sources,
                }
            )
        return memories

    def _filter_domains(self, domains: list[str] | None) -> list[str]:
        if not domains:
            return sorted(self.granted_domains)
        selected: list[str] = []
        for name in domains:
            if not isinstance(name, str):
                continue
            resolved = resolve_domain(name)
            if resolved is not None and resolved in self.granted_domains and resolved not in selected:
                selected.append(resolved)
        return selected


def _clean_list(values: list[str] | None, *, limit: int, item_length: int) -> list[str]:
    if not values:
        return []
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if not item:
            continue
        cleaned.append(item[:item_length])
        if len(cleaned) >= limit:
            break
    return cleaned
