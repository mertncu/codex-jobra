"""Synthetic tests for private deterministic pipeline preparation."""

import copy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))
import prepare_pipeline as pipeline
from prepare_pipeline import PreparationError
from local_storage import StorageError
from validate_profile import SECTIONS


def synthetic_profile():
    profile = json.loads((ROOT / "tests/fixtures/candidate-profile.synthetic.json").read_text())
    profile["verification_status"] = "verified"
    profile["section_reviews"] = dict.fromkeys(SECTIONS, "confirmed")
    for evidence in profile["evidence"]:
        evidence["review_status"] = "confirmed"
    for section in SECTIONS:
        for record in profile[section]:
            record["review_status"] = "confirmed"
    return profile


def synthetic_preferences():
    return {"schema_version": "1", "preferred_roles": ["Backend Developer"],
            "excluded_roles": [], "locations": ["Example City"],
            "work_arrangements": ["remote"], "seniority_preferences": ["entry"]}


class PipelinePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.profiles = self.workspace / ".jobra/profiles"
        self.discovery = self.workspace / ".jobra/discovery"
        self.opportunities = self.workspace / ".jobra/opportunities"
        self.profiles.mkdir(parents=True)
        self.discovery.mkdir(parents=True)
        self.opportunities.mkdir(parents=True)
        self.profile_path = self.profiles / "verified-synthetic.json"
        self.preferences_path = self.discovery / "preferences-synthetic.json"
        self._write(self.profile_path, synthetic_profile())
        self._write(self.preferences_path, synthetic_preferences())

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _write(path, document):
        path.write_text(json.dumps(document), encoding="utf-8")

    def test_successful_preparation_selects_and_references_private_inputs(self):
        historical = self.workspace / ".jobra/matches/pilot-assessment.json"
        historical.parent.mkdir(parents=True)
        historical.write_text("not a current assessment", encoding="utf-8")
        manifest, path = pipeline.prepare_run(self.workspace)
        self.assertEqual("prepared", manifest["run_status"])
        self.assertEqual("completed", manifest["stages"]["discovery_plan_preparation"]["status"])
        self.assertEqual("pending", manifest["stages"]["live_discovery"]["status"])
        self.assertEqual(10, manifest["limits"]["max_discovery_queries"])
        self.assertEqual(10, manifest["limits"]["max_opportunities_to_assess"])
        self.assertEqual(".jobra/profiles/verified-synthetic.json",
                         manifest["inputs"]["candidate_profile"]["path"])
        self.assertIsNone(manifest["inputs"]["selected_opportunity_snapshot"])
        self.assertIsNone(manifest["artifacts"]["assessment"])
        self.assertTrue(manifest["artifacts"]["discovery_query_plan"]["path"].startswith(".jobra/discovery/plan-"))
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest, saved)
        self.assertTrue(pipeline.validate_manifest(saved) == [])
        self.assertEqual(0o600, os.stat(path).st_mode & 0o777)
        self.assertNotIn("Example University", path.read_text(encoding="utf-8"))
        revisions = sorted(self.discovery.glob(f"{manifest['run_id']}-r*.json"))
        self.assertEqual(2, len(revisions))
        self.assertEqual([], pipeline.validate_manifest(json.loads(revisions[0].read_text())))

    def test_selected_saved_snapshot_is_validated_and_referenced(self):
        snapshot = json.loads((ROOT / "tests/fixtures/opportunities.synthetic.json").read_text())
        snapshot_path = self.opportunities / "snapshot-synthetic.json"
        self._write(snapshot_path, snapshot)
        manifest, _ = pipeline.prepare_run(self.workspace)
        self.assertEqual(".jobra/opportunities/snapshot-synthetic.json",
                         manifest["inputs"]["selected_opportunity_snapshot"]["path"])

    def test_unverified_and_invalid_profile_are_recorded_without_private_diagnostics(self):
        profile = synthetic_profile()
        profile["verification_status"] = "draft"
        self._write(self.profile_path, profile)
        manifest, _ = pipeline.prepare_run(self.workspace)
        stage = manifest["stages"]["candidate_profile_validation"]
        self.assertEqual("failed", stage["status"])
        self.assertEqual(["candidate_profile_unverified"], stage["error_codes"])
        self.assertEqual("skipped", manifest["stages"]["discovery_plan_preparation"]["status"])
        self.assertEqual("partial", manifest["run_status"])
        raw = json.dumps(manifest)
        self.assertNotIn("Example University", raw)
        self.assertNotIn("Example Studio", raw)

    def test_missing_profile_is_recorded_and_plan_is_skipped(self):
        self.profile_path.unlink()
        manifest, _ = pipeline.prepare_run(self.workspace)
        self.assertEqual(["verified_profile_missing"],
                         manifest["stages"]["candidate_profile_validation"]["error_codes"])
        self.assertEqual("skipped", manifest["stages"]["discovery_plan_preparation"]["status"])
        self.assertIsNone(manifest["inputs"]["candidate_profile"])

    def test_invalid_search_preferences_are_not_used(self):
        self._write(self.preferences_path, {"schema_version": "1", "preferred_roles": "private"})
        manifest, _ = pipeline.prepare_run(self.workspace)
        self.assertEqual(["search_preferences_invalid"],
                         manifest["stages"]["search_preferences_validation"]["error_codes"])
        self.assertEqual("skipped", manifest["stages"]["discovery_plan_preparation"]["status"])
        self.assertIsNone(manifest["inputs"]["search_preferences"])

    def test_missing_preferences_and_invalid_snapshot_are_explicit(self):
        self.preferences_path.unlink()
        bad_snapshot = self.opportunities / "snapshot-bad.json"
        self._write(bad_snapshot, {"schema_version": "wrong", "opportunities": []})
        manifest, _ = pipeline.prepare_run(self.workspace)
        self.assertEqual(["search_preferences_missing"],
                         manifest["stages"]["search_preferences_validation"]["error_codes"])
        self.assertEqual(["saved_opportunity_snapshot_invalid"],
                         manifest["stages"]["opportunity_snapshot_selection"]["error_codes"])

    def test_ambiguous_input_selections_require_explicit_paths(self):
        self._write(self.profiles / "verified-second.json", synthetic_profile())
        manifest, _ = pipeline.prepare_run(self.workspace)
        self.assertEqual(["profile_selection_ambiguous"],
                         manifest["stages"]["candidate_profile_validation"]["error_codes"])
        self.assertEqual("failed", manifest["stages"]["candidate_profile_validation"]["status"])

    def test_ambiguous_preferences_and_snapshot_require_explicit_paths(self):
        self._write(self.discovery / "preferences-second.json", synthetic_preferences())
        first_snapshot = json.loads((ROOT / "tests/fixtures/opportunities.synthetic.json").read_text())
        self._write(self.opportunities / "snapshot-first.json", first_snapshot)
        second_snapshot = copy.deepcopy(first_snapshot)
        self._write(self.opportunities / "snapshot-second.json", second_snapshot)
        manifest, _ = pipeline.prepare_run(self.workspace)
        self.assertEqual(["preferences_selection_ambiguous"],
                         manifest["stages"]["search_preferences_validation"]["error_codes"])
        self.assertEqual(["opportunity_snapshot_selection_ambiguous"],
                         manifest["stages"]["opportunity_snapshot_selection"]["error_codes"])

    def test_query_budget_exceeded_is_partial_and_plan_is_not_published(self):
        preferences = synthetic_preferences()
        preferences["preferred_roles"] = ["Backend Developer", "AI Engineer"]
        self._write(self.preferences_path, preferences)
        manifest, _ = pipeline.prepare_run(self.workspace, limits={
            "max_discovery_queries": 1, "max_opportunities_to_discover": 10,
            "max_opportunities_to_assess": 10, "max_retries": 1})
        stage = manifest["stages"]["discovery_plan_preparation"]
        self.assertEqual("partial", stage["status"])
        self.assertEqual(["query_budget_exceeded"], stage["error_codes"])
        self.assertEqual(["query_budget_exceeded"], stage["incomplete_reasons"])
        self.assertIsNone(manifest["artifacts"]["discovery_query_plan"])
        self.assertEqual("partial", manifest["run_status"])

    def test_discovery_target_limit_is_recorded_in_plan_not_query_budget(self):
        manifest, _ = pipeline.prepare_run(self.workspace, limits={
            "max_discovery_queries": 10, "max_opportunities_to_discover": 4,
            "max_opportunities_to_assess": 6, "max_retries": 0})
        plan_path = self.workspace / manifest["artifacts"]["discovery_query_plan"]["path"]
        plan = json.loads(plan_path.read_text())
        self.assertEqual(4, plan["target_maximum"])
        self.assertEqual(10, manifest["limits"]["max_discovery_queries"])
        self.assertEqual(6, manifest["limits"]["max_opportunities_to_assess"])

    def test_empty_plan_is_a_failed_stage(self):
        with patch.object(pipeline, "build_search_plan", return_value={"queries": []}):
            manifest, _ = pipeline.prepare_run(self.workspace)
        self.assertEqual(["empty_discovery_plan"],
                         manifest["stages"]["discovery_plan_preparation"]["error_codes"])

    def test_invalid_limits_are_rejected_before_manifest_creation(self):
        with self.assertRaisesRegex(PreparationError, "execution_limits_invalid"):
            pipeline.prepare_run(self.workspace, limits={**pipeline.DEFAULT_LIMITS,
                                                         "max_discovery_queries": 0})
        self.assertEqual([], list(self.discovery.glob("run_*-r*.json")))

    def test_manifest_schema_rejects_bad_reference_and_inconsistent_status(self):
        manifest, _ = pipeline.prepare_run(self.workspace)
        invalid = copy.deepcopy(manifest)
        invalid["inputs"]["candidate_profile"]["path"] = "/private/cv.json"
        self.assertEqual(["manifest_schema_invalid"], pipeline.validate_manifest(invalid))
        invalid = copy.deepcopy(manifest)
        invalid["run_status"] = "completed"
        self.assertEqual(["run_status_inconsistent"], pipeline.validate_manifest(invalid))

    def test_stage_transitions_record_interruption_and_enforce_retry_budget(self):
        manifest, path = pipeline.prepare_run(self.workspace)
        started = pipeline.transition_stage(manifest, "live_discovery", "running")
        self.assertEqual("running", started["run_status"])
        interrupted = pipeline.transition_stage(started, "live_discovery", "partial",
                                                reason="interrupted")
        self.assertEqual("partial", interrupted["run_status"])
        self.assertEqual(["interrupted"], interrupted["stages"]["live_discovery"]["incomplete_reasons"])
        resumed = pipeline.transition_stage(interrupted, "live_discovery", "running")
        self.assertEqual(2, resumed["stages"]["live_discovery"]["attempts"])
        paused_again = pipeline.transition_stage(resumed, "live_discovery", "partial",
                                                 reason="interrupted")
        with self.assertRaisesRegex(PreparationError, "retry_budget_exceeded"):
            pipeline.transition_stage(paused_again, "live_discovery", "running")
        revised_path = pipeline.save_run_manifest(resumed, self.workspace, previous_path=path)
        self.assertNotEqual(path, revised_path)
        self.assertTrue(path.exists())

    def test_invalid_transitions_and_missing_failure_details_are_rejected(self):
        manifest, _ = pipeline.prepare_run(self.workspace)
        with self.assertRaisesRegex(PreparationError, "invalid_stage_transition"):
            pipeline.transition_stage(manifest, "live_discovery", "completed")
        started = pipeline.transition_stage(manifest, "live_discovery", "running")
        with self.assertRaisesRegex(PreparationError, "failed_stage_requires_error_code"):
            pipeline.transition_stage(started, "live_discovery", "failed")
        with self.assertRaisesRegex(PreparationError, "incomplete_stage_requires_reason"):
            pipeline.transition_stage(started, "live_discovery", "partial")

    def test_failed_stage_retry_is_bounded_and_preserves_failure_code(self):
        manifest, _ = pipeline.prepare_run(self.workspace)
        started = pipeline.transition_stage(manifest, "live_discovery", "running")
        failed = pipeline.transition_stage(started, "live_discovery", "failed",
                                           error_code="web_tool_unavailable")
        retried = pipeline.transition_stage(failed, "live_discovery", "running")
        self.assertEqual(["web_tool_unavailable"],
                         retried["stages"]["live_discovery"]["error_codes"])
        failed_again = pipeline.transition_stage(retried, "live_discovery", "failed",
                                                 error_code="web_tool_unavailable")
        with self.assertRaisesRegex(PreparationError, "retry_budget_exceeded"):
            pipeline.transition_stage(failed_again, "live_discovery", "running")

    def test_manifest_publication_is_create_only(self):
        manifest, path = pipeline.prepare_run(self.workspace)
        with self.assertRaisesRegex(StorageError, "output_exists"):
            pipeline.save_run_manifest(manifest, self.workspace)
        self.assertTrue(path.exists())

    def test_cli_prepare_and_transition_commands(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = pipeline.main(["prepare", "--workspace", str(self.workspace)])
        self.assertEqual(0, code)
        prepared = json.loads(output.getvalue())
        self.assertEqual("prepared", prepared["status"])
        manifest_path = self.workspace / prepared["manifest"]
        output = io.StringIO()
        with redirect_stdout(output):
            code = pipeline.main(["transition", "--workspace", str(self.workspace),
                "--manifest", str(manifest_path), "--stage", "live_discovery",
                "--status", "running"])
        self.assertEqual(0, code)
        advanced = json.loads(output.getvalue())
        self.assertEqual("running", advanced["status"])
        self.assertTrue((self.workspace / advanced["manifest"]).exists())


if __name__ == "__main__":
    unittest.main()
