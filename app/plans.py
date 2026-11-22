"""Plans, the products each one opens, and their limits. Prices are monthly amounts in US cents.

Everything here is pure. Account state comes in as the Mongo user document.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

GRACE_DAYS = 7
STALE_DAYS = 7
LIVE_STATUSES = frozenset({"active", "trialing"})

PRODUCTS: dict[str, dict] = {
    "personal": {
        "id": "personal",
        "name": "Personal AI memory",
        "summary": "Capture from Cursor, Claude Code, and Codex. Your agents recall it through MCP.",
        "available": True,
    },
    "team": {
        "id": "team",
        "name": "Shared team memory",
        "summary": "Team workspaces, join codes, and team keys that never read personal memory.",
        "available": True,
    },
    "apps": {
        "id": "apps",
        "name": "App memory",
        "summary": "Connectors for everyday apps such as Spotify and Zepto.",
        "available": False,
    },
}

PLANS: dict[str, dict] = {
    "free": {
        "id": "free",
        "name": "Free",
        "rank": 0,
        "price_cents": 0,
        "price_label": "$0",
        "period": "forever",
        "products": ["personal", "apps"],
        "retention_days": 15,
        "retention_label": "15 days",
        "fetches_per_day": 100,
        "fetch_label": "100 memory fetches a day",
        "max_teams": 0,
        "team_seats": 0,
        "priority_support": False,
        "points": [
            "Personal AI memory",
            "App memory when it ships",
            "Memories kept for 15 days",
            "100 memory fetches a day",
        ],
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "rank": 1,
        "price_cents": 1900,
        "price_label": "$19",
        "period": "per month",
        "products": ["personal", "apps"],
        "retention_days": 183,
        "retention_label": "6 months",
        "fetches_per_day": None,
        "fetch_label": "Unlimited memory fetches",
        "max_teams": 0,
        "team_seats": 0,
        "priority_support": False,
        "points": [
            "Personal AI memory",
            "App memory when it ships",
            "Memories kept for 6 months",
            "Unlimited memory fetches",
        ],
    },
    "enterprise": {
        "id": "enterprise",
        "name": "Enterprise",
        "rank": 2,
        "price_cents": 9900,
        "price_label": "$99",
        "period": "per month",
        "products": ["team", "personal", "apps"],
        "retention_days": None,
        "retention_label": "Until you delete them",
        "fetches_per_day": None,
        "fetch_label": "Unlimited memory fetches",
        "max_teams": 5,
        "team_seats": 25,
        "priority_support": True,
        "points": [
            "Shared team memory: 5 teams, 25 members each",
            "Everything in Pro for your own account",
            "Memories kept until you delete them",
            "Unlimited memory fetches",
            "Priority support requests from the console",
        ],
    },
}


def normalize_plan(value: object) -> str:
    key = str(value or "").strip().lower()
    return key if key in PLANS else "free"


def rank(plan: str) -> int:
    return PLANS[normalize_plan(plan)]["rank"]


def includes(plan: str, product: str) -> bool:
    return product in PLANS[normalize_plan(plan)]["products"]


def fetch_limit(plan: str) -> int | None:
    return PLANS[normalize_plan(plan)]["fetches_per_day"]


def retention_days(plan: str) -> int | None:
    return PLANS[normalize_plan(plan)]["retention_days"]


def retention_cutoff(plan: str, now: datetime | None = None) -> datetime | None:
    """Memories older than this are outside the plan. None means keep them."""
    days = retention_days(plan)
    if days is None:
        return None
    return _now(now) - timedelta(days=days)


def clamp_to_epoch(cutoff: datetime | None, epoch: datetime | None) -> datetime | None:
    """Data written before retention started counts as written at the start."""
    if cutoff is None or epoch is None:
        return cutoff
    return cutoff if cutoff > epoch else None


def retention_shrank(before: str, after: str) -> bool:
    old = retention_days(before)
    new = retention_days(after)
    if new is None:
        return False
    return old is None or new < old


def granted_plan(doc: dict, now: datetime | None = None) -> str | None:
    """A plan Memplug gave this account without Stripe, while it lasts."""
    grant = doc.get("plan_grant") if isinstance(doc, dict) else None
    if not isinstance(grant, dict):
        return None
    plan = normalize_plan(grant.get("plan"))
    if plan == "free":
        return None
    until = aware(grant.get("until"))
    if until is not None and until <= _now(now):
        return None
    return plan


def paid_plan(doc: dict, now: datetime | None = None) -> str:
    """The plan the Stripe subscription currently pays for."""
    if not isinstance(doc, dict):
        return "free"
    plan = normalize_plan(doc.get("plan"))
    if plan == "free":
        return "free"
    moment = _now(now)
    status = str(doc.get("plan_status") or "")
    period_end = aware(doc.get("plan_period_end"))
    if period_end is not None and moment > period_end + timedelta(days=STALE_DAYS):
        return "free"
    if status in LIVE_STATUSES:
        return plan
    if status == "past_due":
        grace = aware(doc.get("plan_grace_until"))
        if grace is not None and grace > moment:
            return plan
    return "free"


def effective_plan(doc: dict | None, now: datetime | None = None) -> str:
    if not isinstance(doc, dict):
        return "free"
    best = paid_plan(doc, now)
    granted = granted_plan(doc, now)
    if granted is not None and rank(granted) > rank(best):
        best = granted
    return best


def products_for(plan: str) -> list[dict]:
    included = set(PLANS[normalize_plan(plan)]["products"])
    return [
        {**product, "included": product["id"] in included}
        for product in PRODUCTS.values()
    ]


def plan_catalog() -> list[dict]:
    catalog = []
    for plan in PLANS.values():
        item = {key: value for key, value in plan.items() if key != "products"}
        item["products"] = [
            {"id": key, "name": PRODUCTS[key]["name"], "available": PRODUCTS[key]["available"]}
            for key in plan["products"]
        ]
        catalog.append(item)
    return catalog


def aware(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _now(now: datetime | None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)
