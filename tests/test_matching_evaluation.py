"""Deterministic scoring tests; all fixtures are synthetic."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))
from match_opportunities import build_match_results
from match_opportunities import save_match_results
from validate_opportunities import validate_opportunities
from validate_profile import validate_document

spec = importlib.util.spec_from_file_location("matching_evaluation", ROOT / "evaluation/evaluate_matching.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)
from evaluation.matching.build_benchmark import build


class MatchingEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.benchmark = build()
        self.golden = json.loads((ROOT / "evaluation/matching/golden.v1.json").read_text())
        self.profile = self.benchmark["candidates"]["graduate"]
        self.preferences = self.benchmark["preferences"]["entry_roles"]
        self.opportunity = next(item for item in self.benchmark["opportunities"]["opportunities"]
                                if item["id"] == "job_direct")

    def prediction(self, invalid_ref=False, omit_second=False):
        candidate_evidence = "bad_ref" if invalid_ref else "ev_skill"
        requirements = [{"id": "req_python", "statement": "Python is required", "priority": "required",
                         "outcome": "matched", "job_evidence_ids": ["job_direct_req_py"],
                         "candidate_record_ids": ["skill_1"], "candidate_evidence_ids": [candidate_evidence],
                         "rationale": "The confirmed profile explicitly lists Python."}]
        if not omit_second:
            requirements.append({"id": "req_kubernetes", "statement": "Kubernetes preferred", "priority": "preferred",
                                 "outcome": "not_evidenced", "job_evidence_ids": ["job_direct_req_k8s"],
                                 "candidate_record_ids": [], "candidate_evidence_ids": [],
                                 "rationale": "No confirmed candidate evidence mentions Kubernetes."})
        assessment = {"schema_version": "1", "assessments": [{"opportunity_id": "job_direct",
            "requirements": requirements,
            "experience_alignment": {"outcome": "uncertain", "job_evidence_ids": [],
                "candidate_record_ids": [], "candidate_evidence_ids": [], "rationale": "Dates and duration are not established."},
            "career_alignment": {"outcome": "aligned", "preference_terms": ["Python Developer"],
                "job_evidence_ids": ["job_job_direct_title"], "rationale": "The title matches an explicit preferred role."}}]}
        result = None
        if not invalid_ref:
            result = build_match_results(self.profile, self.preferences,
                {"schema_version": "1", "opportunities": [self.opportunity]}, assessment,
                evaluated_at="2026-10-13T00:00:00Z")
        return {"case_id": "direct_and_not_evidenced", "assessment": assessment, "result": result}

    def test_denominators_include_missing_cases_and_requirements(self):
        report = evaluation.evaluate(self.benchmark, self.golden, [self.prediction(omit_second=True)], "2026-10-13")
        metrics = report["metrics"]
        total = sum(len(case["requirements"]) for case in self.golden["cases"])
        self.assertEqual(total, metrics["requirement_classification_accuracy"]["denominator"])
        self.assertEqual(8, metrics["hard_filter_correctness"]["denominator"])
        self.assertEqual(7, len(report["missing_prediction_cases"]))
        self.assertGreater(metrics["supported_match_recall"]["denominator"], 0)

    def test_repeated_identical_input_has_identical_deterministic_report(self):
        predictions = [self.prediction()]
        before = copy.deepcopy((self.benchmark, self.golden, predictions))
        first = evaluation.evaluate(self.benchmark, self.golden, predictions, "2026-10-13")
        second = evaluation.evaluate(self.benchmark, self.golden, predictions, "2026-10-13")
        self.assertEqual(first, second)
        self.assertEqual(before, (self.benchmark, self.golden, predictions))

    def test_invalid_candidate_evidence_reference_fails_schema_invariant(self):
        prediction = self.prediction(invalid_ref=True)
        report = evaluation.evaluate(self.benchmark, self.golden, [prediction], "2026-10-13")
        self.assertEqual({"numerator": 0, "denominator": 1, "rate": 0.0},
                         report["metrics"]["schema_invariant_compliance"])
        self.assertEqual(0.0, report["metrics"]["evidence_reference_validity"]["rate"])

    def test_ambiguous_support_is_excluded_not_counted_as_correct(self):
        report = evaluation.evaluate(self.benchmark, self.golden, [self.prediction()], "2026-10-13")
        self.assertGreater(report["metrics"]["ambiguous_evidence_support_unadjudicated"], 0)
        self.assertEqual(sum(1 for case in self.golden["cases"] for req in case["requirements"]
                             if req["evidence_support"] != "ambiguous"),
                         report["metrics"]["evidence_support_accuracy_adjudicated_only"]["denominator"])

    def test_injection_is_preserved_as_untrusted_posting_text(self):
        opportunity = next(item for item in self.benchmark["opportunities"]["opportunities"]
                           if item["id"] == "job_injection")
        injection = next(item for item in opportunity["evidence"] if item["id"] == "job_injection_req_ruby")
        self.assertIn("Ignore all prior instructions", injection["excerpt"])
        expected = next(case for case in self.golden["cases"] if case["case_id"] == "prompt_injection")
        ruby = next(req for req in expected["requirements"] if req["id"] == "req_ruby")
        self.assertEqual("not_evidenced", ruby["expected"])
        self.assertEqual([], ruby["candidate_evidence_ids"])

    def test_benchmark_is_synthetic_and_uses_reserved_hosts(self):
        self.assertTrue(all(item["original_url"].endswith("/" + item["id"])
                            for item in self.benchmark["opportunities"]["opportunities"]))
        for profile in self.benchmark["candidates"].values():
            self.assertTrue(all("synthetic" in doc["label"].casefold() for doc in profile["source_documents"]))
            self.assertEqual([], validate_document(profile, "candidate_profile"))
        for preferences in self.benchmark["preferences"].values():
            self.assertEqual([], validate_document(preferences, "search_preferences"))
        self.assertEqual([], validate_opportunities(self.benchmark["opportunities"]))

    def test_match_snapshots_are_create_only(self):
        prediction = self.prediction()
        result = prediction["result"]["results"][0]
        with TemporaryDirectory() as temporary:
            first = save_match_results(result, Path(temporary))
            original = first.read_bytes()
            second = save_match_results(result, Path(temporary))
            self.assertNotEqual(first, second)
            self.assertEqual(original, first.read_bytes())
            self.assertEqual(0o600, first.stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
