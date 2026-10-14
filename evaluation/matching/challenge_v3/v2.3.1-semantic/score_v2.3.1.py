"""Score blind V0.2.3.1 predictions only after the prediction manifest is saved."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
RUN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "evaluation"))
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))
from evaluate_matching import evaluate, render_markdown
from match_opportunities import build_match_results_resilient


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _failure_register(report, golden, predictions):
    labels = {item["case_id"]: item for item in golden["cases"]}
    observed = {item["case_id"]: item for item in predictions}
    failures = []
    for result in report["per_case"]:
        case_id = result["case_id"]
        expected = labels.get(case_id)
        prediction = observed.get(case_id)
        if expected is None or prediction is None:
            failures.append({"case_id": case_id, "severity": "high", "category": "missing_prediction_or_label",
                "expected": expected, "actual": None, "root_cause_hypothesis": "A prediction or label is absent; no semantic judgment is made."})
            continue
        if result.get("status") == "evaluated" and not result.get("failure_categories"):
            continue
        assessment = prediction.get("assessment", {}).get("assessments", [{}])[0]
        actual = {item.get("id"): item.get("outcome") for item in assessment.get("requirements", [])}
        positive_expected = any(item.get("expected") in ("not_evidenced", "contradicted") and
            item.get("evidence_support") != "ambiguous" for item in expected.get("requirements", []))
        false_positive = any(actual.get(item["id"]) in ("matched", "inferred_support")
            for item in expected.get("requirements", [])
            if item.get("expected") in ("not_evidenced", "contradicted") and item.get("evidence_support") != "ambiguous")
        failures.append({"case_id": case_id, "severity": "high" if positive_expected and false_positive else "medium",
            "category": result.get("failure_categories", []),
            "expected_requirement_outcomes": {item["id"]: item["expected"] for item in expected.get("requirements", [])
                if item.get("evidence_support") != "ambiguous"},
            "actual_requirement_outcomes": result.get("actual_requirement_outcomes", actual),
            "missing_uncertainties": result.get("missing_uncertainties", []),
            "root_cause_hypothesis": "Review the source excerpts and required rationale points; this automated register does not adjudicate whether a golden label is debatable.",
            "review_status": "requires_human_review"})
    return {"register_version": "matching-failure-register-v2.3.1", "cases": failures}


def _write_new(path, text):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def score(prediction_path, package_path, run_id, session_ids, completed_at):
    frozen_path = RUN_DIR / "freeze.v2.3.1.json"
    if not frozen_path.is_file():
        raise ValueError("freeze_missing")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    inputs_path, golden_path = RUN_DIR / "inputs.v2.3.1.json", RUN_DIR / "golden.v2.3.1.json"
    implementation = {
        "build_inputs.py": RUN_DIR / "build_inputs.py",
        "build_prediction_package.py": RUN_DIR / "build_prediction_package.py",
        "freeze.py": RUN_DIR / "freeze.py",
        "score_v2.3.1.py": RUN_DIR / "score_v2.3.1.py",
        "evaluate_matching.py": ROOT / "evaluation/evaluate_matching.py",
        "match_opportunities.py": ROOT / "skills/jobra/scripts/match_opportunities.py",
        "matching-assessment.schema.json": ROOT / "skills/jobra/references/matching-assessment.schema.json",
        "opportunity-matching.md": ROOT / "docs/opportunity-matching.md",
        "matching-evidence-policy.md": ROOT / "docs/matching-evidence-policy.md",
    }
    if sha(inputs_path) != frozen["input_sha256"] or sha(golden_path) != frozen["golden_sha256"]:
        raise ValueError("frozen_dataset_integrity_failure")
    if sha(package_path) != frozen["package_sha256"]:
        raise ValueError("frozen_package_integrity_failure")
    if any(sha(path) != frozen["implementation_sha256"][name] for name, path in implementation.items()):
        raise ValueError("frozen_implementation_integrity_failure")
    if run_id != frozen["prediction_run_id"]:
        raise ValueError("prediction_run_id_mismatch")
    raw = json.loads(prediction_path.read_text(encoding="utf-8"))
    if raw.get("prediction_run_id") != run_id:
        raise ValueError("prediction_manifest_mismatch")
    benchmark = json.loads(inputs_path.read_text(encoding="utf-8"))
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    predictions = raw.get("predictions")
    expected_ids = {item["id"] for item in benchmark["cases"]}
    got_ids = [item.get("case_id") for item in predictions] if isinstance(predictions, list) else []
    if len(got_ids) != len(set(got_ids)) or set(got_ids) != expected_ids:
        raise ValueError("prediction_case_set_mismatch")

    candidate_cases = {item["id"]: item for item in benchmark["cases"]}
    opportunities = {item["id"]: item for item in benchmark["opportunities"]["opportunities"]}
    for prediction in predictions:
        case = candidate_cases[prediction["case_id"]]
        prediction["result"] = build_match_results_resilient(
            benchmark["candidates"][case["candidate"]],
            benchmark["preferences"][case["preferences"]],
            {"schema_version": "1", "opportunities": [opportunities[case["opportunity"]]]},
            prediction["assessment"])
    report = evaluate(benchmark, golden, predictions,
        datetime.now(timezone.utc).date().isoformat(), exclude_ambiguous_support=True)
    report["report_version"] = "matching-semantic-evaluation-v2.3.1"
    report["evaluation_context"] = {"status": "separate_clean_projectless_codex_tasks",
        "prediction_session_ids": session_ids,
        "note": "Each prediction task received only its assigned synthetic source inputs, catalog, schema, and policy. No task received golden labels, prior predictions, or evaluation reports."}
    points = sum(len(item.get("expected_explanation_points", [])) > 0
        for case in golden["cases"] for item in case["requirements"])
    report["semantic_explanation_quality"] = {
        "reviewed_requirement_count": 0, "unresolved_requirement_count": points,
        "status": "pending_independent_human_adjudication",
        "note": "The deterministic rationale-presence metric does not assess semantic persuasiveness; expected points are prepared in the review packet."}
    report["label_adjudication"] = {"source_first_and_engine_independent": True,
        "independent_human_review": "not_performed",
        "ambiguous_requirements_excluded_from_classification": report["ambiguous_requirement_count_excluded_from_accuracy"]}
    report["run_manifest"] = {"benchmark_version": frozen["benchmark_version"],
        "gold_version": frozen["gold_version"], "prediction_run_id": run_id,
        "prediction_session_ids": session_ids, "input_sha256": frozen["input_sha256"],
        "golden_sha256": frozen["golden_sha256"], "package_sha256": frozen["package_sha256"],
        "prediction_sha256": sha(prediction_path), "implementation_sha256": frozen["implementation_sha256"],
        "frozen_at_utc": frozen["frozen_at_utc"], "prediction_completed_at_utc": completed_at,
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    failures = _failure_register(report, golden, predictions)
    md = render_markdown(report)
    md += ("\n## Semantic explanation review\n\n"
           f"No explanation received independent human adjudication; {points} requirement explanations remain unresolved. "
           "The structural explanation-completeness rate is reported separately.\n")
    run_dir = RUN_DIR
    _write_new(run_dir / "report.v2.3.1.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _write_new(run_dir / "report.v2.3.1.md", md)
    _write_new(run_dir / "failure-register.v2.3.1.json", json.dumps(failures, ensure_ascii=False, indent=2) + "\n")
    return report, failures


def main():
    parser = argparse.ArgumentParser(description="Score blind V0.2.3.1 matching predictions")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--session-ids", required=True, help="comma-separated clean Codex task IDs")
    parser.add_argument("--prediction-completed-at", required=True)
    args = parser.parse_args()
    try:
        report, failures = score(args.predictions, args.package, args.run_id,
            args.session_ids.split(","), args.prediction_completed_at)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        parser.exit(1, "matching evaluation failed: frozen_input_or_prediction_error\n")
    print(json.dumps({"status": "scored", "cases": report["case_count"],
        "failure_count": len(failures["cases"]), "report": str(RUN_DIR / "report.v2.3.1.md")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
