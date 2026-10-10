"""Synthetic contract tests. Run with Python unittest; jsonschema is test-only."""

import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/jobra/scripts/validate_profile.py"
SPEC = importlib.util.spec_from_file_location("validate_profile", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def load_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


PROFILE_SCHEMA = load_json("skills/jobra/references/candidate-profile.schema.json")
PREFERENCES_SCHEMA = load_json("skills/jobra/references/search-preferences.schema.json")
PROFILE = load_json("tests/fixtures/candidate-profile.synthetic.json")
PREFERENCES = load_json("tests/fixtures/search-preferences.synthetic.json")


class DataContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        jsonschema.Draft202012Validator.check_schema(PROFILE_SCHEMA)
        jsonschema.Draft202012Validator.check_schema(PREFERENCES_SCHEMA)

    def test_synthetic_fixtures(self):
        jsonschema.validate(PROFILE, PROFILE_SCHEMA)
        jsonschema.validate(PREFERENCES, PREFERENCES_SCHEMA)
        self.assertEqual([], MODULE.validate_profile_invariants(PROFILE))
        self.assertEqual([], MODULE.validate_document(PROFILE, "candidate_profile"))
        self.assertEqual([], MODULE.validate_document(PREFERENCES, "search_preferences"))

    def test_location_can_be_omitted_without_changing_existing_v1(self):
        profile = copy.deepcopy(PROFILE)
        profile["evidence"][0].pop("location")
        self.assertEqual([], MODULE.validate_document(profile, "candidate_profile"))
        self.assertEqual([], MODULE.validate_document(PROFILE, "candidate_profile"))

    def test_corrected_extraction_retains_origin_and_provenance(self):
        profile = copy.deepcopy(PROFILE)
        record = profile["education"][0]
        record["institution"] = "Corrected Example College"
        record["review_status"] = "corrected"
        record["correction_note"] = "User corrected institution name"
        profile["evidence"][0]["review_status"] = "corrected"
        profile["evidence"][0]["correction_note"] = "Source name was misread"
        self.assertEqual("extracted", record["origin"])
        self.assertEqual(["ev_school"], record["evidence_ids"])
        self.assertEqual([], MODULE.validate_document(profile, "candidate_profile"))

    def test_schema_validation_precedes_invariant_checks(self):
        profile = copy.deepcopy(PROFILE)
        profile["education"][0]["evidence_ids"] = "not an array"
        errors = MODULE.validate_document(profile, "candidate_profile")
        self.assertTrue(any("type validation failed" in issue for issue in errors))
        self.assertFalse(any("requires evidence" in issue for issue in errors))

    def test_format_validation_rejects_bad_project_url(self):
        profile = copy.deepcopy(PROFILE)
        profile["projects"][0]["url"] = "not a uri"
        errors = MODULE.validate_document(profile, "candidate_profile")
        self.assertTrue(any("format validation failed" in issue for issue in errors))

    def test_schema_errors_hide_private_values(self):
        profile = copy.deepcopy(PROFILE)
        secret = "PRIVATE_CV_TEXT_DO_NOT_LOG"
        profile["projects"][0]["url"] = secret
        profile["education"][0]["institution"] = ""
        errors = MODULE.validate_document(profile, "candidate_profile")
        self.assertTrue(errors)
        self.assertNotIn(secret, " ".join(errors))
        self.assertNotIn("Example University", " ".join(errors))

    def test_profile_rejects_preferences_and_freeform_proficiency(self):
        profile = copy.deepcopy(PROFILE)
        profile["preferred_roles"] = ["Developer"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(profile, PROFILE_SCHEMA)
        profile = copy.deepcopy(PROFILE)
        profile["technical_skills"][0]["level"] = "expert"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(profile, PROFILE_SCHEMA)

    def test_preferences_reject_profile_fields(self):
        preferences = copy.deepcopy(PREFERENCES)
        preferences["evidence"] = []
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(preferences, PREFERENCES_SCHEMA)

    def test_unknown_evidence_and_document_references(self):
        profile = copy.deepcopy(PROFILE)
        profile["evidence"][0]["source_document_id"] = "missing"
        profile["education"][0]["evidence_ids"] = ["unknown"]
        issues = MODULE.validate_profile_invariants(profile)
        self.assertTrue(any("unknown document" in issue for issue in issues))
        self.assertTrue(any("unknown evidence" in issue for issue in issues))

    def test_duplicate_record_ids(self):
        profile = copy.deepcopy(PROFILE)
        profile["projects"][0]["id"] = profile["education"][0]["id"]
        self.assertTrue(any("duplicate identifier" in issue for issue in MODULE.validate_profile_invariants(profile)))

    def test_extracted_record_requires_evidence(self):
        profile = copy.deepcopy(PROFILE)
        profile["education"][0]["evidence_ids"] = []
        self.assertTrue(any("requires evidence" in issue for issue in MODULE.validate_profile_invariants(profile)))

    def test_verification_requires_all_reviews(self):
        profile = copy.deepcopy(PROFILE)
        profile["verification_status"] = "verified"
        issues = MODULE.validate_profile_invariants(profile)
        self.assertTrue(any("section_reviews" in issue for issue in issues))
        self.assertTrue(any("pending evidence" in issue for issue in issues))
        self.assertTrue(any("pending record" in issue for issue in issues))

    def test_verified_profile_with_reviewed_inference(self):
        profile = copy.deepcopy(PROFILE)
        profile["verification_status"] = "verified"
        profile["section_reviews"] = dict.fromkeys(profile["section_reviews"], "confirmed")
        for item in profile["evidence"]:
            item["review_status"] = "confirmed"
        for section in MODULE.SECTIONS:
            for record in profile[section]:
                record["review_status"] = "confirmed"
        jsonschema.validate(profile, PROFILE_SCHEMA)
        self.assertEqual([], MODULE.validate_profile_invariants(profile))

    def test_rejected_evidence_cannot_support_accepted_record(self):
        profile = copy.deepcopy(PROFILE)
        profile["evidence"][0]["review_status"] = "rejected"
        profile["education"][0]["review_status"] = "confirmed"
        self.assertTrue(any("rejected evidence" in issue for issue in MODULE.validate_profile_invariants(profile)))

    def test_rejected_records_remain_stored_but_are_excluded_downstream(self):
        profile = copy.deepcopy(PROFILE)
        profile["verification_status"] = "verified"
        profile["section_reviews"] = dict.fromkeys(profile["section_reviews"], "confirmed")
        for item in profile["evidence"]:
            item["review_status"] = "confirmed"
        for section in MODULE.SECTIONS:
            for record in profile[section]:
                record["review_status"] = "confirmed"
        rejected = profile["education"][0]
        rejected["review_status"] = "rejected"
        self.assertEqual([], MODULE.validate_document(profile, "candidate_profile"))
        self.assertIn(rejected, profile["education"])
        self.assertEqual([], MODULE.records_for_downstream(profile, "education"))
        self.assertEqual(["exp_1"], [r["id"] for r in MODULE.records_for_downstream(profile, "experience")])

    def test_downstream_view_refuses_draft_profile(self):
        with self.assertRaises(ValueError):
            MODULE.records_for_downstream(PROFILE, "education")

    def test_corrected_record_requires_note(self):
        profile = copy.deepcopy(PROFILE)
        profile["education"][0]["review_status"] = "corrected"
        self.assertTrue(any("correction_note" in issue for issue in MODULE.validate_profile_invariants(profile)))

    def test_unreviewed_extracted_proficiency_is_not_allowed(self):
        profile = copy.deepcopy(PROFILE)
        profile["technical_skills"][0]["level"] = "advanced"
        self.assertTrue(any("proficiency requires user review" in issue for issue in MODULE.validate_profile_invariants(profile)))

    def test_invariant_errors_do_not_contain_raw_excerpt(self):
        profile = copy.deepcopy(PROFILE)
        profile["evidence"][0]["source_document_id"] = "missing"
        errors = MODULE.validate_profile_invariants(profile)
        self.assertNotIn(profile["evidence"][0]["excerpt"], " ".join(errors))


if __name__ == "__main__":
    unittest.main()
