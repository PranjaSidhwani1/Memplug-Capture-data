"""Stripe subscriptions. Stripe is the record of what an account pays for, and Memplug copies it.

Every Stripe event, return from checkout, and hourly check runs the same sync. The sync reads
the customer's subscriptions from Stripe, so the order events arrive in does not matter.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from app.access import account_doc, fetches_today, retention_epoch, team_state
from app.config import stripe_secret, stripe_webhook_secret
from app.plans import (
    GRACE_DAYS,
    PLANS,
    aware,
    effective_plan,
    granted_plan,
    normalize_plan,
    plan_catalog,
    products_for,
    rank,
    retention_shrank,
)

log = logging.getLogger("memplug.billing")

LIVE = frozenset({"active", "trialing", "past_due"})
LOOKUP_KEYS = {"pro": "memplug_pro_monthly", "enterprise": "memplug_enterprise_monthly"}
PRODUCT_IDS = {"pro": "memplug_pro", "enterprise": "memplug_enterprise"}
EVENTS = frozenset(
    {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
        "checkout.session.async_payment_failed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
        "invoice.paid",
        "invoice.payment_failed",
        "invoice.payment_action_required",
    }
)

_prices: dict[str, str] = {}
_price_lock = threading.Lock()
_ready = False


class BillingError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _db():
    from app.store import database

    return database()


def _users():
    return _db()["users"]


def ensure_billing_indexes() -> None:
    global _ready
    if _ready:
        return
    db = _db()
    db["stripe_events"].create_index("event_id", unique=True)
    db["users"].create_index("stripe_customer_id")
    _ready = True


def payments_ready() -> bool:
    return bool(stripe_secret())


def _stripe():
    secret = stripe_secret()
    if not secret:
        raise BillingError(503, "Card payments are not set up yet. The server needs STRIPE_SECRET_KEY.")
    import stripe

    stripe.api_key = secret
    stripe.max_network_retries = 2
    return stripe


def _call(action: str, fn, *args, **kwargs):
    import stripe

    try:
        return fn(*args, **kwargs)
    except stripe.CardError as exc:
        raise BillingError(402, exc.user_message or "The card was declined.") from exc
    except stripe.StripeError as exc:
        log.warning("stripe %s failed: %s", action, exc)
        detail = getattr(exc, "user_message", None) or "Stripe could not finish that. Try again in a minute."
        raise BillingError(502, detail) from exc


def _missing(exc) -> bool:
    return getattr(exc, "code", "") == "resource_missing"


# Prices


def _configured_price(plan: str) -> str:
    return os.environ.get(f"STRIPE_PRICE_{plan.upper()}", "").strip()


def price_for(stripe, plan: str) -> str:
    """One stable monthly Price per plan. Found by lookup key, created once if missing."""
    cached = _prices.get(plan)
    if cached:
        return cached
    with _price_lock:
        if plan in _prices:
            return _prices[plan]
        configured = _configured_price(plan)
        if configured:
            _prices[plan] = configured
            return configured
        spec = PLANS[plan]
        listed = _call("list prices", stripe.Price.list, lookup_keys=[LOOKUP_KEYS[plan]], active=True, limit=1)
        for price in listed.get("data") or []:
            recurring = price.get("recurring") or {}
            if (
                price.get("unit_amount") == spec["price_cents"]
                and price.get("currency") == "usd"
                and recurring.get("interval") == "month"
            ):
                _prices[plan] = price["id"]
                return price["id"]
        product = _product_for(stripe, plan)
        price = _call(
            "create price",
            stripe.Price.create,
            product=product,
            currency="usd",
            unit_amount=spec["price_cents"],
            recurring={"interval": "month"},
            lookup_key=LOOKUP_KEYS[plan],
            transfer_lookup_key=True,
            nickname=f"Memplug {spec['name']} monthly",
            metadata={"memplug_plan": plan},
            idempotency_key=f"memplug-price-{plan}-{spec['price_cents']}",
        )
        _prices[plan] = price["id"]
        return price["id"]


def _product_for(stripe, plan: str) -> str:
    product_id = PRODUCT_IDS[plan]
    try:
        stripe.Product.retrieve(product_id)
        return product_id
    except stripe.StripeError as exc:
        if not _missing(exc):
            raise BillingError(502, "Stripe could not finish that. Try again in a minute.") from exc
    try:
        stripe.Product.create(
            id=product_id,
            name=f"Memplug {PLANS[plan]['name']}",
            metadata={"memplug_plan": plan},
        )
    except stripe.StripeError as exc:
        if getattr(exc, "code", "") != "resource_already_exists":
            raise BillingError(502, "Stripe could not finish that. Try again in a minute.") from exc
    return product_id


def plan_for_price(price) -> str | None:
    if not price:
        return None
    if isinstance(price, str):
        price_id = price
        price = {"id": price_id}
    price_id = str(price.get("id") or "")
    for plan in ("enterprise", "pro"):
        configured = _configured_price(plan)
        if configured and configured == price_id:
            return plan
    lookup = price.get("lookup_key") or ""
    for plan, key in LOOKUP_KEYS.items():
        if lookup == key:
            return plan
    tagged = normalize_plan((price.get("metadata") or {}).get("memplug_plan"))
    if tagged != "free":
        return tagged
    product = price.get("product")
    product_id = product if isinstance(product, str) else str((product or {}).get("id") or "")
    for plan, known in PRODUCT_IDS.items():
        if product_id == known:
            return plan
    return None


def subscription_plan(subscription) -> str | None:
    items = (subscription.get("items") or {}).get("data") or []
    best = None
    for item in items:
        plan = plan_for_price(item.get("price"))
        if plan and (best is None or rank(plan) > rank(best)):
            best = plan
    if best is None:
        tagged = normalize_plan((subscription.get("metadata") or {}).get("plan"))
        best = tagged if tagged != "free" else None
    return best


# Sync


def choose_subscription(subscriptions: list, current_id: str):
    """The subscription that decides the plan, and any extra live ones to cancel."""
    live = []
    for subscription in subscriptions:
        plan = subscription_plan(subscription)
        if plan and subscription.get("status") in LIVE:
            live.append((subscription, plan))
    if not live:
        return None, None, []

    def weight(pair):
        subscription, plan = pair
        return (
            subscription.get("status") != "past_due",
            rank(plan),
            subscription.get("id") == current_id,
            subscription.get("created") or 0,
        )

    live.sort(key=weight, reverse=True)
    chosen, plan = live[0]
    return chosen, plan, [subscription for subscription, _plan in live[1:]]


def subscription_fields(subscription, plan: str, previous: dict, now: datetime) -> dict:
    status = str(subscription.get("status") or "")
    items = (subscription.get("items") or {}).get("data") or []
    period_end = _from_unix(subscription.get("current_period_end"))
    if period_end is None and items:
        period_end = _from_unix(items[0].get("current_period_end"))
    cancel_at = _from_unix(subscription.get("cancel_at"))
    if cancel_at is None and subscription.get("cancel_at_period_end"):
        cancel_at = period_end
    grace = None
    if status == "past_due":
        kept = aware(previous.get("plan_grace_until"))
        same = str(previous.get("stripe_subscription_id") or "") == str(subscription.get("id") or "")
        if previous.get("plan_status") == "past_due" and same and kept is not None:
            grace = kept
        else:
            grace = now + timedelta(days=GRACE_DAYS)
    return {
        "plan": plan,
        "plan_status": status,
        "plan_period_end": period_end,
        "plan_cancel_at": cancel_at,
        "plan_grace_until": grace,
        "plan_pending_change": bool(subscription.get("pending_update")),
        "stripe_subscription_id": str(subscription.get("id") or ""),
    }


def no_subscription_fields(subscriptions: list) -> dict:
    latest = max(subscriptions, key=lambda item: item.get("created") or 0) if subscriptions else None
    return {
        "plan": "free",
        "plan_status": str(latest.get("status") or "none") if latest else "none",
        "plan_period_end": None,
        "plan_cancel_at": None,
        "plan_grace_until": None,
        "plan_pending_change": False,
        "stripe_subscription_id": "",
    }


def sync_account(user_id: str) -> dict | None:
    """Copy the customer's subscriptions from Stripe. The newest sync to start wins the write."""
    doc = account_doc(user_id)
    if not doc:
        return None
    customer = str(doc.get("stripe_customer_id") or "")
    if not customer:
        return doc
    stripe = _stripe()
    seq = time.time_ns()
    _users().update_one({"_id": doc["_id"]}, {"$max": {"billing_sync_seq": seq}})
    listed = _call("list subscriptions", stripe.Subscription.list, customer=customer, status="all", limit=100)
    subscriptions = list(listed.get("data") or [])
    chosen, plan, extra = choose_subscription(subscriptions, str(doc.get("stripe_subscription_id") or ""))
    for duplicate in extra:
        try:
            stripe.Subscription.cancel(duplicate["id"], prorate=True, invoice_now=True)
            log.warning("canceled duplicate subscription user=%s subscription=%s", user_id, duplicate["id"])
        except stripe.StripeError:
            log.exception("duplicate subscription was not canceled user=%s", user_id)
    now = datetime.now(timezone.utc)
    if chosen is not None:
        fields = subscription_fields(chosen, plan, doc, now)
    else:
        fields = no_subscription_fields(subscriptions)
    fields["billing_synced_at"] = now
    before = effective_plan(doc, now)
    result = _users().update_one({"_id": doc["_id"], "billing_sync_seq": seq}, {"$set": fields})
    updated = account_doc(user_id) or doc
    if result.matched_count == 0:
        return updated
    after = effective_plan(updated, now)
    if before != after:
        log.info("plan changed user=%s from=%s to=%s", user_id, before, after)
    if retention_shrank(before, after):
        from app.retention import purge_user

        purge_user(user_id)
    return updated


