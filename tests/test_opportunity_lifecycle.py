"""Synthetic deduplication and append-only freshness regressions."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))
from opportunity_lifecycle import (LifecycleError, append_observation,
                                   classify_relationship, freshness_state,
                                   merge_same_opportunity, normalize_posting_url)
from validate_opportunities import validate_opportunities

FIXTURE = json.loads((ROOT / "tests/fixtures/opportunities.synthetic.json").read_text())


class OpportunityLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.base = copy.deepcopy(FIXTURE["opportunities"][0])

    def test_normalized_exact_url_and_safe_merge_preserve_provenance(self):
        self.assertEqual(normalize_posting_url("https://EXAMPLE.com/roles/101/?utm_source=x#apply"),
                         normalize_posting_url("https://example.com/roles/101"))
        second = copy.deepcopy(self.base)
        second["id"] = "opp_copy"
        second["source_platform"] = "Aggregator"
        second["original_url"] = "https://jobs.example.com/roles/101?utm_campaign=x"
        second["sources"][0]["url"] = second["original_url"]
        self.assertEqual("same_opportunity_high_confidence", classify_relationship(self.base, second)[0])
        merged = merge_same_opportunity(self.base, second)
        self.assertEqual(2, len(merged["sources"]))
        self.assertEqual(2, len(merged["evidence"]))
        self.assertEqual([], validate_opportunities({"schema_version": "1", "opportunities": [merged]}))

    def test_cross_platform_explicit_posting_id_is_high_confidence(self):
        second = copy.deepcopy(self.base)
        second["id"] = "opp_cross_platform"
        second["original_url"] = "https://board.example.org/jobs/abc"
        second["source_platform"] = "Other ATS"
        second["sources"][0].update(url=second["original_url"], platform="Other ATS")
        for item in second["claims"].values():
            if item["value"] is not None:
                item["evidence_ids"] = ["ev_1"]
        for record in (self.base, second):
            record["claims"]["posting_id"] = {"value": "REQ-778", "origin": "observed", "evidence_ids": ["ev_1"]}
        self.assertEqual("same_opportunity_high_confidence", classify_relationship(self.base, second)[0])

    def test_similar_but_distinct_and_possible_duplicate_are_not_merged(self):
        second = copy.deepcopy(self.base)
        second["id"] = "opp_other_city"
        second["original_url"] = "https://other.example/jobs/55"
        second["sources"][0]["url"] = second["original_url"]
        second["claims"]["location"].update(value="Manchester")
        self.assertEqual("distinct_opportunities", classify_relationship(self.base, second)[0])
        second["claims"]["location"].update(value="London")
        self.assertEqual("possible_duplicate_requires_review", classify_relationship(self.base, second)[0])
        with self.assertRaises(LifecycleError):
            merge_same_opportunity(self.base, second)

    def test_conflicting_high_confidence_sources_refuse_merge(self):
        second = copy.deepcopy(self.base)
        second["id"] = "opp_conflict"
        second["claims"]["employer"]["value"] = "Different Employer"
        with self.assertRaisesRegex(LifecycleError, "conflicting_claims"):
            merge_same_opportunity(self.base, second)

    def _observe(self, result, code):
        source = {"id": "src_new", "url": self.base["original_url"], "platform": self.base["source_platform"],
                  "observed_at": "2026-10-13T12:00:00Z", "access": "inaccessible",
                  "observation_result": result, "http_status": code}
        return append_observation(self.base, source)

    def test_http_410_is_gone_but_not_proof_applications_closed(self):
        record = self._observe("gone", 410)
        state = freshness_state(record)
        self.assertEqual("gone", state["observation_result"])
        self.assertIsNone(state["application_status"])
        self.assertEqual("unknown", record["claims"]["status"]["origin"])
        self.assertEqual([], validate_opportunities({"schema_version": "1", "opportunities": [record]}))

    def test_temporary_failure_does_not_transition_to_closed(self):
        record = self._observe("temporary_failure", 503)
        self.assertEqual("temporary_failure", freshness_state(record)["observation_result"])
        self.assertIsNone(freshness_state(record)["application_status"])
        self.assertEqual("2026-10-10T09:00:00Z", self.base["last_observed_at"])
        self.assertEqual([], validate_opportunities({"schema_version": "1", "opportunities": [record]}))

    def test_unknown_status_stays_unknown_on_reachable_page(self):
        source = {"id": "src_new", "url": self.base["original_url"], "platform": self.base["source_platform"],
                  "observed_at": "2026-10-13T12:00:00Z", "access": "accessible", "observation_result": "reachable", "http_status": 200}
        record = append_observation(self.base, source)
        self.assertTrue(freshness_state(record)["source_reachable"])
        self.assertIsNone(freshness_state(record)["application_status"])
        self.assertEqual([], validate_opportunities({"schema_version": "1", "opportunities": [record]}))


if __name__ == "__main__":
    unittest.main()
