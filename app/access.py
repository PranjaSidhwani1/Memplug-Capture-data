"""Which plan covers a workspace, what it may do today, and how far back its memory reaches."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.plans import (
    PLANS,
    aware,
    clamp_to_epoch,
    effective_plan,
    fetch_limit,
    includes,
    retention_cutoff,
    retention_days,
)

log = logging.getLogger("memplug.access")

_ready = False
_epoch: datetime | None = None
_epoch_lock = threading.Lock()


class AccessError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class TeamState:
    team_id: str
    owner_id: str
    owner_plan: str
    active: bool
    reason: str


@dataclass
class Access:
    allowed: bool
    reason: str = ""
    plan: str | None = None
    retain_after: datetime | None = None
    limit: int | None = None
    meter: tuple[str, str] | None = None


@dataclass
class Reservation:
    meter: tuple[str, str] | None
    day: str


def _db():
    from app.store import database

    return database()


def ensure_usage_indexes() -> None:
    global _ready
    if _ready:
        return
    _db()["usage_daily"].create_index(
        [("workspace_type", 1), ("workspace_id", 1), ("day", 1)],
        unique=True,
        name="workspace_day",
    )
    _ready = True


def account_doc(user_id: str) -> dict | None:
    try:
        oid = ObjectId(user_id)
    except (InvalidId, TypeError):
        return None
    return _db()["users"].find_one({"_id": oid})


def plan_for_user(user_id: str) -> str | None:
    """None means the id is not an account, as with a local stdio server."""
    doc = account_doc(user_id) if user_id else None
    if not doc:
        return None
    return effective_plan(doc)


def team_state(team_id: str) -> TeamState:
    from app.users import team_owner

    owner = team_owner(team_id)
    if not owner:
        return TeamState(team_id, "", "free", False, "That team no longer exists.")
    plan = plan_for_user(owner) or "free"
    if includes(plan, "team"):
        return TeamState(team_id, owner, plan, True, "")
    return TeamState(
        team_id,
        owner,
        plan,
        False,
        "Shared team memory needs an active Enterprise plan on the team owner's account.",
    )


def retention_epoch() -> datetime:
    """The moment retention started. Older data is treated as written then."""
    global _epoch
    if _epoch is not None:
        return _epoch
    with _epoch_lock:
        if _epoch is not None:
            return _epoch
        settings = _db()["settings"]
        try:
            doc = settings.find_one_and_update(
                {"_id": "retention_epoch"},
                {"$setOnInsert": {"at": datetime.now(timezone.utc)}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            doc = settings.find_one({"_id": "retention_epoch"})
        _epoch = aware((doc or {}).get("at")) or datetime.now(timezone.utc)
    return _epoch


def effective_cutoff(plan: str, now: datetime | None = None) -> datetime | None:
    return clamp_to_epoch(retention_cutoff(plan, now), retention_epoch())


def owner_window(owner_type: str, owner_id: str) -> tuple[datetime | None, int | None]:
    """The retention cutoff for one owner, and how many days its plan keeps."""
    if owner_type == "team":
        plan = team_state(owner_id).owner_plan
    else:
        plan = plan_for_user(owner_id)
        if plan is None:
            return None, None
    return effective_cutoff(plan), retention_days(plan)


def cutoff_for_owner(owner_type: str, owner_id: str) -> datetime | None:
    return owner_window(owner_type, owner_id)[0]


def expires_at(retain_from, days: int | None) -> datetime | None:
    start = aware(retain_from)
    if days is None or start is None:
        return None
    return max(start, retention_epoch()) + timedelta(days=days)


def workspace_access(actor_user_id: str, owner_type: str, owner_id: str) -> Access:
    if owner_type == "team":
        state = team_state(owner_id)
        if not state.active:
            return Access(False, state.reason)
        return Access(
            True,
            plan=state.owner_plan,
            retain_after=effective_cutoff(state.owner_plan),
            limit=fetch_limit(state.owner_plan),
            meter=("team", owner_id),
        )
    plan = plan_for_user(actor_user_id)
    if plan is None:
        return Access(True)
    return Access(
        True,
        plan=plan,
        retain_after=effective_cutoff(plan),
        limit=fetch_limit(plan),
        meter=("user", actor_user_id),
    )


def limit_message(access: Access) -> str:
    return (
        f"Free includes {access.limit} memory fetches a day, and today's are used. "
        "The count resets at 00:00 UTC. Pro has no daily cap."
    )


def reserve_fetch(access: Access) -> Reservation | None:
    """Hold one fetch before the search runs. None means the daily limit is reached."""
    if access.meter is None:
        return Reservation(None, "")
    ensure_usage_indexes()
    day = _today()
    kind, owner = access.meter
    col = _db()["usage_daily"]
    query = {"workspace_type": kind, "workspace_id": owner, "day": day}
    if access.limit is None:
        try:
            col.update_one(query, {"$inc": {"fetches": 1}}, upsert=True)
        except DuplicateKeyError:
            col.update_one(query, {"$inc": {"fetches": 1}})
        return Reservation(access.meter, day)
    if access.limit <= 0:
        return None
    for _attempt in range(2):
        held = col.find_one_and_update(
            {**query, "fetches": {"$lt": access.limit}},
            {"$inc": {"fetches": 1}},
        )
        if held is not None:
            return Reservation(access.meter, day)
        try:
            col.insert_one({**query, "fetches": 1})
            return Reservation(access.meter, day)
        except DuplicateKeyError:
            continue
    return None


def release_fetch(reservation: Reservation | None) -> None:
    """Give a held fetch back when the search did not run."""
    if reservation is None or reservation.meter is None:
        return
    kind, owner = reservation.meter
    _db()["usage_daily"].update_one(
        {"workspace_type": kind, "workspace_id": owner, "day": reservation.day, "fetches": {"$gt": 0}},
        {"$inc": {"fetches": -1}},
    )


def fetches_today(kind: str, owner: str) -> int:
    doc = _db()["usage_daily"].find_one(
        {"workspace_type": kind, "workspace_id": owner, "day": _today()},
        {"fetches": 1},
    )
    try:
        return int((doc or {}).get("fetches") or 0)
    except (TypeError, ValueError):
        return 0


def check_team_create(user_id: str) -> None:
    plan = plan_for_user(user_id) or "free"
    if not includes(plan, "team"):
        raise AccessError(402, "Shared team memory is part of Enterprise. Upgrade on the Plan tab to create a team.")
    allowed = PLANS[plan]["max_teams"]
    owned = _db()["teams"].count_documents({"created_by": user_id})
    if owned >= allowed:
        raise AccessError(409, f"Enterprise includes {allowed} teams, and this account already owns {owned}.")


def check_team_join(user_id: str, code: str) -> None:
    cleaned = "".join(code.split()).upper()
    team = _db()["teams"].find_one({"join_code": cleaned}, {"_id": 1}) if cleaned else None
    if not team:
        return
    team_id = str(team["_id"])
    members = _db()["team_members"]
    if members.find_one({"team_id": team_id, "user_id": user_id}, {"_id": 1}):
        return
    state = team_state(team_id)
    if not state.active:
        raise AccessError(402, "This team's Enterprise plan is not active, so it cannot take new members.")
    seats = PLANS[state.owner_plan]["team_seats"]
    if members.count_documents({"team_id": team_id}) >= seats:
        raise AccessError(409, f"This team is full. Its plan includes {seats} members.")


def check_team_workspace(team_id: str) -> None:
    state = team_state(team_id)
    if not state.active:
        raise AccessError(402, state.reason)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()
