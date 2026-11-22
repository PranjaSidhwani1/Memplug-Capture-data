"""Delete what a plan no longer keeps: memories, raw transcripts, and the graph they leave behind."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from app.access import effective_cutoff, plan_for_user
from app.plans import effective_plan

log = logging.getLogger("memplug.retention")

_INTERVAL_SECONDS = 60 * 60
_started = False

_OLD_MESSAGES = """
    SELECT id FROM messages
    WHERE workspace_type = %s AND workspace_id = %s AND LEAST(inserted_at, created_at) < %s
"""

_OWNER_EDGES = """
    SELECT r.id FROM entity_relationships r
    JOIN entities e ON e.id = r.source_entity_id
    WHERE e.owner_type = %s AND e.owner_id = %s
"""


def start_purge_loop() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="retention-purge").start()


def _loop() -> None:
    while True:
        try:
            from app.billing import reconcile_accounts

            reconcile_accounts()
        except Exception:
            log.exception("billing reconcile failed")
        try:
            purge_expired()
        except Exception:
            log.exception("retention purge failed")
        time.sleep(_INTERVAL_SECONDS)


def purge_expired() -> None:
    """Apply every account's retention. Team data follows the team owner's plan."""
    from app.store import database

    db = database()
    plans: dict[str, str] = {}
    owners: list[tuple[str, str, datetime | None]] = []
    fields = {"plan": 1, "plan_status": 1, "plan_period_end": 1, "plan_grace_until": 1, "plan_grant": 1}
    for doc in db["users"].find({}, fields):
        user_id = str(doc["_id"])
        plan = effective_plan(doc)
        plans[user_id] = plan
        owners.append(("user", user_id, effective_cutoff(plan)))
    for team in db["teams"].find({}, {"created_by": 1}):
        plan = plans.get(str(team.get("created_by") or ""), "free")
        owners.append(("team", str(team["_id"]), effective_cutoff(plan)))
    purge_owners(owners)


def purge_user(user_id: str) -> None:
    """Apply one account's retention now, including the teams it owns."""
    from app.store import database

    cutoff = effective_cutoff(plan_for_user(user_id) or "free")
    if cutoff is None:
        return
    owners: list[tuple[str, str, datetime | None]] = [("user", user_id, cutoff)]
    for team in database()["teams"].find({"created_by": user_id}, {"_id": 1}):
        owners.append(("team", str(team["_id"]), cutoff))
    purge_owners(owners)


def purge_owners(owners: list[tuple[str, str, datetime | None]]) -> None:
    doomed = [(kind, owner, cutoff) for kind, owner, cutoff in owners if owner and cutoff is not None]
    if not doomed:
        return
    from app.config import postgres_url

    if postgres_url():
        _purge_postgres(doomed)
    for kind, owner, cutoff in doomed:
        try:
            _purge_conversations(kind, owner, cutoff)
        except Exception:
            log.exception("conversation purge failed owner=%s:%s", kind, owner)


def _purge_postgres(doomed: list[tuple[str, str, datetime]]) -> None:
    from app.memories import _connect, _ensure_schema

    totals: dict[str, int] = {}
    with _connect() as conn:
        _ensure_schema(conn)
        conn.commit()
        for kind, owner, cutoff in doomed:
            try:
                removed = _purge_owner(conn, kind, owner, cutoff)
                conn.commit()
            except Exception:
                conn.rollback()
                log.exception("retention purge failed owner=%s:%s", kind, owner)
                continue
            for key, count in removed.items():
                totals[key] = totals.get(key, 0) + count
    if any(totals.values()):
        log.info("retention removed %s", totals)


