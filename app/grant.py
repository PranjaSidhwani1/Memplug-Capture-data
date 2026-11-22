"""Give an account a plan without Stripe, or take it back.

    python -m app.grant someone@example.com enterprise
    python -m app.grant someone@example.com pro --days 30 --note "design partner"
    python -m app.grant someone@example.com clear

A grant sits beside any Stripe subscription. The account gets whichever plan is higher.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from app.plans import PLANS
from app.store import database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.grant", description="Give or remove a plan without Stripe.")
    parser.add_argument("email")
    parser.add_argument("plan", choices=["pro", "enterprise", "clear"])
    parser.add_argument("--days", type=int, default=0, help="How long the grant lasts. Leave it out to keep the grant until you clear it.")
    parser.add_argument("--note", default="", help="Why the grant exists, for your own records.")
    args = parser.parse_args(argv)

    users = database()["users"]
    email = args.email.strip().lower()
    doc = users.find_one({"email": email}, {"_id": 1})
    if not doc:
        print(f"No account uses {email}.", file=sys.stderr)
        return 1
    if args.plan == "clear":
        users.update_one({"_id": doc["_id"]}, {"$unset": {"plan_grant": ""}})
        print(f"Removed the granted plan from {email}. The hourly purge applies the smaller retention.")
        return 0
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=args.days) if args.days > 0 else None
    grant = {"plan": args.plan, "until": until, "note": args.note.strip(), "granted_at": now}
    users.update_one({"_id": doc["_id"]}, {"$set": {"plan_grant": grant}})
    ending = f"until {until.date().isoformat()}" if until else "until you clear it"
    print(f"{email} now has {PLANS[args.plan]['name']} {ending}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
