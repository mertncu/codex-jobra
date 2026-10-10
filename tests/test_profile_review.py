"""Synthetic tests for explicit profile review and private snapshot persistence."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))
from review_profile import ReviewError, apply_review_batch, apply_review_operation, save_review_operation  # noqa: E402
from validate_profile import SECTIONS, records_for_downstream, validate_document  # noqa: E402


PROFILE = json.loads((ROOT / "tests/fixtures/candidate-profile.synthetic.json").read_text(encoding="utf-8"))


def apply(profile, action, **fields):
    return apply_review_operation(profile, {"action": action, **fields})


def review_all(profile):
    result = copy.deepcopy(profile)
    for evidence in profile["evidence"]:
        result = apply(result, "review_evidence", evidence_id=evidence["id"], decision="confirmed")
    for section in SECTIONS:
        for record in profile[section]:
            result = apply(result, "confirm_record", section=section, record_id=record["id"])
        result = apply(result, "confirm_section", section=section)
    return result


class ProfileReviewTests(unittest.TestCase):
    def test_confirm_requires_explicit_evidence_review(self):
        with self.assertRaisesRegex(ReviewError, "supporting_evidence_unreviewed"):
            apply(PROFILE, "confirm_record", section="education", record_id="edu_1")
        result = apply(PROFILE, "review_evidence", evidence_id="ev_school", decision="confirmed")
        result = apply(result, "confirm_record", section="education", record_id="edu_1")
        self.assertEqual("confirmed", result["education"][0]["review_status"])
        self.assertEqual("pending", PROFILE["education"][0]["review_status"])

    def test_correction_keeps_origin_and_source_evidence(self):
        result = apply(PROFILE, "review_evidence", evidence_id="ev_school", decision="confirmed")
        result = apply(result, "correct_record", section="education", record_id="edu_1",
                       changes={"institution": "Corrected Synthetic College", "period": "2020–2024"},
                       correction_note="User supplied corrected school and period")
        record = result["education"][0]
        self.assertEqual("corrected", record["review_status"])
        self.assertEqual("extracted", record["origin"])
        self.assertEqual(["ev_school"], record["evidence_ids"])
        self.assertEqual([], validate_document(result, "candidate_profile"))

    def test_evidence_correction_and_rejected_evidence(self):
        result = apply(PROFILE, "review_evidence", evidence_id="ev_school", decision="corrected",
                       remove_fields=["location"], correction_note="Source location was not reliable")
        self.assertEqual("corrected", result["evidence"][0]["review_status"])
        self.assertNotIn("location", result["evidence"][0])
        result = apply(PROFILE, "review_evidence", evidence_id="ev_school", decision="rejected")
        with self.assertRaisesRegex(ReviewError, "supporting_evidence_unreviewed"):
            apply(result, "confirm_record", section="education", record_id="edu_1")
        result = apply(result, "reject_record", section="education", record_id="edu_1")
        self.assertEqual([], validate_document(result, "candidate_profile"))

    def test_user_added_record_is_pending_and_requires_confirmation(self):
        result = apply(PROFILE, "add_record", section="technical_skills",
                       record={"id": "skill_added", "name": "Rust", "level": "unknown"})
        added = result["technical_skills"][-1]
        self.assertEqual(("user", "pending", []),
                         (added["origin"], added["review_status"], added["evidence_ids"]))
        result = apply(result, "confirm_record", section="technical_skills", record_id="skill_added")
        self.assertEqual("confirmed", result["technical_skills"][-1]["review_status"])

    def test_correction_can_remove_unsupported_optional_claim(self):
        profile = copy.deepcopy(PROFILE)
        profile["experience"][0]["period"] = "Uncertain dates"
        result = apply(profile, "review_evidence", evidence_id="ev_intern", decision="confirmed")
        result = apply(result, "correct_record", section="experience", record_id="exp_1",
                       remove_fields=["period"], correction_note="User cannot confirm dates")
        self.assertNotIn("period", result["experience"][0])
        self.assertEqual("corrected", result["experience"][0]["review_status"])

    def test_empty_section_requires_explicit_confirmation(self):
        profile = copy.deepcopy(PROFILE)
        profile["suggested_roles"] = []
        profile["evidence"] = [item for item in profile["evidence"] if item["id"] != "ev_role"]
        self.assertEqual("pending", profile["section_reviews"]["suggested_roles"])
        result = apply(profile, "confirm_section", section="suggested_roles")
        self.assertEqual("confirmed", result["section_reviews"]["suggested_roles"])
        self.assertEqual("pending", profile["section_reviews"]["suggested_roles"])

    def test_pending_record_blocks_section_and_finalization(self):
        with self.assertRaisesRegex(ReviewError, "pending_records"):
            apply(PROFILE, "confirm_section", section="education")
        with self.assertRaisesRegex(ReviewError, "pending_sections"):
            apply(PROFILE, "finalize", approved=True)

    def test_final_approval_required_and_no_accidental_verification(self):
        reviewed = review_all(PROFILE)
        self.assertEqual("draft", reviewed["verification_status"])
        for approval in (False, "true", None):
            with self.assertRaisesRegex(ReviewError, "final_approval_required"):
                apply(reviewed, "finalize", approved=approval)
        verified = apply(reviewed, "finalize", approved=True)
        self.assertEqual("verified", verified["verification_status"])
        self.assertEqual([], validate_document(verified, "candidate_profile"))

    def test_rejected_record_retained_but_downstream_excluded(self):
        result = copy.deepcopy(PROFILE)
        for item in PROFILE["evidence"]:
            result = apply(result, "review_evidence", evidence_id=item["id"], decision="confirmed")
        result = apply(result, "reject_record", section="education", record_id="edu_1")
        for section in SECTIONS:
            for record in PROFILE[section]:
                if record["id"] != "edu_1":
                    result = apply(result, "confirm_record", section=section, record_id=record["id"])
            result = apply(result, "confirm_section", section=section)
        verified = apply(result, "finalize", approved=True)
        self.assertEqual("rejected", verified["education"][0]["review_status"])
        self.assertEqual([], records_for_downstream(verified, "education"))
        self.assertEqual(1, len(records_for_downstream(verified, "experience")))

    def test_modifying_confirmed_section_resets_review(self):
        result = review_all(PROFILE)
        result = apply(result, "add_record", section="education", record={"id": "edu_new", "institution": "Invented College"})
        self.assertEqual("pending", result["section_reviews"]["education"])
        with self.assertRaisesRegex(ReviewError, "pending_sections"):
            apply(result, "finalize", approved=True)

    def test_invalid_update_does_not_mutate_input(self):
        original = copy.deepcopy(PROFILE)
        with self.assertRaisesRegex(ReviewError, "invalid_review_result"):
            apply(PROFILE, "add_record", section="projects", record={"id": "proj_1", "name": "Duplicate"})
        self.assertEqual(original, PROFILE)

    def test_verified_profile_is_locked(self):
        verified = apply(review_all(PROFILE), "finalize", approved=True)
        with self.assertRaisesRegex(ReviewError, "verified_profile_locked"):
            apply(verified, "add_record", section="projects", record={"id": "proj_new", "name": "New"})
        with self.assertRaisesRegex(ReviewError, "verified_profile_locked"):
            apply(verified, "finalize", approved=True)

    def test_private_snapshot_is_atomic_and_never_replaces_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profiles = root / ".jobra/profiles"
            profiles.mkdir(parents=True)
            source = profiles / "draft-source.json"
            source.write_text(json.dumps(PROFILE), encoding="utf-8")
            operation = root / ".jobra/operation.json"
            operation.write_text(json.dumps({"action": "review_evidence", "evidence_id": "ev_school", "decision": "confirmed"}), encoding="utf-8")
            output = save_review_operation(source, operation, root)
            self.assertNotEqual(source, output)
            self.assertEqual(PROFILE, json.loads(source.read_text(encoding="utf-8")))
            self.assertEqual("confirmed", json.loads(output.read_text(encoding="utf-8"))["evidence"][0]["review_status"])
            self.assertEqual(0o600, output.stat().st_mode & 0o777)
            before = set(profiles.iterdir())
            operation.write_text(json.dumps({"action": "finalize", "approved": True}), encoding="utf-8")
            with self.assertRaisesRegex(ReviewError, "pending_sections"):
                save_review_operation(output, operation, root)
            self.assertEqual(before, set(profiles.iterdir()))

    def test_private_operation_path_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profiles = root / ".jobra/profiles"
            profiles.mkdir(parents=True)
            source = profiles / "draft.json"
            source.write_text(json.dumps(PROFILE), encoding="utf-8")
            operation = root / "operation.json"
            operation.write_text(json.dumps({"action": "finalize", "approved": True}), encoding="utf-8")
            with self.assertRaisesRegex(ReviewError, "unsafe_input_path"):
                save_review_operation(source, operation, root)

    def test_batch_applies_ordered_decisions_and_writes_one_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profiles = root / ".jobra/profiles"
            profiles.mkdir(parents=True)
            source = profiles / "draft-synthetic.json"
            source.write_text(json.dumps(PROFILE), encoding="utf-8")
            request = root / ".jobra/review-batch.json"
            request.write_text(json.dumps({"operations": [
                {"action": "review_evidence", "evidence_id": "ev_school", "decision": "confirmed"},
                {"action": "confirm_record", "section": "education", "record_id": "edu_1"},
                {"action": "confirm_section", "section": "education"},
            ]}), encoding="utf-8")
            output = save_review_operation(source, request, root)
            self.assertEqual(2, len(list(profiles.glob("*.json"))))
            self.assertEqual(PROFILE, json.loads(source.read_text(encoding="utf-8")))
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("draft", result["verification_status"])
            self.assertEqual("confirmed", result["section_reviews"]["education"])
            self.assertEqual([], validate_document(result, "candidate_profile"))
            self.assertEqual(0o600, output.stat().st_mode & 0o777)

    def test_cli_accepts_batch_and_reports_only_status_and_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profiles = root / ".jobra/profiles"
            profiles.mkdir(parents=True)
            source = profiles / "draft-synthetic.json"
            source.write_text(json.dumps(PROFILE), encoding="utf-8")
            request = root / ".jobra/review-batch.json"
            request.write_text(json.dumps({"operations": [
                {"action": "review_evidence", "evidence_id": "ev_school", "decision": "confirmed"},
                {"action": "confirm_record", "section": "education", "record_id": "edu_1"},
            ]}), encoding="utf-8")
            process = subprocess.run(
                [sys.executable, str(ROOT / "skills/jobra/scripts/review_profile.py"),
                 str(source), str(request), "--workspace", str(root)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, process.returncode)
            self.assertEqual("", process.stderr)
            output = json.loads(process.stdout)
            self.assertEqual({"status", "output"}, set(output))
            self.assertEqual("draft", output["status"])
            self.assertEqual(2, len(list(profiles.glob("*.json"))))

    def test_batch_partial_failure_rolls_back_without_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profiles = root / ".jobra/profiles"
            profiles.mkdir(parents=True)
            source = profiles / "draft-synthetic.json"
            source.write_text(json.dumps(PROFILE), encoding="utf-8")
            request = root / ".jobra/review-batch.json"
            request.write_text(json.dumps({"operations": [
                {"action": "review_evidence", "evidence_id": "ev_school", "decision": "confirmed"},
                {"action": "confirm_record", "section": "education", "record_id": "missing"},
            ]}), encoding="utf-8")
            before = set(profiles.iterdir())
            with self.assertRaisesRegex(ReviewError, "record_not_found"):
                save_review_operation(source, request, root)
            self.assertEqual(before, set(profiles.iterdir()))
            self.assertEqual(PROFILE, json.loads(source.read_text(encoding="utf-8")))

    def test_batch_invariant_failure_rolls_back_in_memory(self):
        original = copy.deepcopy(PROFILE)
        operations = [
            {"action": "review_evidence", "evidence_id": "ev_school", "decision": "confirmed"},
            {"action": "add_record", "section": "projects",
             "record": {"id": "edu_1", "name": "Duplicate synthetic ID"}},
        ]
        with self.assertRaisesRegex(ReviewError, "invalid_review_result"):
            apply_review_batch(PROFILE, operations)
        self.assertEqual(original, PROFILE)

    def test_batch_cannot_finalize_or_supply_implicit_approval(self):
        reviewed = review_all(PROFILE)
        with self.assertRaisesRegex(ReviewError, "batch_finalization_forbidden"):
            apply_review_batch(reviewed, [{"action": "finalize", "approved": True}])
        with self.assertRaisesRegex(ReviewError, "invalid_operation"):
            apply_review_batch(PROFILE, [{"action": "confirm_section", "section": "education", "approved": True}])
        self.assertEqual("draft", reviewed["verification_status"])
        verified = apply(reviewed, "finalize", approved=True)
        with self.assertRaisesRegex(ReviewError, "verified_profile_locked"):
            apply_review_batch(verified, [{"action": "confirm_section", "section": "education"}])

    def test_batch_finalization_failure_writes_nothing_and_preserves_verified_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profiles = root / ".jobra/profiles"
            profiles.mkdir(parents=True)
            source = profiles / "draft-synthetic.json"
            source.write_text(json.dumps(PROFILE), encoding="utf-8")
            request = root / ".jobra/review-batch.json"
            request.write_text(json.dumps({"operations": [
                {"action": "review_evidence", "evidence_id": "ev_school", "decision": "confirmed"},
                {"action": "finalize", "approved": True},
            ]}), encoding="utf-8")
            with self.assertRaisesRegex(ReviewError, "batch_finalization_forbidden"):
                save_review_operation(source, request, root)
            self.assertEqual([source], list(profiles.glob("*.json")))
            self.assertEqual(PROFILE, json.loads(source.read_text(encoding="utf-8")))

            verified = apply(review_all(PROFILE), "finalize", approved=True)
            locked = profiles / "verified-existing.json"
            locked.write_text(json.dumps(verified), encoding="utf-8")
            before = set(profiles.iterdir())
            request.write_text(json.dumps({"operations": [
                {"action": "confirm_section", "section": "education"},
            ]}), encoding="utf-8")
            with self.assertRaisesRegex(ReviewError, "verified_profile_locked"):
                save_review_operation(locked, request, root)
            self.assertEqual(before, set(profiles.iterdir()))
            self.assertEqual(verified, json.loads(locked.read_text(encoding="utf-8")))

    def test_invalid_or_empty_batch_has_no_effect(self):
        for operations in ([], {}, "not a list", [None]):
            with self.assertRaises(ReviewError):
                apply_review_batch(PROFILE, operations)
        self.assertEqual("pending", PROFILE["evidence"][0]["review_status"])

    def test_end_to_end_synthetic_snapshots_and_verified_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profiles = root / ".jobra/profiles"
            profiles.mkdir(parents=True)
            current = profiles / "draft-synthetic.json"
            synthetic = copy.deepcopy(PROFILE)
            synthetic["suggested_roles"] = []
            synthetic["evidence"] = [item for item in synthetic["evidence"] if item["id"] != "ev_role"]
            current.write_text(json.dumps(synthetic), encoding="utf-8")
            operation_file = root / ".jobra/decision.json"

            def decision(action, **fields):
                nonlocal current
                operation_file.write_text(json.dumps({"action": action, **fields}), encoding="utf-8")
                current = save_review_operation(current, operation_file, root)

            for item in synthetic["evidence"]:
                decision("review_evidence", evidence_id=item["id"], decision="confirmed")
            decision("correct_record", section="education", record_id="edu_1",
                     changes={"institution": "Corrected Synthetic College"},
                     correction_note="User corrected school name")
            decision("reject_record", section="experience", record_id="exp_1")
            decision("confirm_record", section="projects", record_id="proj_1")
            decision("confirm_record", section="technical_skills", record_id="skill_1")
            decision("add_record", section="projects", record={"id": "proj_added", "name": "User project"})
            decision("confirm_record", section="projects", record_id="proj_added")
            for section in SECTIONS:
                decision("confirm_section", section=section)
            reviewed = json.loads(current.read_text(encoding="utf-8"))
            self.assertEqual("draft", reviewed["verification_status"])
            decision("finalize", approved=True)
            verified = json.loads(current.read_text(encoding="utf-8"))
            self.assertTrue(current.name.startswith("verified-"))
            self.assertEqual([], validate_document(verified, "candidate_profile"))
            self.assertEqual([], records_for_downstream(verified, "experience"))
            self.assertEqual(2, len(records_for_downstream(verified, "projects")))
            self.assertEqual("rejected", verified["experience"][0]["review_status"])
            previous = set(profiles.iterdir())
            operation_file.write_text(json.dumps({"action": "add_record", "section": "projects",
                                                  "record": {"id": "too_late", "name": "Too late"}}), encoding="utf-8")
            with self.assertRaisesRegex(ReviewError, "verified_profile_locked"):
                save_review_operation(current, operation_file, root)
            self.assertEqual(previous, set(profiles.iterdir()))


if __name__ == "__main__":
    unittest.main()