def _purge_owner(conn, kind: str, owner: str, cutoff: datetime) -> dict[str, int]:
    scope = (kind, owner, cutoff)
    pair = (kind, owner)
    removed: dict[str, int] = {}
    removed["memories"] = _count(
        conn.execute(
            "DELETE FROM memories WHERE owner_type = %s AND owner_id = %s AND retain_from < %s",
            scope,
        )
    )
    removed["candidates"] = _count(
        conn.execute(
            "DELETE FROM memory_candidates WHERE owner_type = %s AND owner_id = %s AND created_at < %s",
            scope,
        )
    )
    conn.execute(f"DELETE FROM memory_evidence WHERE message_id IN ({_OLD_MESSAGES})", scope)
    conn.execute(
        f"""
        UPDATE relationship_evidence SET message_id = NULL
        WHERE memory_id IS NOT NULL AND message_id IN ({_OLD_MESSAGES})
        """,
        scope,
    )
    conn.execute(f"DELETE FROM relationship_evidence WHERE message_id IN ({_OLD_MESSAGES})", scope)
    conn.execute(
        f"""
        DELETE FROM memory_candidates
        WHERE job_id IN (
            SELECT job.id FROM processing_jobs job
            WHERE job.status <> 'running' AND job.message_id IN ({_OLD_MESSAGES})
        )
        """,
        scope,
    )
    conn.execute(
        f"DELETE FROM processing_jobs WHERE status <> 'running' AND message_id IN ({_OLD_MESSAGES})",
        scope,
    )
    removed["messages"] = _count(
        conn.execute(
            """
            DELETE FROM messages m
            WHERE m.workspace_type = %s AND m.workspace_id = %s AND LEAST(m.inserted_at, m.created_at) < %s
              AND NOT EXISTS (SELECT 1 FROM processing_jobs job WHERE job.message_id = m.id)
            """,
            scope,
        )
    )
    conn.execute(
        f"""
        DELETE FROM relationship_evidence
        WHERE message_id IS NULL AND memory_id IS NULL
          AND relationship_id IN ({_OWNER_EDGES})
        """,
        pair,
    )
    removed["relationships"] = _count(
        conn.execute(
            """
            DELETE FROM entity_relationships r
            USING entities e
            WHERE r.source_entity_id = e.id
              AND e.owner_type = %s AND e.owner_id = %s
              AND r.created_at < %s
              AND NOT EXISTS (SELECT 1 FROM relationship_evidence ev WHERE ev.relationship_id = r.id)
            """,
            scope,
        )
    )
    removed["entities"] = _count(
        conn.execute(
            """
            WITH orphan AS (
                SELECT e.id FROM entities e
                WHERE e.owner_type = %s AND e.owner_id = %s AND e.created_at < %s
                  AND NOT EXISTS (SELECT 1 FROM memory_entities me WHERE me.entity_id = e.id)
                  AND NOT EXISTS (
                      SELECT 1 FROM entity_relationships r
                      WHERE r.source_entity_id = e.id OR r.target_entity_id = e.id
                  )
            ),
            aliases AS (
                DELETE FROM entity_aliases WHERE entity_id IN (SELECT id FROM orphan)
            ),
            vectors AS (
                DELETE FROM entity_vectors WHERE entity_id IN (SELECT id FROM orphan)
            )
            DELETE FROM entities WHERE id IN (SELECT id FROM orphan)
            """,
            scope,
        )
    )
    return removed


def _purge_conversations(kind: str, owner: str, cutoff: datetime) -> None:
    """Raw chat in Mongo follows the same window as the Postgres copy."""
    from app.store import database

    col = database()["conversations"]
    stamp = cutoff.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if kind == "team":
        scope: dict = {"workspace_type": "team", "workspace_id": owner}
    else:
        scope = {"user_id": owner, "workspace_type": {"$ne": "team"}}
    for condition in ({"saved_at": {"$lt": stamp}}, {"timestamp": {"$lt": stamp}}):
        col.update_many({**scope, "messages": {"$elemMatch": condition}}, {"$pull": {"messages": condition}})
    col.delete_many({**scope, "messages": {"$size": 0}})


def _count(cursor) -> int:
    return max(0, cursor.rowcount or 0)
