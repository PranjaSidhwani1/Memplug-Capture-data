"""Postgres tables for messages, jobs, and the memory graph.

Account records stay in Mongo. These tables store the ids Mongo already issued.
User and workspace ids are strings for that reason.
"""

from __future__ import annotations

import logging

log = logging.getLogger("memplug.graph")

_DIM = 384


def ensure_graph_schema(conn) -> None:
    """Create the graph tables and the memory history columns. Safe on every boot."""
    _memory_history(conn)
    _registries(conn)
    _messages(conn)
    _jobs(conn)
    _candidates(conn)
    _graph(conn)
    _retention_indexes(conn)
    _vector_indexes(conn)


def _memory_history(conn) -> None:
    # Retention counts from retain_from, the first time a fact was stored. Rewording keeps it.
    conn.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS retain_from TIMESTAMPTZ")
    conn.execute("UPDATE memories SET retain_from = created_at WHERE retain_from IS NULL")
    conn.execute("ALTER TABLE memories ALTER COLUMN retain_from SET DEFAULT now()")
    conn.execute("ALTER TABLE memories ALTER COLUMN retain_from SET NOT NULL")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS memories_owner_retain_idx
        ON memories (owner_type, owner_id, retain_from)
        """
    )
    conn.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS status TEXT")
    conn.execute("UPDATE memories SET status = 'active' WHERE status IS NULL OR status = ''")
    conn.execute("ALTER TABLE memories ALTER COLUMN status SET DEFAULT 'active'")
    conn.execute("ALTER TABLE memories ALTER COLUMN status SET NOT NULL")
    conn.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS confidence REAL")
    conn.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS superseded_by UUID")
    conn.execute(
        """
        DO $$
        BEGIN
            ALTER TABLE memories
                ADD CONSTRAINT memories_status_check
                CHECK (status IN ('active', 'superseded'));
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    conn.execute(
        """
        DO $$
        BEGIN
            ALTER TABLE memories
                ADD CONSTRAINT memories_superseded_by_fkey
                FOREIGN KEY (superseded_by) REFERENCES memories(id) ON DELETE SET NULL;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS memories_owner_active_idx
        ON memories (owner_type, owner_id)
        WHERE status = 'active'
        """
    )


def _registries(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY,
            workspace_type TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id UUID PRIMARY KEY,
            user_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            workspace_type TEXT NOT NULL,
            source TEXT NOT NULL,
            external_session_id TEXT NOT NULL,
            project_id TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, source, external_session_id)
        )
        """
    )


def _messages(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id UUID PRIMARY KEY,
            external_message_id TEXT NOT NULL DEFAULT '',
            event_id TEXT NOT NULL DEFAULT '',
            dedupe_key TEXT NOT NULL,
            user_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            workspace_type TEXT NOT NULL,
            session_id TEXT NOT NULL,
            source TEXT NOT NULL,
            project_id TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            tool_name TEXT NOT NULL DEFAULT '',
            tool_use_id TEXT NOT NULL DEFAULT '',
            tool_input TEXT NOT NULL DEFAULT '',
            tool_status TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS messages_dedupe_idx
        ON messages (user_id, dedupe_key)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS messages_session_idx
        ON messages (user_id, workspace_id, source, session_id, created_at)
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS message_embeddings (
            message_id UUID PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
            embedding vector({_DIM}) NOT NULL
        )
        """
    )
    conn.execute("SAVEPOINT message_guard")
    try:
        conn.execute(
            """
            CREATE OR REPLACE FUNCTION memplug_reject_message_update()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'messages are immutable';
            END;
            $$;
            """
        )
        conn.execute("DROP TRIGGER IF EXISTS messages_no_update ON messages")
        conn.execute(
            """
            CREATE TRIGGER messages_no_update
            BEFORE UPDATE ON messages
            FOR EACH ROW
            EXECUTE FUNCTION memplug_reject_message_update()
            """
        )
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT message_guard")
        log.warning("message immutability trigger was not created")
    finally:
        conn.execute("RELEASE SAVEPOINT message_guard")


def _jobs(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processing_jobs (
            id UUID PRIMARY KEY,
            message_id UUID NOT NULL UNIQUE REFERENCES messages(id),
            user_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
            locked_at TIMESTAMPTZ,
            last_error TEXT NOT NULL DEFAULT '',
            claim_token UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT processing_jobs_status_check
                CHECK (status IN ('pending', 'running', 'done', 'failed'))
        )
        """
    )
    conn.execute("ALTER TABLE processing_jobs ADD COLUMN IF NOT EXISTS claim_token UUID")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS processing_jobs_pending_idx
        ON processing_jobs (run_after, created_at)
        WHERE status = 'pending'
        """
    )