def reconcile_accounts(limit: int = 200) -> None:
    """Hourly. Re-read accounts whose renewal is due or whose payment is unsettled."""
    if not stripe_secret():
        return
    now = datetime.now(timezone.utc)
    paid = ["pro", "enterprise"]
    query = {
        "stripe_customer_id": {"$nin": ["", None]},
        "$or": [
            {"plan": {"$in": paid}, "plan_period_end": {"$lt": now}},
            {"plan_status": {"$in": ["past_due", "incomplete", "unpaid", "paused"]}},
            {"plan": {"$in": paid}, "billing_synced_at": {"$lt": now - timedelta(days=1)}},
            {"plan": {"$in": paid}, "billing_synced_at": {"$exists": False}},
        ],
    }
    for doc in _users().find(query, {"_id": 1}).limit(limit):
        try:
            sync_account(str(doc["_id"]))
        except Exception:
            log.exception("billing sync failed user=%s", doc["_id"])


# Account actions


def _has_live(doc: dict) -> bool:
    return (
        normalize_plan(doc.get("plan")) != "free"
        and str(doc.get("plan_status") or "") in LIVE
        and bool(doc.get("stripe_subscription_id"))
    )


def _ensure_customer(stripe, doc: dict) -> str:
    existing = str(doc.get("stripe_customer_id") or "")
    if existing:
        return existing
    user_id = str(doc["_id"])
    customer = _call(
        "create customer",
        stripe.Customer.create,
        email=doc.get("email") or None,
        name=doc.get("name") or None,
        metadata={"memplug_user_id": user_id},
        idempotency_key=f"memplug-customer-{user_id}",
    )
    result = _users().update_one(
        {"_id": doc["_id"], "stripe_customer_id": {"$in": ["", None]}},
        {"$set": {"stripe_customer_id": customer["id"]}},
    )
    if result.matched_count == 0:
        fresh = _users().find_one({"_id": doc["_id"]}, {"stripe_customer_id": 1}) or {}
        return str(fresh.get("stripe_customer_id") or customer["id"])
    return customer["id"]


