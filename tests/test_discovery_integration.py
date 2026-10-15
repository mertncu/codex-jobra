"""Synthetic end-to-end tests for deterministic discovery integration."""

import copy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))
import prepare_pipeline
from integrate_discovery import DiscoveryIntegrationError, execute_discovery
from validate_opportunities import validate_opportunities


def _synthetic_preferences():
    return {"schema_version": "1", "preferred_roles": ["Backend Developer"],
            "excluded_roles": [], "locations": ["Example City"],
            "work_arrangements": ["remote"], "seniority_preferences": ["entry"]}


class DiscoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        for folder in ("profiles", "discovery", "opportunities"):
            (self.workspace / ".jobra" / folder).mkdir(parents=True, exist_ok=True)
        profile = json.loads((ROOT / "tests/fixtures/candidate-profile.synthetic.json").read_text())
        from validate_profile import SECTIONS
        profile["verification_status"] = "verified"
        profile["section_reviews"] = dict.fromkeys(SECTIONS, "confirmed")
        for evidence in profile["evidence"]:
            evidence["review_status"] = "confirmed"
        for section in SECTIONS:
            for record in profile[section]:
                record["review_status"] = "confirmed"
        self._write(self.workspace / ".jobra/profiles/verified-synthetic.json", profile)
        self._write(self.workspace / ".jobra/discovery/preferences-synthetic.json", _synthetic_preferences())
        self.manifest, self.manifest_path = prepare_pipeline.prepare_run(self.workspace)
        self.plan = json.loads((self.workspace / self.manifest["artifacts"]["discovery_query_plan"]["path"]).read_text())
        self.base = copy.deepcopy(json.loads((ROOT / "tests/fixtures/opportunities.synthetic.json").read_text())["opportunities"][0])

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _write(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def _record(self, opportunity_id="opp_new", *, url=None, title=None):
        record = copy.deepcopy(self.base)
        record["id"] = opportunity_id
        if url:
            record["original_url"] = url
            record["sources"][0]["url"] = url
        if title:
            record["claims"]["title"]["value"] = title
        return record

    def _payload(self, observations, *, execution_status="completed"):
        return {"schema_version": "1", "execution_status": execution_status,
                "queries_executed": self.plan["queries"][:1], "observations": observations}

    def _opp_observation(self, record, observation_id="obs_1"):
        return {"observation_id": observation_id, "outcome": "opportunity", "opportunity": record}

    def test_successful_discovery_creates_snapshot_audit_and_manifest_revisions(self):
        result = execute_discovery(self.manifest_path,
                                   self._payload([self._opp_observation(self._record())]),
                                   self.workspace)
        current = result["manifest"]
        self.assertEqual("completed", current["stages"]["live_discovery"]["status"])
        self.assertEqual("completed", current["stages"]["opportunity_validation_and_persistence"]["status"])
        self.assertEqual("completed", current["stages"]["deduplication_and_freshness"]["status"])
        self.assertEqual([], validate_opportunities(json.loads(result["snapshot_path"].read_text())))
        self.assertEqual(0o600, result["snapshot_path"].stat().st_mode & 0o777)
        self.assertEqual(0o600, result["audit_path"].stat().st_mode & 0o777)
        self.assertEqual("accepted_distinct", json.loads(result["audit_path"].read_text())["observations"][0]["status"])
        revisions = sorted((self.workspace / ".jobra/discovery").glob(f"{current['run_id']}-r*.json"))
        self.assertGreaterEqual(len(revisions), 5)
        self.assertTrue(self.manifest_path.exists())

    def test_mixed_invalid_inaccessible_and_rejected_observations_are_audited(self):
        invalid = self._record("opp_bad")
        invalid["claims"]["title"]["evidence_ids"] = ["ev_missing"]
        payload = self._payload([
            self._opp_observation(self._record(), "obs_valid"),
            self._opp_observation(invalid, "obs_invalid"),
            {"observation_id": "obs_unreachable", "outcome": "inaccessible",
             "source_url": "https://jobs.example.test/closed", "reason_code": "source_inaccessible"},
            {"observation_id": "obs_rejected", "outcome": "rejected", "reason_code": "user_rejected",
             "opportunity": {"id": "opp_rejected", "description": "retained in private audit"}},
        ])
        result = execute_discovery(self.manifest_path, payload, self.workspace)
        self.assertEqual("partial", result["manifest"]["stages"]["opportunity_validation_and_persistence"]["status"])
        audit = json.loads(result["audit_path"].read_text())
        self.assertEqual(["accepted_distinct", "invalid_observation", "source_inaccessible", "explicitly_rejected"],
                         [row["status"] for row in audit["observations"]])
        self.assertIn("retained in private audit", result["audit_path"].read_text())
        self.assertEqual(1, len(json.loads(result["snapshot_path"].read_text())["opportunities"]))

    def test_duplicate_is_merged_with_source_provenance_and_similar_listing_needs_review(self):
        historical = {"schema_version": "1", "opportunities": [self.base]}
        historical_path = self.workspace / ".jobra/opportunities/snapshot-history.json"
        self._write(historical_path, historical)
        self.manifest, self.manifest_path = prepare_pipeline.prepare_run(
            self.workspace, opportunity_snapshot_path=historical_path)
        self.plan = json.loads((self.workspace / self.manifest["artifacts"]["discovery_query_plan"]["path"]).read_text())
        duplicate = self._record("opp_duplicate", url=self.base["original_url"] + "?utm_source=search")
        possible = self._record("opp_possible", url="https://example.com/jobs/other")
        payload = self._payload([self._opp_observation(duplicate, "obs_duplicate"),
                                 self._opp_observation(possible, "obs_possible")])
        result = execute_discovery(self.manifest_path, payload, self.workspace)
        snapshot = json.loads(result["snapshot_path"].read_text())
        self.assertEqual([], validate_opportunities(snapshot))
        self.assertGreaterEqual(len(snapshot["opportunities"][0]["sources"]), 2)
        audit = json.loads(result["audit_path"].read_text())
        self.assertEqual("merged_same_opportunity", audit["observations"][0]["status"])
        self.assertEqual("possible_duplicate_requires_review", audit["observations"][1]["status"])
        self.assertTrue(audit["observations"][1]["review_required"])
        self.assertEqual(historical, json.loads(historical_path.read_text()))

    def test_query_and_opportunity_budgets_are_enforced_without_saving_results(self):
        second_query = self.plan["queries"][0] + " extra"
        query_error = self._payload([])
        query_error["queries_executed"] = [second_query]
        with self.assertRaisesRegex(DiscoveryIntegrationError, "query_outside_prepared_plan"):
            execute_discovery(self.manifest_path, query_error, self.workspace)
        self.assertFalse(list((self.workspace / ".jobra/opportunities").glob("snapshot-*.json")))

        self.tearDown()
        self.setUp()
        self.manifest["limits"]["max_opportunities_to_discover"] = 1
        self.manifest["revision"] += 1
        self.manifest_path = prepare_pipeline.save_run_manifest(
            self.manifest, self.workspace, previous_path=self.manifest_path)
        payload = self._payload([self._opp_observation(self._record("opp_a"), "obs_a"),
                                 self._opp_observation(self._record("opp_b"), "obs_b")])
        with self.assertRaisesRegex(DiscoveryIntegrationError, "opportunity_budget_exceeded"):
            execute_discovery(self.manifest_path, payload, self.workspace)
        self.assertFalse(list((self.workspace / ".jobra/opportunities").glob("snapshot-*.json")))

    def test_no_valid_opportunities_fails_but_preserves_audit_and_interruption(self):
        invalid = self._record()
        invalid["claims"]["title"]["evidence_ids"] = ["not-real"]
        with self.assertRaisesRegex(DiscoveryIntegrationError, "no_valid_opportunities") as caught:
            execute_discovery(self.manifest_path,
                              self._payload([self._opp_observation(invalid)], execution_status="interrupted"),
                              self.workspace)
        saved, _ = prepare_pipeline.read_manifest(caught.exception.manifest_path, self.workspace)
        self.assertEqual("partial", saved["stages"]["live_discovery"]["status"])
        self.assertEqual("failed", saved["stages"]["opportunity_validation_and_persistence"]["status"])
        self.assertEqual("skipped", saved["stages"]["deduplication_and_freshness"]["status"])
        self.assertIsNotNone(saved["artifacts"]["discovery_audit"])
        self.assertIsNone(saved["artifacts"]["opportunity_snapshot"])

    def test_unknown_freshness_and_application_status_are_preserved(self):
        record = self._record()
        record["claims"]["status"] = {"value": None, "origin": "unknown", "evidence_ids": []}
        result = execute_discovery(self.manifest_path,
                                   self._payload([self._opp_observation(record)]), self.workspace)
        audit = json.loads(result["audit_path"].read_text())
        self.assertIsNone(audit["freshness"][0]["application_status"])
        self.assertTrue(audit["freshness"][0]["source_reachable"])
        self.assertIsNone(json.loads(result["snapshot_path"].read_text())["opportunities"][0]["claims"]["status"]["value"])

    def test_input_is_not_mutated_and_prior_artifacts_cannot_be_reused(self):
        payload = self._payload([self._opp_observation(self._record())])
        before = copy.deepcopy(payload)
        result = execute_discovery(self.manifest_path, payload, self.workspace)
        self.assertEqual(before, payload)
        self.assertTrue(result["snapshot_path"].exists())
        with self.assertRaisesRegex(DiscoveryIntegrationError, "discovery_stage_not_executable"):
            execute_discovery(result["manifest_path"], payload, self.workspace)


if __name__ == "__main__":
    unittest.main()
