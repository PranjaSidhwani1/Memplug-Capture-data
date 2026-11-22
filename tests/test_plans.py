"""Plans, products, limits, and which plan an account is on."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.plans import (
    clamp_to_epoch,
    effective_plan,
    fetch_limit,
    granted_plan,
    includes,
    normalize_plan,
    plan_catalog,
    products_for,
    retention_cutoff,
    retention_days,
    retention_shrank,
)

NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)


class CatalogTests(unittest.TestCase):
    def test_limits(self):
        self.assertEqual(fetch_limit("free"), 100)
        self.assertIsNone(fetch_limit("pro"))
        self.assertIsNone(fetch_limit("enterprise"))
        self.assertEqual(retention_days("free"), 15)
        self.assertEqual(retention_days("pro"), 183)
        self.assertIsNone(retention_days("enterprise"))
        self.assertEqual(normalize_plan("nope"), "free")
        self.assertEqual(normalize_plan(" PRO "), "pro")

    def test_products(self):
        for plan in ("free", "pro"):
            self.assertTrue(includes(plan, "personal"))
            self.assertTrue(includes(plan, "apps"))
            self.assertFalse(includes(plan, "team"))
        self.assertTrue(includes("enterprise", "team"))
        apps = next(item for item in products_for("free") if item["id"] == "apps")
        self.assertTrue(apps["included"])
        self.assertFalse(apps["available"])

    def test_catalog_shape(self):
        catalog = {item["id"]: item for item in plan_catalog()}
        self.assertEqual(list(catalog), ["free", "pro", "enterprise"])
        self.assertEqual(catalog["pro"]["price_cents"], 1900)
        self.assertEqual(catalog["enterprise"]["price_cents"], 9900)
        self.assertEqual(catalog["enterprise"]["max_teams"], 5)
        self.assertEqual(catalog["enterprise"]["team_seats"], 25)
        self.assertEqual(
            [product["id"] for product in catalog["free"]["products"]],
            ["personal", "apps"],
        )


class RetentionTests(unittest.TestCase):
    def test_free_cutoff_is_fifteen_days(self):
        cutoff = retention_cutoff("free", NOW)
        self.assertEqual(NOW - cutoff, timedelta(days=15))
        self.assertIsNone(retention_cutoff("enterprise", NOW))

    def test_epoch_grace(self):
        epoch = NOW - timedelta(days=3)
        self.assertIsNone(clamp_to_epoch(retention_cutoff("free", NOW), epoch))
        later = NOW + timedelta(days=20)
        self.assertEqual(clamp_to_epoch(retention_cutoff("free", later), epoch), later - timedelta(days=15))
        self.assertIsNone(clamp_to_epoch(None, epoch))

    def test_shrink(self):
        self.assertTrue(retention_shrank("pro", "free"))
        self.assertTrue(retention_shrank("enterprise", "pro"))
        self.assertFalse(retention_shrank("free", "pro"))
        self.assertFalse(retention_shrank("pro", "enterprise"))
        self.assertFalse(retention_shrank("free", "free"))


class EffectivePlanTests(unittest.TestCase):
    def doc(self, **fields):
        return {"plan": "pro", "plan_status": "active", "plan_period_end": NOW + timedelta(days=10), **fields}

    def test_active_and_trialing(self):
        self.assertEqual(effective_plan(self.doc(), NOW), "pro")
        self.assertEqual(effective_plan(self.doc(plan_status="trialing"), NOW), "pro")

    def test_unpaid_states_are_free(self):
        for status in ("incomplete", "incomplete_expired", "unpaid", "paused", "canceled", "none", ""):
            self.assertEqual(effective_plan(self.doc(plan_status=status), NOW), "free", status)

    def test_past_due_grace(self):
        inside = self.doc(plan_status="past_due", plan_grace_until=NOW + timedelta(days=2))
        self.assertEqual(effective_plan(inside, NOW), "pro")
        outside = self.doc(plan_status="past_due", plan_grace_until=NOW - timedelta(minutes=1))
        self.assertEqual(effective_plan(outside, NOW), "free")
        self.assertEqual(effective_plan(self.doc(plan_status="past_due"), NOW), "free")

    def test_stale_period(self):
        stale = self.doc(plan_period_end=NOW - timedelta(days=8))
        self.assertEqual(effective_plan(stale, NOW), "free")
        recent = self.doc(plan_period_end=NOW - timedelta(days=2))
        self.assertEqual(effective_plan(recent, NOW), "pro")

    def test_iso_strings(self):
        doc = self.doc(plan_period_end=(NOW + timedelta(days=3)).isoformat().replace("+00:00", "Z"))
        self.assertEqual(effective_plan(doc, NOW), "pro")

    def test_grants(self):
        free = {"plan": "free", "plan_status": "none"}
        self.assertEqual(effective_plan({**free, "plan_grant": {"plan": "enterprise"}}, NOW), "enterprise")
        lapsed = {"plan": "enterprise", "until": NOW - timedelta(seconds=1)}
        self.assertEqual(effective_plan({**free, "plan_grant": lapsed}, NOW), "free")
        self.assertIsNone(granted_plan({**free, "plan_grant": {"plan": "free"}}, NOW))
        paid = self.doc(plan="enterprise", plan_grant={"plan": "pro"})
        self.assertEqual(effective_plan(paid, NOW), "enterprise")
        self.assertEqual(effective_plan(self.doc(plan_grant={"plan": "enterprise"}), NOW), "enterprise")

    def test_missing_doc(self):
        self.assertEqual(effective_plan(None, NOW), "free")
        self.assertEqual(effective_plan({}, NOW), "free")


if __name__ == "__main__":
    unittest.main()