def _adopt_customer(user_id: str, customer_id: str) -> None:
    doc = account_doc(user_id)
    if not doc or not customer_id:
        return
    current = str(doc.get("stripe_customer_id") or "")
    if current == customer_id:
        return
    if current:
        log.warning("stripe customer mismatch user=%s stored=%s event=%s", user_id, current, customer_id)
        return
    _users().update_one(
        {"_id": doc["_id"], "stripe_customer_id": {"$in": ["", None]}},
        {"$set": {"stripe_customer_id": customer_id}},
    )


def _retire_checkout(stripe, doc: dict) -> bool:
    """Expire the account's last open checkout. True when that checkout was just paid."""
    session_id = str(doc.get("checkout_session_id") or "")
    if not session_id:
        return False
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.StripeError:
        return False
    if session.get("status") == "open":
        try:
            stripe.checkout.Session.expire(session_id)
            return False
        except stripe.StripeError:
            try:
                session = stripe.checkout.Session.retrieve(session_id)
            except stripe.StripeError:
                return False
    if session.get("status") != "complete":
        return False
    if session.get("payment_status") == "unpaid":
        raise BillingError(409, "Stripe is still confirming your last payment. Try again in a few minutes.")
    return bool(session.get("subscription"))


def start_checkout(user_id: str, plan: str, return_base: str) -> dict:
    chosen = normalize_plan(plan)
    if chosen == "free":
        raise BillingError(400, "Choose Pro or Enterprise.")
    doc = account_doc(user_id)
    if not doc:
        raise BillingError(401, "Sign in again.")
    granted = granted_plan(doc)
    if granted is not None and rank(granted) >= rank(chosen):
        raise BillingError(409, f"{PLANS[granted]['name']} is already on this account through Memplug.")
    stripe = _stripe()
    ensure_billing_indexes()
    customer = _ensure_customer(stripe, doc)
    doc = sync_account(user_id) or doc
    if _has_live(doc):
        return _change_or_resume(stripe, doc, chosen)
    if _retire_checkout(stripe, doc):
        doc = sync_account(user_id) or doc
        if _has_live(doc):
            return _change_or_resume(stripe, doc, chosen)
    price = price_for(stripe, chosen)
    session = _call(
        "create checkout",
        stripe.checkout.Session.create,
        mode="subscription",
        customer=customer,
        client_reference_id=user_id,
        line_items=[{"price": price, "quantity": 1}],
        success_url=f"{return_base}/?billing=success&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{return_base}/?billing=cancel",
        metadata={"user_id": user_id, "plan": chosen},
        subscription_data={"metadata": {"user_id": user_id, "plan": chosen}},
        allow_promotion_codes=True,
    )
    _users().update_one({"_id": doc["_id"]}, {"$set": {"checkout_session_id": session["id"]}})
    if not session.get("url"):
        raise BillingError(502, "Stripe did not return a checkout page.")
    return {"status": "checkout", "url": session["url"]}


