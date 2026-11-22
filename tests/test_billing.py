"""How Stripe subscriptions map onto Memplug plans. No network calls."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from app.billing import (
    choose_subscription,
    no_subscription_fields,
    plan_for_price,
    subscription_fields,
    subscription_plan,
)

NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
CLEAN_ENV = {"STRIPE_PRICE_PRO": "", "STRIPE_PRICE_ENTERPRISE": ""}


def sub(sub_id, status, lookup, created=0, **extra):
    period_end = int((NOW + timedelta(days=20)).timestamp())
    return {
        "id": sub_id,
        "status": status,
        "created": created,
        "items": {"data": [{"id": f"si_{sub_id}", "current_period_end": period_end, "price": {"id": f"price_{lookup}", "lookup_key": lookup}}]},
        **extra,
    }


@mock.patch.dict(os.environ, CLEAN_ENV)
class PriceTests(unittest.TestCase):
    def test_lookup_keys(self):
        self.assertEqual(plan_for_price({"id": "price_1", "lookup_key": "memplug_pro_monthly"}), "pro")
        self.assertEqual(plan_for_price({"id": "price_2", "lookup_key": "memplug_enterprise_monthly"}), "enterprise")

    def test_metadata_and_product(self):
        self.assertEqual(plan_for_price({"id": "price_3", "metadata": {"memplug_plan": "enterprise"}}), "enterprise")
        self.assertEqual(plan_for_price({"id": "price_4", "product": "memplug_pro"}), "pro")
        self.assertEqual(plan_for_price({"id": "price_5", "product": {"id": "memplug_enterprise"}}), "enterprise")

    def test_unknown_price(self):
        self.assertIsNone(plan_for_price({"id": "price_6", "product": "prod_other"}))
        self.assertIsNone(plan_for_price(None))

    def test_configured_price(self):
        with mock.patch.dict(os.environ, {"STRIPE_PRICE_ENTERPRISE": "price_custom"}):
            self.assertEqual(plan_for_price("price_custom"), "enterprise")

    def test_subscription_takes_highest_item(self):
        both = sub("a", "active", "memplug_pro_monthly")
        both["items"]["data"].append({"id": "si_b", "price": {"id": "p", "lookup_key": "memplug_enterprise_monthly"}})
        self.assertEqual(subscription_plan(both), "enterprise")


@mock.patch.dict(os.environ, CLEAN_ENV)
class ChooseTests(unittest.TestCase):
    def test_duplicates_are_returned_for_cancel(self):
        pro = sub("pro", "active", "memplug_pro_monthly", created=1)
        ent = sub("ent", "active", "memplug_enterprise_monthly", created=2)
        old = sub("old", "canceled", "memplug_enterprise_monthly", created=0)
        chosen, plan, extra = choose_subscription([pro, ent, old], "pro")
        self.assertEqual((chosen["id"], plan), ("ent", "enterprise"))
        self.assertEqual([item["id"] for item in extra], ["pro"])

    def test_paid_beats_past_due(self):
        late = sub("late", "past_due", "memplug_enterprise_monthly", created=5)
        paid = sub("paid", "active", "memplug_pro_monthly", created=1)
        chosen, plan, _extra = choose_subscription([late, paid], "")
        self.assertEqual((chosen["id"], plan), ("paid", "pro"))

    def test_same_plan_keeps_current(self):
        first = sub("first", "active", "memplug_pro_monthly", created=1)
        second = sub("second", "active", "memplug_pro_monthly", created=2)
        chosen, _plan, extra = choose_subscription([first, second], "first")
        self.assertEqual(chosen["id"], "first")
        self.assertEqual([item["id"] for item in extra], ["second"])

    def test_nothing_live(self):
        for status in ("incomplete", "incomplete_expired", "canceled", "unpaid", "paused"):
            chosen, plan, extra = choose_subscription([sub("x", status, "memplug_pro_monthly")], "")
            self.assertIsNone(chosen, status)
            self.assertIsNone(plan)
            self.assertEqual(extra, [])


@mock.patch.dict(os.environ, CLEAN_ENV)
class FieldTests(unittest.TestCase):
    def test_period_end_and_cancel(self):
        item = sub("a", "active", "memplug_pro_monthly", cancel_at_period_end=True)
        fields = subscription_fields(item, "pro", {}, NOW)
        self.assertEqual(fields["plan"], "pro")
        self.assertEqual(fields["plan_status"], "active")
        self.assertEqual(fields["plan_period_end"], NOW + timedelta(days=20))
        self.assertEqual(fields["plan_cancel_at"], fields["plan_period_end"])
        self.assertIsNone(fields["plan_grace_until"])
        self.assertEqual(fields["stripe_subscription_id"], "a")

    def test_grace_starts_once(self):
        item = sub("a", "past_due", "memplug_pro_monthly")
        first = subscription_fields(item, "pro", {}, NOW)
        self.assertEqual(first["plan_grace_until"], NOW + timedelta(days=7))
        previous = {"plan_status": "past_due", "stripe_subscription_id": "a", "plan_grace_until": first["plan_grace_until"]}
        again = subscription_fields(item, "pro", previous, NOW + timedelta(days=3))
        self.assertEqual(again["plan_grace_until"], first["plan_grace_until"])

    def test_pending_update(self):
        item = sub("a", "active", "memplug_pro_monthly", pending_update={"expires_at": 1})
        self.assertTrue(subscription_fields(item, "pro", {}, NOW)["plan_pending_change"])

    def test_no_subscription(self):
        fields = no_subscription_fields([sub("a", "canceled", "memplug_pro_monthly", created=1), sub("b", "incomplete_expired", "memplug_pro_monthly", created=3)])
        self.assertEqual(fields["plan"], "free")
        self.assertEqual(fields["plan_status"], "incomplete_expired")
        self.assertEqual(fields["stripe_subscription_id"], "")
        self.assertEqual(no_subscription_fields([])["plan_status"], "none")


if __name__ == "__main__":
    unittest.main()
