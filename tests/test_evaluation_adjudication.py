"""Review-packet and human-judgment invariants using synthetic inputs only."""

import copy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))
from adjudicate_evaluation import (  # noqa: E402
    AdjudicationError, _digest, build_packet, summarize, validate_judgments,
)
from evaluate_candidate import evaluate_dataset  # noqa: E402
from ingest_resume import ingest_resume  # noqa: E402


RESUMES = ROOT / "evaluation/resumes"
SOURCE = RESUMES / "new-graduate.md"


def fixture():
    ingested = ingest_resume(SOURCE)
    source = ingested["source_document"]
    profile = {
        "schema_version": "1", "verification_status": "draft",
        "section_reviews": {section: "pending" for section in
                            ("education", "experience", "projects", "technical_skills", "suggested_roles")},
        "source_documents": [source],
        "evidence": [
            {"id": "ev_edu", "source_document_id": source["id"], "location": "line 5",
             "excerpt": "Northbridge University", "extraction": "explicit", "review_status": "pending"},
            {"id": "ev_skill", "source_document_id": source["id"], "location": "line 19",
             "excerpt": "Python", "extraction": "explicit", "review_status": "pending"},
        ],
        "education": [{"id": "edu_one", "origin": "extracted", "review_status": "pending",
                       "evidence_ids": ["ev_edu"], "institution": "Northbridge University",
                       "field": "Computer Science"}],
        "experience": [], "projects": [], "suggested_roles": [],
        "technical_skills": [{"id": "skill_one", "origin": "extracted", "review_status": "pending",
                              "evidence_ids": ["ev_skill"], "name": "Python", "level": "unknown"}],
    }
    full = json.loads((ROOT / "evaluation/golden.v1.json").read_text(encoding="utf-8"))
    case = full["cases"][0]
    subset = {"dataset_version": full["dataset_version"], "cases": [{**case, "claims": [
        next(item for item in case["claims"] if item["id"] == claim_id)
        for claim_id in ("ng_edu_school", "ng_skill_python")]}]}
    return profile, subset


def decisions(packet, judgments):
    return {"packet_id": packet["packet_id"], "reviewer_type": "human",
            "reviewer": "Independent reviewer", "reviewed_at": "2026-10-11",
            "judgments": judgments}


def judgment(item, category, rationale="Checked the original source and claim."):
    return {"item_id": item["id"], "category": category, "rationale": rationale,
            "source_ref": item["sources"][0]["ref"]}


