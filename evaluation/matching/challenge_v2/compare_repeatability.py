"""Compare separate Codex runs without treating either as ground truth."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))
from local_storage import write_private_json_atomic
from match_opportunities import MatchError, validate_matching_inputs

BASE = Path(__file__).resolve().parent


def compare(primary_path: Path, repeat_path: Path, primary_session: str, repeat_session: str,
            primary_completed_at: str | None = None, repeat_completed_at: str | None = None):
    inputs = json.loads((BASE / "inputs.v2.json").read_text(encoding="utf-8"))
    frozen = json.loads((BASE / "freeze.v2.json").read_text(encoding="utf-8"))
    primary = json.loads(primary_path.read_text(encoding="utf-8"))
    repeat = json.loads(repeat_path.read_text(encoding="utf-8"))
    case_map = {item["id"]: item for item in inputs["cases"]}
    opportunities = {item["id"]: item for item in inputs["opportunities"]["opportunities"]}
    left = {item["case_id"]: item for item in primary.get("predictions", [])}
    right = {item["case_id"]: item for item in repeat.get("predictions", [])}
    rows = []
    for case_id in sorted(set(left) & set(right)):
        case = case_map.get(case_id)
        if case is None:
            continue
        assessment_left = left[case_id].get("assessment")
        assessment_right = right[case_id].get("assessment")
        opportunity = {"schema_version": "1", "opportunities": [opportunities[case["opportunity"]]]}
        profile = inputs["candidates"][case["candidate"]]
        preferences = inputs["preferences"][case["preferences"]]
        valid = []
        for assessment in (assessment_left, assessment_right):
            try:
                validate_matching_inputs(profile, preferences, opportunity, assessment)
                valid.append(True)
            except (MatchError, TypeError, ValueError):
                valid.append(False)
        req_maps = []
        for assessment in (assessment_left, assessment_right):
            items = assessment.get("assessments", [{}])[0].get("requirements", []) if isinstance(assessment, dict) else []
            req_maps.append({item["id"]: item for item in items})
        common = sorted(set(req_maps[0]) & set(req_maps[1]))
        category_consistent = bool(common) and all(req_maps[0][key]["outcome"] == req_maps[1][key]["outcome"] for key in common)
        evidence_consistent = bool(common) and all(
            set(req_maps[0][key].get("candidate_evidence_ids", [])) ==
            set(req_maps[1][key].get("candidate_evidence_ids", [])) for key in common)
        rows.append({"case_id": case_id, "primary_schema_valid": valid[0], "repeat_schema_valid": valid[1],
                     "common_requirement_ids": common, "classification_consistent": category_consistent,
                     "candidate_evidence_references_consistent": evidence_consistent})
    return {"report_version": "matching-repeatability-v2", "benchmark_version": "matching-challenge-v2",
            "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "prediction_run_id": frozen["prediction_run_id"],
            "input_sha256": frozen["input_sha256"], "labels_sha256": frozen["labels_sha256"],
            "primary_predictions_sha256": hashlib.sha256(primary_path.read_bytes()).hexdigest(),
            "repeat_predictions_sha256": hashlib.sha256(repeat_path.read_bytes()).hexdigest(),
            "primary_session_id": primary_session, "repeat_session_id": repeat_session,
            "primary_session_completed_at_utc": primary_completed_at,
            "repeat_session_completed_at_utc": repeat_completed_at,
            "repeat_cases_requested": len(right), "cases_compared": len(rows), "cases": rows,
            "classification_consistency": {"numerator": sum(row["classification_consistent"] for row in rows),
                "denominator": len(rows)},
            "candidate_evidence_reference_consistency": {"numerator": sum(row["candidate_evidence_references_consistent"] for row in rows),
                "denominator": len(rows)},
            "primary_schema_validity": {"numerator": sum(row["primary_schema_valid"] for row in rows), "denominator": len(rows)},
            "repeat_schema_validity": {"numerator": sum(row["repeat_schema_valid"] for row in rows), "denominator": len(rows)},
            "first_repeat_attempt": {"status": "unscorable", "session_id": "01a13585-07f8-7893-ae6f-f9d186f0eff8",
                "reason": "Output did not conform to the documented assessment schema; the repeat prompt referred to a format unavailable in that clean context."},
            "interpretation": "Run agreement is consistency evidence only, not correctness or additional ground truth."}


def main():
    parser = argparse.ArgumentParser(description="Compare selected blind matching predictions across clean sessions")
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--repeat", type=Path, required=True)
    parser.add_argument("--primary-session", required=True)
    parser.add_argument("--repeat-session", required=True)
    parser.add_argument("--primary-completed-at")
    parser.add_argument("--repeat-completed-at")
    parser.add_argument("--workspace", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        report = compare(args.primary, args.repeat, args.primary_session, args.repeat_session,
                         args.primary_completed_at, args.repeat_completed_at)
        path = write_private_json_atomic(args.workspace, "evaluations",
                                         f"matching-repeatability-v2-{args.repeat_session.replace('-', '')}-{uuid4().hex}.json", report)
    except (OSError, UnicodeError, ValueError, TypeError):
        parser.exit(1, "repeat comparison failed: invalid_input_or_storage\n")
    print(json.dumps({"status": "compared", "cases": report["cases_compared"],
                      "report": str(path.relative_to(args.workspace))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
