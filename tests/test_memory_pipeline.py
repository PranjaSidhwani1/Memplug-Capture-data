"""Pipeline rules that do not need a database or a model."""

from __future__ import annotations

import unittest
import uuid

from app.candidates import canonical_entity_type, canonical_relationship, parse_decisions, parse_extraction
from app.decide import align_decisions, validate_decision
from app.entities import name_variant_match, resolution_action
from app.ingest import dedupe_key
from app.relations import bind_relationships, plan_relationship
from app.retrieve import fuse_rows
from app.writer import mentions


class DecisionTests(unittest.TestCase):
    def test_rejects_targets_that_were_not_retrieved(self):
        candidate = {"candidate_id": "cand_001", "content": "Memplug uses Redis.", "domain": "Coding", "memory_type": "fact", "scope": "project", "source_message_ids": []}
        retrieved = [{"memory_id": "mem-1", "content": "Memplug uses PostgreSQL.", "similarity": 0.4}]
        decision = validate_decision(
            {
                "operation": "REPLACE",
                "target_memory_ids": ["mem-other", "mem-1"],
                "final_content": "Memplug uses PostgreSQL and Redis.",
                "confidence": 0.9,
            },
            candidate,
            retrieved,
        )
        self.assertEqual(decision["operation"], "REPLACE")
        self.assertEqual(decision["target_memory_ids"], ["mem-1"])

    def test_low_confidence_is_noop(self):
        decision = validate_decision(
            {"operation": "ADD", "final_content": "A fact.", "confidence": 0.2, "target_memory_ids": []},
            {"candidate_id": "cand_001", "content": "A fact."},
            [],
        )
        self.assertEqual(decision["operation"], "NOOP")
        self.assertEqual(decision["final_content"], "")

    def test_replace_without_targets_becomes_add(self):
        decision = validate_decision(
            {"operation": "REPLACE", "final_content": "A new fact.", "confidence": 0.8, "target_memory_ids": ["nope"]},
            {"candidate_id": "cand_001", "content": "A new fact."},
            [],
        )
        self.assertEqual(decision["operation"], "ADD")
        self.assertEqual(decision["target_memory_ids"], [])

    def test_unchanged_replace_is_noop(self):
        decision = validate_decision(
            {"operation": "REPLACE", "target_memory_ids": ["mem-1"], "final_content": "Same fact.", "confidence": 0.99},
            {"candidate_id": "cand_001", "content": "Same fact."},
            [{"memory_id": "mem-1", "content": "same   fact."}],
        )
        self.assertEqual(decision["operation"], "NOOP")

    def test_missing_proposal_falls_back_to_add(self):
        candidate = {"candidate_id": "cand_001", "content": "Keep this.", "confidence": 0.8, "domain": "Work", "memory_type": "fact", "scope": "user", "source_message_ids": []}
        aligned = align_decisions([candidate], [], {"cand_001": []})
        self.assertEqual(aligned[0]["operation"], "ADD")
        self.assertEqual(aligned[0]["final_content"], "Keep this.")


class EntityTests(unittest.TestCase):
    def test_postgres_variant_is_reuse_and_semantic_alone_is_not(self):
        self.assertTrue(name_variant_match("Postgres", "PostgreSQL"))
        self.assertFalse(name_variant_match("Java", "JavaScript"))
        self.assertFalse(name_variant_match("Python", "Python3"))
        self.assertFalse(name_variant_match("Redis", "Memcached"))
        reused = resolution_action(variant_id="ent-pg")
        self.assertEqual(reused["action"], "REUSE")
        self.assertEqual(reused["match_id"], "ent-pg")
        created = resolution_action(semantic=[("ent-near", 0.99)])
        self.assertEqual(created["action"], "CREATE")
        self.assertEqual(created["ambiguous_with"], ["ent-near"])

    def test_alias_reuses_and_exact_wins(self):
        decision = resolution_action(exact_id="ent-1", alias_id="ent-2", semantic=[("ent-3", 0.95)])
        self.assertEqual(decision["action"], "REUSE")
        self.assertEqual(decision["match_id"], "ent-1")
        self.assertIn("ent-3", decision["ambiguous_with"])

    def test_entity_type_aliases(self):
        self.assertEqual(canonical_entity_type("tool"), "technology")
        self.assertEqual(canonical_entity_type("place"), "location")
        self.assertEqual(canonical_entity_type("mystery"), "concept")