def _change_or_resume(stripe, doc: dict, chosen: str) -> dict:
    current = normalize_plan(doc.get("plan"))
    if current != chosen:
        return _change_plan(stripe, doc, chosen)
    if doc.get("plan_cancel_at"):
        _call("resume subscription", stripe.Subscription.modify, doc["stripe_subscription_id"], cancel_at_period_end=False)
        sync_account(str(doc["_id"]))
        return {"status": "resumed"}
    raise BillingError(409, f"You are already on {PLANS[chosen]['name']}.")


def _change_plan(stripe, doc: dict, chosen: str) -> dict:
    user_id = str(doc["_id"])
    subscription_id = str(doc["stripe_subscription_id"])
    subscription = _call("read subscription", stripe.Subscription.retrieve, subscription_id)
    items = (subscription.get("items") or {}).get("data") or []
    if not items:
        raise BillingError(502, "The Stripe subscription has no price to change.")
    if subscription.get("cancel_at_period_end"):
        _call("resume subscription", stripe.Subscription.modify, subscription_id, cancel_at_period_end=False)
    price = price_for(stripe, chosen)
    swap = [{"id": items[0]["id"], "price": price}]
    if rank(chosen) > rank(normalize_plan(doc.get("plan"))):
        updated = _call(
            "upgrade subscription",
            stripe.Subscription.modify,
            subscription_id,
            items=swap,
            proration_behavior="always_invoice",
            payment_behavior="pending_if_incomplete",
            expand=["latest_invoice"],
        )
    else:
        updated = _call(
            "downgrade subscription",
            stripe.Subscription.modify,
            subscription_id,
            items=swap,
            proration_behavior="create_prorations",
        )
    sync_account(user_id)
    if updated.get("pending_update"):
        invoice = updated.get("latest_invoice")
        url = invoice.get("hosted_invoice_url") if hasattr(invoice, "get") else ""
        return {"status": "action_required", "url": url or ""}
    return {"status": "changed"}


