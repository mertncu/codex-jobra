"""Offline planning gates; these tests are not live-search evidence."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))
from plan_discovery import build_search_plan, DiscoveryError
from validate_profile import SECTIONS


class DiscoveryPlanTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((ROOT / "tests/fixtures/candidate-profile.synthetic.json").read_text())
        self.profile["verification_status"] = "verified"
        self.profile["section_reviews"] = dict.fromkeys(SECTIONS, "confirmed")
        for item in self.profile["evidence"]:
            item["review_status"] = "confirmed"
        for section in SECTIONS:
            for record in self.profile[section]:
                record["review_status"] = "confirmed"
        self.preferences = {"schema_version": "1", "preferred_roles": ["Backend Developer"],
                            "excluded_roles": [], "locations": ["Example City"],
                            "work_arrangements": ["remote"], "seniority_preferences": ["entry"]}

    def test_no_profile_content_in_queries_and_no_input_mutation(self):
        before = copy.deepcopy((self.profile, self.preferences))
        first = build_search_plan(self.profile, self.preferences)
        self.assertEqual(before, (self.profile, self.preferences))
        self.profile["education"][0]["institution"] = "PRIVATE_CANDIDATE_MARKER"
        second = build_search_plan(self.profile, self.preferences)
        self.assertEqual(first["queries"], second["queries"])
        self.assertNotIn("PRIVATE_CANDIDATE_MARKER", json.dumps(second))
        self.assertNotIn("suggested_roles", second["verified_fact_ids_local_only"])
        self.assertEqual("awaiting_query_approval", second["status"])

    def test_unverified_and_missing_preferences_block_planning(self):
        self.profile["verification_status"] = "draft"
        with self.assertRaises(DiscoveryError):
            build_search_plan(self.profile, self.preferences)
        self.setUp()
        for field in ("preferred_roles", "locations", "work_arrangements", "seniority_preferences"):
            preferences = copy.deepcopy(self.preferences)
            preferences[field] = []
            with self.assertRaisesRegex(DiscoveryError, "essential_preferences_missing"):
                build_search_plan(self.profile, preferences)

    def test_rejected_and_inferred_records_are_not_planning_facts(self):
        record = self.profile["education"][0]
        record["review_status"] = "rejected"
        plan = build_search_plan(self.profile, self.preferences)
        self.assertNotIn(record["id"], plan["verified_fact_ids_local_only"]["education"])
        record["review_status"] = "confirmed"
        for item in self.profile["evidence"]:
            if item["id"] in record["evidence_ids"]:
                item["extraction"] = "inferred"
        plan = build_search_plan(self.profile, self.preferences)
        self.assertNotIn(record["id"], plan["verified_fact_ids_local_only"]["education"])

    def test_conflicts_and_oversized_scope_rejected(self):
        self.preferences["excluded_roles"] = ["backend developer"]
        with self.assertRaisesRegex(DiscoveryError, "conflicting_role_preferences"):
            build_search_plan(self.profile, self.preferences)
        self.preferences["excluded_roles"] = []
        self.preferences["locations"] = [f"Location {i}" for i in range(101)]
        with self.assertRaisesRegex(DiscoveryError, "search_scope_too_broad"):
            build_search_plan(self.profile, self.preferences)


if __name__ == "__main__":
    unittest.main()