def _candidates(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_candidates (
            id UUID PRIMARY KEY,
            candidate_key TEXT NOT NULL,
            job_id UUID REFERENCES processing_jobs(id),
            user_id TEXT NOT NULL,
            owner_type TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            content TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            domain TEXT NOT NULL,
            scope TEXT NOT NULL,
            confidence REAL,
            operation TEXT NOT NULL DEFAULT '',
            final_content TEXT NOT NULL DEFAULT '',
            target_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            source_message_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_evidence (
            id UUID PRIMARY KEY,
            memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
            message_id UUID NOT NULL REFERENCES messages(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (memory_id, message_id)
        )
        """
    )


def _graph(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entities (
            id UUID PRIMARY KEY,
            user_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            owner_type TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            name TEXT NOT NULL,
            name_norm TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            canonical_name TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS entities_owner_name_idx
        ON entities (owner_type, owner_id, entity_type, name_norm)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS entities_owner_idx
        ON entities (owner_type, owner_id)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entity_aliases (
            id UUID PRIMARY KEY,
            entity_id UUID NOT NULL REFERENCES entities(id),
            alias TEXT NOT NULL,
            alias_norm TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS entity_aliases_norm_idx
        ON entity_aliases (entity_id, alias_norm)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS entity_aliases_lookup_idx
        ON entity_aliases (alias_norm)
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS entity_vectors (
            entity_id UUID PRIMARY KEY REFERENCES entities(id),
            embedding vector({_DIM}) NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entity_relationships (
            id UUID PRIMARY KEY,
            source_entity_id UUID NOT NULL REFERENCES entities(id),
            target_entity_id UUID NOT NULL REFERENCES entities(id),
            relationship_type TEXT NOT NULL,
            properties JSONB NOT NULL DEFAULT '{}'::jsonb,
            valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
            valid_until TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT entity_relationships_distinct
                CHECK (source_entity_id <> target_entity_id)
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS entity_relationships_active_idx
        ON entity_relationships (source_entity_id, target_entity_id, relationship_type)
        WHERE valid_until IS NULL
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS entity_relationships_source_idx
        ON entity_relationships (source_entity_id)
        WHERE valid_until IS NULL
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS entity_relationships_target_idx
        ON entity_relationships (target_entity_id)
        WHERE valid_until IS NULL
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_entities (
            memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
            entity_id UUID NOT NULL REFERENCES entities(id),
            role TEXT NOT NULL DEFAULT 'mentioned',
            PRIMARY KEY (memory_id, entity_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS relationship_evidence (
            id UUID PRIMARY KEY,
            relationship_id UUID NOT NULL REFERENCES entity_relationships(id),
            message_id UUID REFERENCES messages(id),
            memory_id UUID REFERENCES memories(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (relationship_id, message_id)
        )
        """
    )


def _retention_indexes(conn) -> None:
    """Lookups the hourly retention purge makes for each account."""
    for statement in (
        "CREATE INDEX IF NOT EXISTS messages_workspace_inserted_idx ON messages (workspace_type, workspace_id, inserted_at)",
        "CREATE INDEX IF NOT EXISTS memory_candidates_owner_created_idx ON memory_candidates (owner_type, owner_id, created_at)",
        "CREATE INDEX IF NOT EXISTS memory_candidates_job_idx ON memory_candidates (job_id)",
        "CREATE INDEX IF NOT EXISTS memory_evidence_message_idx ON memory_evidence (message_id)",
        "CREATE INDEX IF NOT EXISTS relationship_evidence_message_idx ON relationship_evidence (message_id)",
        "CREATE INDEX IF NOT EXISTS memory_entities_entity_idx ON memory_entities (entity_id)",
        "CREATE INDEX IF NOT EXISTS entity_relationships_source_all_idx ON entity_relationships (source_entity_id)",
        "CREATE INDEX IF NOT EXISTS entity_relationships_target_all_idx ON entity_relationships (target_entity_id)",
    ):
        conn.execute(statement)


def _vector_indexes(conn) -> None:
    _hnsw(
        conn,
        "memory_vectors_embedding_hnsw",
        "CREATE INDEX IF NOT EXISTS memory_vectors_embedding_hnsw ON memory_vectors USING hnsw (embedding vector_cosine_ops)",
    )
    _hnsw(
        conn,
        "message_embeddings_hnsw",
        "CREATE INDEX IF NOT EXISTS message_embeddings_hnsw ON message_embeddings USING hnsw (embedding vector_cosine_ops)",
    )
    _hnsw(
        conn,
        "entity_vectors_hnsw",
        "CREATE INDEX IF NOT EXISTS entity_vectors_hnsw ON entity_vectors USING hnsw (embedding vector_cosine_ops)",
    )


def _hnsw(conn, name: str, statement: str) -> None:
    conn.execute(f"SAVEPOINT {name}")
    try:
        conn.execute(statement)
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        log.warning("vector index %s was not created", name)
    finally:
        conn.execute(f"RELEASE SAVEPOINT {name}")
