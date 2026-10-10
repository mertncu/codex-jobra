"""Deterministic, privacy-safe scoring of Jobra setup drafts against synthetic gold."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import json
from pathlib import Path
import re
from uuid import uuid4

from ingest_resume import IngestionError, ingest_resume
from local_storage import StorageError, write_private_json_atomic
from save_profile_draft import validate_draft_against_ingestion
from validate_profile import validate_document


# Only literal, profile-backed facts are scored. Summaries, proficiency and
# suggested roles require human judgment and are intentionally out of scope.
SCORED_FIELDS = {
    "education": ("institution", "credential", "field", "period"),
    "experience": ("organization", "role", "kind", "period"),
    "projects": ("name", "url"),
    "technical_skills": ("name",),
}


class EvaluationError(Exception):
    """Fixed, privacy-safe evaluation failure code."""


def normalize(value: str) -> str:
    """Casefold and collapse whitespace; no fuzzy or semantic equivalence."""
    return " ".join(value.casefold().split())


def _key(section: str, field: str, value: str) -> tuple[str, str, str]:
    return section, field, normalize(value)


def _prediction_claims(profile: dict) -> list[dict]:
    claims = []
    for section, fields in SCORED_FIELDS.items():
        for record in profile[section]:
            if record["review_status"] == "rejected":
                continue
            for field in fields:
                if field in record:
                    claims.append({"section": section, "field": field,
                                   "value": record[field], "evidence_ids": record["evidence_ids"]})
    return claims


def _source_evidence_ok(item: dict, ingestion: dict) -> bool:
    if item.get("source_document_id") != ingestion["source_document"]["id"]:
        return False
    location, excerpt = item.get("location"), item.get("excerpt")
    return bool(location and excerpt and any(
        segment["location"] == location and excerpt in segment["text"]
        for segment in ingestion["segments"]
    ))


def _gold_evidence_ok(claim: dict, gold: dict, evidence_by_id: dict, ingestion: dict) -> bool:
    for evidence_id in claim["evidence_ids"]:
        item = evidence_by_id.get(evidence_id)
        if not item or not _source_evidence_ok(item, ingestion):
            continue
        for expected in gold["evidence"]:
            if item["location"] == expected["location"] and normalize(expected["quote"]) in normalize(item["excerpt"]):
                return True
    return False


def validate_dataset(dataset: dict, resume_dir: Path) -> None:
    """Check independently written gold labels against source text."""
    if dataset.get("dataset_version") != "1.0.0" or not isinstance(dataset.get("cases"), list):
        raise EvaluationError("invalid_dataset")
    case_ids = set()
    for case in dataset["cases"]:
        try:
            case_id, resume = case["id"], case["resume"]
            if not re.fullmatch(r"[a-z][a-z0-9-]+", case_id) or resume != case_id + ".md" or case_id in case_ids:
                raise ValueError
            case_ids.add(case_id)
            ingestion = ingest_resume(resume_dir / resume)
            claim_ids = set()
            for claim in case["claims"]:
                if claim["id"] in claim_ids or claim["field"] not in SCORED_FIELDS[claim["section"]] or not claim["value"]:
                    raise ValueError
                claim_ids.add(claim["id"])
                if not claim["evidence"]:
                    raise ValueError
                for expected in claim["evidence"]:
                    if not any(segment["location"] == expected["location"] and expected["quote"] in segment["text"]
                               for segment in ingestion["segments"]):
                        raise ValueError
            for forbidden in case.get("forbidden_claims", []):
                if forbidden["field"] not in SCORED_FIELDS[forbidden["section"]]:
                    raise ValueError
        except (KeyError, TypeError, ValueError, IndexError, IngestionError, OSError):
            raise EvaluationError("invalid_dataset") from None


def evaluate_case(case: dict, profile: object, ingestion: dict) -> dict:
    """Score a saved setup draft. Invalid profiles receive diagnostics, not claim metrics."""
    issues = validate_document(profile, "candidate_profile")
    result = {"case_id": case["id"], "schema_invariant_pass": not issues,
              "draft_source_pass": False, "validation_error_count": len(issues),
              "failure_categories": []}
    if issues:
        result["failure_categories"].append("invalid_schema_or_invariant")
        return result
    source_issues = validate_draft_against_ingestion(profile, ingestion)
    result["draft_source_pass"] = not source_issues
    if source_issues:
        result["failure_categories"].append("invalid_draft_or_source")
    predicted = _prediction_claims(profile)
    evidence_by_id = {item["id"]: item for item in profile["evidence"]}
    golden_by_key = defaultdict(list)
    for gold in case["claims"]:
        for value in (gold["value"], *gold.get("aliases", [])):
            golden_by_key[_key(gold["section"], gold["field"], value)].append(gold)
    forbidden = {_key(item["section"], item["field"], item["value"]): item["category"]
                 for item in case.get("forbidden_claims", [])}
    matched_ids = set()
    matched = grounded = unsupported = unmatched = 0
    wrong_evidence_ids = []
    forbidden_categories = []
    for index, claim in enumerate(predicted):
        key = _key(claim["section"], claim["field"], claim["value"])
        gold = next((item for item in golden_by_key[key] if item["id"] not in matched_ids), None)
        if gold is not None:
            matched += 1
            matched_ids.add(gold["id"])
            if _gold_evidence_ok(claim, gold, evidence_by_id, ingestion):
                grounded += 1
            else:
                wrong_evidence_ids.append(gold["id"])
            continue
        if key in forbidden:
            unsupported += 1
            forbidden_categories.append(forbidden[key])
        elif not any(_source_evidence_ok(evidence_by_id.get(ref, {}), ingestion) for ref in claim["evidence_ids"]):
            unsupported += 1
        else:
            unmatched += 1  # May be a valid unlabelled or semantically equivalent claim.
    if wrong_evidence_ids:
        result["failure_categories"].append("incorrect_evidence")
    if unsupported:
        result["failure_categories"].append("unsupported_claim")
    if unmatched:
        result["failure_categories"].append("unmatched_needs_human_review")
    result.update({"predicted_claims": len(predicted), "gold_claims": len(case["claims"]),
                   "matched_claims": matched, "grounded_matches": grounded,
                   "unsupported_claims": unsupported, "unmatched_for_review": unmatched,
                   "missing_gold_ids": sorted(item["id"] for item in case["claims"] if item["id"] not in matched_ids),
                   "incorrect_evidence_gold_ids": sorted(wrong_evidence_ids),
                   "forbidden_categories": sorted(forbidden_categories)})
    return result


def _ratio(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def evaluate_dataset(dataset: dict, resume_dir: Path, predictions_dir: Path,
                     evaluation_date: str) -> dict:
    validate_dataset(dataset, resume_dir)
    try:
        date.fromisoformat(evaluation_date)
    except ValueError:
        raise EvaluationError("invalid_date") from None
    results = []
    for case in dataset["cases"]:
        path = predictions_dir / (case["id"] + ".json")
        if not path.exists():
            results.append({"case_id": case["id"], "status": "missing_prediction"})
            continue
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            results.append({"case_id": case["id"], "status": "unreadable_prediction",
                            "failure_categories": ["unreadable_prediction"]})
            continue
        result = evaluate_case(case, profile, ingest_resume(resume_dir / case["resume"]))
        result["status"] = "evaluated"
        results.append(result)
    attempted = [item for item in results if item["status"] != "missing_prediction"]
    valid = [item for item in attempted if item.get("schema_invariant_pass")]
    scored = [item for item in valid if "matched_claims" in item]
    total = lambda name: sum(item[name] for item in scored)
    metrics = {
        "claim_precision": _ratio(total("matched_claims"), total("predicted_claims")),
        "claim_recall": _ratio(total("matched_claims"), total("gold_claims")),
        "evidence_attribution_accuracy": _ratio(total("grounded_matches"), total("matched_claims")),
        "unsupported_claim_rate": _ratio(total("unsupported_claims"), total("predicted_claims")),
        "schema_invariant_pass_rate": _ratio(len(valid), len(attempted)),
        "draft_source_pass_rate": _ratio(sum(bool(item.get("draft_source_pass")) for item in attempted), len(attempted)),
    }
    return {"dataset_version": dataset["dataset_version"], "evaluation_date": evaluation_date,
            "resume_count": len(dataset["cases"]), "prediction_count": len(attempted),
            "scored_prediction_count": len(scored), "metrics": metrics, "cases": results,
            "known_limitations": ["Only literal fields in SCORED_FIELDS are scored; summaries, proficiency and suggested roles require human review.",
                                  "Aliases are explicit; unmatched source-grounded claims require human review.",
                                  "Unsupported claim rate is a conservative lower bound, not a semantic judgment."]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate private Jobra drafts against synthetic gold")
    parser.add_argument("--dataset", type=Path, default=Path(__file__).resolve().parents[3] / "evaluation/golden.v1.json")
    parser.add_argument("--resumes", type=Path, default=Path(__file__).resolve().parents[3] / "evaluation/resumes")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    try:
        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        report = evaluate_dataset(dataset, args.resumes, args.predictions, args.date)
        output = write_private_json_atomic(args.workspace, "evaluations", f"report-{uuid4().hex}.json", report)
    except (OSError, UnicodeError, json.JSONDecodeError, EvaluationError, StorageError):
        parser.exit(1, "evaluation failed: invalid_input_or_storage\n")
    print(json.dumps({"status": "evaluated", "output": str(output.relative_to(args.workspace)),
                      "prediction_count": report["prediction_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