def cancel_plan(user_id: str) -> None:
    """Stop renewing. The plan stays until the paid period ends, as in the Stripe portal."""
    doc = account_doc(user_id)
    if not doc:
        raise BillingError(401, "Sign in again.")
    subscription_id = str(doc.get("stripe_subscription_id") or "")
    if not subscription_id:
        if granted_plan(doc) is not None:
            raise BillingError(409, "This plan was granted by Memplug. Send a support request to change it.")
        raise BillingError(409, "This account is on Free already.")
    stripe = _stripe()
    try:
        stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
    except stripe.StripeError as exc:
        if not _missing(exc):
            raise BillingError(502, getattr(exc, "user_message", None) or "Stripe could not cancel the plan. Try again in a minute.") from exc
    sync_account(user_id)


def resume_plan(user_id: str) -> None:
    doc = account_doc(user_id)
    if not doc or not doc.get("stripe_subscription_id"):
        raise BillingError(409, "There is no subscription to resume.")
    stripe = _stripe()
    _call("resume subscription", stripe.Subscription.modify, doc["stripe_subscription_id"], cancel_at_period_end=False)
    sync_account(user_id)


def start_portal(user_id: str, return_base: str) -> str:
    doc = account_doc(user_id) or {}
    customer = str(doc.get("stripe_customer_id") or "")
    if not customer:
        raise BillingError(409, "Subscribe before you manage a card.")
    stripe = _stripe()
    session = _call(
        "open portal",
        stripe.billing_portal.Session.create,
        customer=customer,
        return_url=f"{return_base}/?billing=return",
    )
    return session["url"]


def confirm_checkout(user_id: str, session_id: str) -> None:
    """Read a finished checkout directly, so the page does not wait on the webhook."""
    stripe = _stripe()
    session = _call("read checkout", stripe.checkout.Session.retrieve, session_id)
    owner = str(session.get("client_reference_id") or (session.get("metadata") or {}).get("user_id") or "")
    if owner != user_id:
        raise BillingError(404, "That checkout belongs to another account.")
    customer = session.get("customer")
    _adopt_customer(user_id, customer if isinstance(customer, str) else str((customer or {}).get("id") or ""))
    sync_account(user_id)