class AdjudicationTests(unittest.TestCase):
    def setUp(self):
        profile, dataset = fixture()
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        predictions = Path(self.temporary.name)
        (predictions / "new-graduate.json").write_text(json.dumps(profile), encoding="utf-8")
        self.baseline = evaluate_dataset(dataset, RESUMES, predictions, "2026-10-11")
        self.packet = build_packet(dataset, RESUMES, predictions, self.baseline, "baseline-hash")
        self.claim = next(item for item in self.packet["items"] if item["kind"] == "unmatched_claim")
        self.evidence = next(item for item in self.packet["items"] if item["kind"] == "evidence_mismatch")

    def test_packet_requires_reproducible_baseline_and_never_assigns_categories(self):
        self.assertEqual(3, len(self.packet["items"]))
        self.assertEqual(1, sum(item["kind"] == "unmatched_claim" for item in self.packet["items"]))
        self.assertEqual(2, sum(item["kind"] == "evidence_mismatch" for item in self.packet["items"]))
        self.assertTrue(all("category" not in item for item in self.packet["items"]))
        self.assertEqual("line 5", self.claim["sources"][0]["location"])
        altered = copy.deepcopy(self.baseline)
        altered["metrics"]["claim_precision"]["numerator"] += 1
        profile, dataset = fixture()
        with self.assertRaisesRegex(AdjudicationError, "baseline_mismatch"):
            build_packet(dataset, RESUMES, Path(self.temporary.name), altered, "baseline-hash")

    def test_invalid_categories_and_missing_rationale_or_source(self):
        for item, category in ((self.claim, "sufficient_support"),
                               (self.evidence, "valid_extra"),
                               (self.claim, "automatic_valid")):
            with self.subTest(item=item["id"], category=category):
                with self.assertRaisesRegex(AdjudicationError, "invalid_category"):
                    validate_judgments(self.packet, decisions(self.packet, [judgment(item, category)]))
        bad = judgment(self.claim, "valid_extra", "  ")
        with self.assertRaisesRegex(AdjudicationError, "rationale_required"):
            validate_judgments(self.packet, decisions(self.packet, [bad]))
        bad = judgment(self.claim, "valid_extra")
        bad["source_ref"] = "other_source"
        with self.assertRaisesRegex(AdjudicationError, "invalid_source_reference"):
            validate_judgments(self.packet, decisions(self.packet, [bad]))

    def test_duplicate_and_conflicting_judgments_rejected(self):
        one = judgment(self.claim, "valid_extra")
        two = judgment(self.claim, "incorrect")
        for pair in ((one, one), (one, two)):
            with self.assertRaisesRegex(AdjudicationError, "duplicate_judgment"):
                validate_judgments(self.packet, decisions(self.packet, list(pair)))

    def test_partial_review_and_adjusted_denominators_preserve_strict_scores(self):
        original = copy.deepcopy(self.baseline)
        pending = summarize(self.packet, self.baseline)
        self.assertEqual(0, pending["review_counts"]["adjudicated_items"])
        self.assertEqual(3, pending["review_counts"]["unresolved_items"])
        reviewed = summarize(self.packet, self.baseline, decisions(self.packet, [
            judgment(self.claim, "valid_extra"),
            judgment(self.evidence, "sufficient_support"),
        ]))
        self.assertEqual(2, reviewed["review_counts"]["adjudicated_items"])
        self.assertEqual(1, reviewed["review_counts"]["unresolved_items"])
        self.assertEqual({"numerator": 3, "denominator": 3, "value": 1.0},
                         reviewed["review_adjusted_metrics"]["claim_precision_lower_bound"])
        self.assertEqual({"numerator": 1, "denominator": 2, "value": 0.5},
                         reviewed["review_adjusted_metrics"]["evidence_accuracy_on_strict_matches_lower_bound"])
        self.assertEqual(original["metrics"], reviewed["original_strict_metrics"])
        self.assertEqual(original, self.baseline)

    def test_incorrect_unsupported_and_ambiguous_do_not_gain_credit(self):
        extra = copy.deepcopy(self.claim)
        extra["id"] = "new-graduate:claim:extra"
        packet = copy.deepcopy(self.packet)
        packet["items"].append(extra)
        body = {key: value for key, value in packet.items() if key != "packet_id"}
        packet["packet_id"] = _digest(body)
        report = summarize(packet, self.baseline, decisions(packet, [
            judgment(self.claim, "incorrect"), judgment(extra, "unsupported"),
            judgment(self.evidence, "ambiguous"),
        ]))
        self.assertEqual(2, report["review_counts"]["confirmed_incorrect_or_unsupported"])
        self.assertEqual(2, report["review_counts"]["unresolved_items"])
        self.assertEqual(self.baseline["metrics"]["claim_precision"],
                         report["review_adjusted_metrics"]["claim_precision_lower_bound"])
        self.assertEqual(self.baseline["metrics"]["evidence_attribution_accuracy"],
                         report["review_adjusted_metrics"]["evidence_accuracy_on_strict_matches_lower_bound"])

    def test_review_attestation_required(self):
        bad = decisions(self.packet, [])
        bad["reviewer_type"] = "codex"
        with self.assertRaisesRegex(AdjudicationError, "reviewer_required"):
            validate_judgments(self.packet, bad)


if __name__ == "__main__":
    unittest.main()