class RelationshipTests(unittest.TestCase):
    def test_active_duplicate_is_not_created(self):
        self.assertEqual(plan_relationship({"USES"}, "USES", "create"), {"create": False, "close_types": []})
        self.assertEqual(plan_relationship({"USES"}, "USES", "supersede"), {"create": False, "close_types": []})

    def test_supersede_closes_other_active_types(self):
        plan = plan_relationship({"USES_FOR_STORAGE"}, "USES_FOR_CACHING", "supersede")
        self.assertEqual(plan["create"], True)
        self.assertEqual(plan["close_types"], ["USES_FOR_STORAGE"])
        crowded = plan_relationship({"USES_FOR_STORAGE", "OWNED_BY"}, "USES_FOR_CACHING", "supersede")
        self.assertEqual(crowded["close_types"], [])

    def test_create_leaves_other_types_open(self):
        plan = plan_relationship({"OWNED_BY"}, "USES", "create")
        self.assertEqual(plan, {"create": True, "close_types": []})

    def test_bind_requires_resolved_ids(self):
        resolutions = [
            {"name_norm": "memplug", "entity_id": "ent-1"},
            {"name_norm": "redis", "entity_id": "ent-2"},
        ]
        bound = bind_relationships(
            [
                {"source": "Memplug", "target": "Redis", "relationship": "USES", "action": "create", "source_message_ids": []},
                {"source": "Memplug", "target": "Missing", "relationship": "USES", "action": "create", "source_message_ids": []},
                {"source": "Redis", "target": "Redis", "relationship": "USES", "action": "create", "source_message_ids": []},
            ],
            resolutions,
        )
        self.assertEqual(len(bound), 1)
        self.assertEqual(bound[0]["source_entity_id"], "ent-1")
        self.assertEqual(bound[0]["target_entity_id"], "ent-2")

    def test_relationship_type_is_normalized(self):
        self.assertEqual(canonical_relationship("uses for caching"), "USES_FOR_CACHING")
        self.assertEqual(canonical_relationship("123"), "")


class ParseTests(unittest.TestCase):
    def test_extraction_keeps_cited_messages_and_drops_weak_facts(self):
        message_id = str(uuid.uuid4())
        parsed = parse_extraction(
            {
                "memory_candidates": [
                    {
                        "candidate_id": "cand_001",
                        "content": "Memplug uses Redis for caching.",
                        "memory_type": "decision",
                        "domain": "Coding",
                        "scope": "project",
                        "confidence": 0.91,
                        "source_message_ids": [message_id, "not-a-uuid"],
                    },
                    {"content": "Too unsure.", "confidence": 0.2},
                ],
                "entity_candidates": [
                    {"name": "Memplug", "type": "project"},
                    {"name": "Redis", "type": "technology"},
                    {"name": "Redis", "type": "tool"},
                ],
                "relationship_candidates": [
                    {"source": "Memplug", "relationship": "uses", "target": "Redis", "action": "create", "source_message_ids": [message_id]}
                ],
            },
            {message_id},
        )
        self.assertEqual(len(parsed["memory_candidates"]), 1)
        self.assertEqual(parsed["memory_candidates"][0]["source_message_ids"], [message_id])
        self.assertEqual(
            [(item["name"], item["entity_type"]) for item in parsed["entity_candidates"]],
            [("Memplug", "project"), ("Redis", "technology")],
        )
        self.assertEqual(parsed["relationship_candidates"][0]["relationship"], "USES")

    def test_decisions_parse(self):
        rows = parse_decisions(
            {"decisions": [{"candidate_id": "cand_001", "operation": "merge", "target_memory_ids": ["a", "a"], "final_content": "Combined.", "confidence": 0.7}]}
        )
        self.assertEqual(rows[0]["operation"], "MERGE")
        self.assertEqual(rows[0]["target_memory_ids"], ["a"])


class IngestAndRankTests(unittest.TestCase):
    def test_event_id_is_the_idempotency_key(self):
        event = dedupe_key(event_id="evt-1", role="user", content="hello")
        external = dedupe_key(external_message_id="msg-1", role="user", content="hello")
        body = dedupe_key(role="user", content="hello")
        self.assertTrue(event.startswith("event:"))
        self.assertTrue(external.startswith("external:"))
        self.assertNotEqual(event, body)
        self.assertEqual(body, dedupe_key(role="user", content="hello"))
        other_session = dedupe_key(role="user", content="hello", session_id="other")
        self.assertNotEqual(body, other_session)

    def test_graph_hit_changes_rank(self):
        vector = [("mem-a", "alpha"), ("mem-b", "beta")]
        lexical = [("mem-b", "beta")]
        graph = [("mem-b", "beta"), ("mem-c", "gamma")]
        self.assertEqual(fuse_rows([vector, lexical, graph], 2), ["beta", "alpha"])

    def test_mentions_ignores_punctuation_and_short_names(self):
        self.assertTrue(mentions("Memplug uses Redis.", "redis"))
        self.assertFalse(mentions("The goal is speed.", "go"))
        self.assertFalse(mentions("Redisson is a client.", "redis"))


if __name__ == "__main__":
    unittest.main()