def apply_stripe_event(payload: bytes, signature: str) -> None:
    secret = stripe_secret()
    webhook_secret = stripe_webhook_secret()
    if not secret or not webhook_secret:
        raise BillingError(503, "Stripe webhooks are not configured.")
    stripe = _stripe()
    try:
        event = stripe.Webhook.construct_event(payload, signature, webhook_secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise BillingError(400, "Stripe signature was rejected.") from exc
    ensure_billing_indexes()
    events = _db()["stripe_events"]
    event_id = str(event.get("id") or "")
    if event_id and events.find_one({"event_id": event_id}, {"_id": 1}):
        return
    kind = str(event.get("type") or "")
    if kind in EVENTS:
        target = (event.get("data") or {}).get("object") or {}
        user_id = _user_for_event(kind, target)
        if user_id:
            sync_account(user_id)
        else:
            log.info("stripe event has no Memplug account type=%s id=%s", kind, event_id)
    if event_id:
        try:
            events.insert_one({"event_id": event_id, "type": kind, "received_at": datetime.now(timezone.utc)})
        except DuplicateKeyError:
            pass


def _user_for_event(kind: str, target) -> str:
    customer = target.get("customer")
    customer_id = customer if isinstance(customer, str) else str((customer or {}).get("id") or "")
    meta = target.get("metadata") or {}
    named = str(meta.get("user_id") or target.get("client_reference_id") or "")
    if kind.startswith("checkout.session") and named and account_doc(named):
        _adopt_customer(named, customer_id)
        return named
    if customer_id:
        doc = _users().find_one({"stripe_customer_id": customer_id}, {"_id": 1})
        if doc:
            return str(doc["_id"])
    if named and account_doc(named):
        _adopt_customer(named, customer_id)
        return named
    return ""


# Account page


def account_view(user_id: str) -> dict:
    from app.users import list_teams

    doc = account_doc(user_id) or {}
    now = datetime.now(timezone.utc)
    plan = effective_plan(doc, now)
    spec = PLANS[plan]
    subscription = None
    if doc.get("stripe_subscription_id"):
        subscription = {
            "plan": normalize_plan(doc.get("plan")),
            "status": str(doc.get("plan_status") or ""),
            "period_end": _iso(doc.get("plan_period_end")),
            "cancel_at": _iso(doc.get("plan_cancel_at")),
            "grace_until": _iso(doc.get("plan_grace_until")),
            "pending_change": bool(doc.get("plan_pending_change")),
        }
    grant = None
    granted = granted_plan(doc, now)
    if granted is not None:
        grant = {"plan": granted, "until": _iso((doc.get("plan_grant") or {}).get("until"))}
    teams = []
    for team in list_teams(user_id):
        state = team_state(team["id"])
        teams.append(
            {
                "id": team["id"],
                "name": team["name"],
                "role": team["role"],
                "active": state.active,
                "reason": state.reason,
                "fetches_today": fetches_today("team", team["id"]),
            }
        )
    deletes_from = ""
    if spec["retention_days"] is not None:
        start = retention_epoch() + timedelta(days=spec["retention_days"])
        if start > now:
            deletes_from = _iso(start)
    return {
        "plan": plan,
        "plan_name": spec["name"],
        "retention_days": spec["retention_days"],
        "retention_label": spec["retention_label"],
        "deletes_from": deletes_from,
        "fetches_today": fetches_today("user", user_id),
        "fetch_limit": spec["fetches_per_day"],
        "fetch_label": spec["fetch_label"],
        "subscription": subscription,
        "grant": grant,
        "payments_ready": payments_ready(),
        "can_manage": bool(doc.get("stripe_customer_id")) and payments_ready(),
        "teams": teams,
        "owned_teams": sum(1 for team in teams if team["role"] == "owner"),
        "max_teams": spec["max_teams"],
        "team_seats": spec["team_seats"],
        "priority_support": spec["priority_support"],
        "products": products_for(plan),
        "plans": plan_catalog(),
    }


def _from_unix(value) -> datetime | None:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return None


def _iso(value) -> str:
    moment = aware(value)
    if moment is None:
        return ""
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
