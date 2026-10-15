"""Synthetic tests for discovery-to-current-matching handoff."""

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))

import integrate_matching as integration
import prepare_pipeline as pipeline
from local_storage import write_private_json_atomic
from validate_profile import SECTIONS


def synthetic_profile():
    profile = json.loads((ROOT / "tests/fixtures/candidate-profile.synthetic.json").read_text())
    profile["verification_status"] = "verified"
    profile["section_reviews"] = dict.fromkeys(SECTIONS, "confirmed")
    for item in profile["evidence"]:
        item["review_status"] = "confirmed"
    for section in SECTIONS:
        for item in profile[section]:
            item["review_status"] = "confirmed"
    return profile


def synthetic_preferences():
    return json.loads((ROOT / "tests/fixtures/search-preferences.synthetic.json").read_text())


class DiscoveryMatchingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name).resolve()
        for category in ("profiles", "discovery", "opportunities", "matches"):
            (self.workspace / ".jobra" / category).mkdir(parents=True, exist_ok=True)
        self.profile_path = write_private_json_atomic(
            self.workspace, "profiles", "verified-synthetic.json", synthetic_profile())
        self.preferences_path = write_private_json_atomic(
            self.workspace, "discovery", "preferences-synthetic.json", synthetic_preferences())
        self.opportunities = json.loads((ROOT / "tests/fixtures/opportunities.synthetic.json").read_text())
        self.opportunities["opportunities"] = [copy.deepcopy(self.opportunities["opportunities"][0])]
        self.opportunity = self.opportunities["opportunities"][0]
        self.snapshot_path = write_private_json_atomic(
            self.workspace, "opportunities", "snapshot-synthetic.json", self.opportunities)
        self.manifest, self.manifest_path = pipeline.prepare_run(
            self.workspace, opportunity_snapshot_path=self.snapshot_path,
            limits={"max_discovery_queries": 3, "max_opportunities_to_discover": 3,
                    "max_opportunities_to_assess": 2, "max_retries": 1})
        self.audit = {"audit_version": "1", "run_id": self.manifest["run_id"],
            "created_at": "2026-10-15T12:00:00Z", "query_count": 1,
            "observation_count": 3, "valid_opportunity_count": 2,
            "resulting_catalog_count": 1, "execution_status": "partial",
            "observations": [
                {"observation_id": "obs_new", "opportunity_id": self.opportunity["id"],
                 "status": "accepted_distinct", "relationship": "distinct_opportunities"},
                {"observation_id": "obs_excluded", "status": "explicitly_rejected",
                 "reason_code": "excluded_seniority", "source_url": "https://jobs.example.test/senior"},
                {"observation_id": "obs_duplicate", "opportunity_id": "opp_possible",
                 "status": "possible_duplicate_requires_review",
                 "relationship": "possible_duplicate_requires_review"}],
            }
        self.audit_path = write_private_json_atomic(
            self.workspace, "discovery", "audit-synthetic.json", self.audit)
        self.manifest["artifacts"]["opportunity_snapshot"] = self._ref(self.snapshot_path)
        self.manifest["artifacts"]["discovery_audit"] = self._ref(self.audit_path)
        self.manifest, self.manifest_path = self._transition("live_discovery", "running")
        self.manifest, self.manifest_path = self._transition("live_discovery", "partial", reason="discovery_incomplete")
        self.manifest, self.manifest_path = self._transition("opportunity_validation_and_persistence", "running")
        self.manifest, self.manifest_path = self._transition(
            "opportunity_validation_and_persistence", "partial", reason="observation_failures_or_review")
        self.manifest, self.manifest_path = self._transition("deduplication_and_freshness", "running")
        self.manifest, self.manifest_path = self._transition(
            "deduplication_and_freshness", "partial", reason="review_or_observation_uncertainty")

    def tearDown(self):
        self.temp.cleanup()

    def _ref(self, path):
        return {"path": path.resolve().relative_to(self.workspace).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def _transition(self, stage, status, **kwargs):
        next_manifest = pipeline.transition_stage(self.manifest, stage, status, **kwargs)
        next_path = pipeline.save_run_manifest(next_manifest, self.workspace, previous_path=self.manifest_path)
        return next_manifest, next_path

    def _prepare(self, ids=None):
        return integration.prepare_matching_stage(self.manifest_path, self.workspace, ids)

    @staticmethod
    def _valid_assessment(catalog):
        opportunity = catalog["opportunities"][0]
        requirements = []
        for slot in opportunity["requirement_slots"]:
            requirements.append({"id": slot["requirement_id"],
                "statement": "Qualification represented by source evidence", "priority": "unspecified",
                "outcome": "not_evidenced", "evidence_quality": "insufficient",
                "job_evidence_ids": [slot["job_evidence_id"]],
                "candidate_record_ids": [], "candidate_evidence_ids": [],
                "rationale": "The candidate catalog contains no reviewed evidence establishing this qualification."})
        return {"schema_version": "1", "assessments": [{
            "opportunity_id": opportunity["opportunity_id"], "requirements": requirements,
            "experience_alignment": {"outcome": "unknown", "job_evidence_ids": [],
                "candidate_record_ids": [], "candidate_evidence_ids": [], "rationale": "The posting evidence does not state an assessable experience threshold."},
            "career_alignment": {"outcome": "uncertain", "preference_terms": [],
                "job_evidence_ids": [], "rationale": "No direct preference evidence is available for this title."}}]}

    def test_partial_discovery_prepares_current_catalog_and_immutable_revisions(self):
        source_hash = hashlib.sha256(self.snapshot_path.read_bytes()).hexdigest()
        result = self._prepare([self.opportunity["id"]])
        catalog = json.loads(result["catalog_path"].read_text())
        self.assertEqual([self.opportunity["id"]], result["assessment_opportunity_ids"])
        self.assertEqual("completed", result["manifest"]["stages"]["matching_catalog_preparation"]["status"])
        self.assertEqual("running", result["manifest"]["stages"]["semantic_assessment"]["status"])
        self.assertEqual(self.audit["run_id"], catalog["pipeline_context"]["run_id"])
        self.assertTrue(catalog["opportunities"][0]["requirement_slots"])
        self.assertEqual(source_hash, hashlib.sha256(self.snapshot_path.read_bytes()).hexdigest())
        self.assertEqual(0o600, os.stat(result["catalog_path"]).st_mode & 0o777)
        self.assertTrue(self.manifest_path.exists())

    def test_budget_and_possible_duplicate_selection_are_explicit(self):
        with self.assertRaisesRegex(integration.MatchingIntegrationError, "selected_opportunity_ids_invalid"):
            self._prepare([self.opportunity["id"], self.opportunity["id"]])
        snapshot = {"opportunities": [{"id": "one"}, {"id": "two"}, {"id": "three"}]}
        audit = {"observations": [{"opportunity_id": "three",
                                   "status": "possible_duplicate_requires_review"}]}
        selected, possible = integration._select_ids(snapshot, audit, 2)
        self.assertNotIn("three", selected)
        self.assertIn("three", possible)
        with self.assertRaisesRegex(integration.MatchingIntegrationError, "assessment_budget_exceeded"):
            integration._select_ids(snapshot, audit, 2, ["one", "two", "three"])

    def test_explicit_user_exclusion_is_not_sent_for_semantic_assessment(self):
        prefs = synthetic_preferences()
        title = self.opportunity["claims"]["title"]["value"]
        prefs["excluded_roles"] = [title]
        alternate_preferences = write_private_json_atomic(
            self.workspace, "discovery", "preferences-excluded.json", prefs)
        manifest, path = pipeline.prepare_run(self.workspace,
            profile_path=self.profile_path, preferences_path=alternate_preferences,
            opportunity_snapshot_path=self.snapshot_path,
            limits={"max_discovery_queries": 3, "max_opportunities_to_discover": 3,
                    "max_opportunities_to_assess": 2, "max_retries": 1})
        audit = copy.deepcopy(self.audit)
        audit["run_id"] = manifest["run_id"]
        audit_path = write_private_json_atomic(
            self.workspace, "discovery", "audit-excluded.json", audit)
        manifest["artifacts"]["opportunity_snapshot"] = self._ref(self.snapshot_path)
        manifest["artifacts"]["discovery_audit"] = self._ref(audit_path)
        for stage, status, kwargs in (
            ("live_discovery", "running", {}), ("live_discovery", "partial", {"reason": "discovery_incomplete"}),
            ("opportunity_validation_and_persistence", "running", {}),
            ("opportunity_validation_and_persistence", "partial", {"reason": "observation_failures_or_review"}),
            ("deduplication_and_freshness", "running", {}),
            ("deduplication_and_freshness", "partial", {"reason": "review_or_observation_uncertainty"})):
            manifest = pipeline.transition_stage(manifest, stage, status, **kwargs)
        path = pipeline.save_run_manifest(manifest, self.workspace, previous_path=path)
        result = integration.prepare_matching_stage(path, self.workspace, [self.opportunity["id"]])
        catalog = json.loads(result["catalog_path"].read_text())
        self.assertEqual([], result["assessment_opportunity_ids"])
        self.assertEqual([], catalog["opportunities"])
        self.assertIn(self.opportunity["id"], catalog["pipeline_context"]["explicitly_excluded_ids"])
        final = integration.finalize_matching_stage(result["manifest_path"], self.workspace)
        self.assertEqual("excluded_by_explicit_user_constraint",
                         final["result"]["results"][0]["workflow_status"])

    def test_valid_assessment_aggregates_and_reports_all_snapshot_items(self):
        prepared = self._prepare([self.opportunity["id"]])
        catalog = json.loads(prepared["catalog_path"].read_text())
        before = hashlib.sha256(self.snapshot_path.read_bytes()).hexdigest()
        final = integration.finalize_matching_stage(
            prepared["manifest_path"], self.workspace, self._valid_assessment(catalog))
        self.assertEqual("successfully_assessed", final["result"]["results"][0]["workflow_status"])
        self.assertEqual("newly_discovered", final["result"]["results"][0]["discovery_origin"]["classification"])
        self.assertEqual(self.opportunity["original_url"], final["result"]["results"][0]["original_url"])
        self.assertEqual("completed", final["manifest"]["stages"]["semantic_assessment"]["status"])
        self.assertEqual("completed", final["manifest"]["stages"]["aggregation_and_results"]["status"])
        self.assertTrue(final["result_report_path"].exists())
        report = final["result_report_path"].read_text()
        self.assertIn("explicitly_rejected", report)
        self.assertIn(self.opportunity["last_observed_at"].replace("-", "\\-"), report)
        self.assertEqual("partial", final["manifest"]["run_status"])
        self.assertIn("discovery run", report.lower())
        self.assertEqual(before, hashlib.sha256(self.snapshot_path.read_bytes()).hexdigest())
        self.assertIn("result_snapshot", final["manifest"]["artifacts"])

    def test_missing_assessment_is_not_a_negative_match_and_exclusions_remain_visible(self):
        prepared = self._prepare([self.opportunity["id"]])
        final = integration.finalize_matching_stage(prepared["manifest_path"], self.workspace)
        result = final["result"]["results"][0]
        self.assertEqual("assessment_not_completed", result["workflow_status"])
        self.assertIsNone(result["candidate_fit"])
        self.assertIn("explicitly_rejected", final["result_report_path"].read_text())
        self.assertEqual("partial", final["manifest"]["run_status"])

    def test_invalid_assessment_is_visible_without_discarding_other_result_data(self):
        prepared = self._prepare([self.opportunity["id"]])
        catalog = json.loads(prepared["catalog_path"].read_text())
        assessment = self._valid_assessment(catalog)
        assessment["assessments"][0]["requirements"][0]["job_evidence_ids"] = ["invented_evidence"]
        final = integration.finalize_matching_stage(prepared["manifest_path"], self.workspace, assessment)
        result = final["result"]["results"][0]
        self.assertEqual("assessment_failed_validation", result["workflow_status"])
        self.assertEqual("invalid", result["semantic_assessment"]["status"])
        self.assertEqual("partial", final["manifest"]["stages"]["aggregation_and_results"]["status"])

    def test_result_artifacts_are_create_only_and_manifest_links_sources(self):
        prepared = self._prepare([self.opportunity["id"]])
        catalog = json.loads(prepared["catalog_path"].read_text())
        final = integration.finalize_matching_stage(
            prepared["manifest_path"], self.workspace, self._valid_assessment(catalog))
        manifest = final["manifest"]
        self.assertEqual(self._ref(self.snapshot_path), manifest["artifacts"]["opportunity_snapshot"])
        self.assertEqual(self._ref(self.audit_path), manifest["artifacts"]["discovery_audit"])
        self.assertTrue((self.workspace / manifest["artifacts"]["result_snapshot"]["path"]).exists())
        self.assertTrue((self.workspace / manifest["artifacts"]["result_report"]["path"]).exists())
        self.assertTrue(pipeline.validate_manifest(manifest) == [])


if __name__ == "__main__":
    unittest.main()
