"""Score frozen V0.2.2 blind predictions after extraction has ended."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[4]
CHALLENGE = Path(__file__).resolve().parents[1]
RUN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "evaluation"))
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))
from evaluate_matching import render_markdown, evaluate, _write_private_markdown
from local_storage import StorageError, write_private_json_atomic


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _failure_register(report, golden, raw_predictions):
    labels = {item["case_id"]: item for item in golden["cases"]}
    predictions = {item["case_id"]: item for item in raw_predictions}
    cases = []
    for result in report["per_case"]:
        case_id = result["case_id"]
        pred = predictions.get(case_id, {})
        assessment = (pred.get("repair_assessment") or pred.get("assessment") or {}).get("assessments", [{}])[0]
        requirements = assessment.get("requirements", [])
        actual = result.get("actual_requirement_outcomes", {})
        label = labels.get(case_id, {})
        expected = {item.get("id"): item.get("expected") for item in label.get("requirements", [])}
        scored_expected = {item.get("id"): item.get("expected") for item in label.get("requirements", [])
                          if item.get("evidence_support") != "ambiguous"}
        observed_support = {item.get("id"): item.get("candidate_evidence_ids", []) for item in requirements}
        correct_categories = all(actual.get(identifier) == outcome for identifier, outcome in scored_expected.items())
        hard_ok = result.get("hard_filter_correct") is True
        invalid = result.get("post_repair_valid") is False
        if not invalid and correct_categories and hard_ok and not result.get("failure_categories"):
            continue
        failure_codes = result.get("failure_categories", [])
        hard_violation = label.get("hard_filter_violations", [])
        unsupported_ids = {item["id"] for item in label.get("requirements", [])
                           if item.get("evidence_support") == "unsupported"}
        severity = "high" if (hard_violation and not hard_ok) or any(
            identifier in unsupported_ids and expected.get(identifier) in ("not_evidenced", "contradicted") and
            actual.get(identifier) in ("matched", "inferred_support") for identifier in expected) else "medium"
        if invalid:
            root = "Assessment validation rejected its schema, identifiers, provenance links, or invariants."
            fix = "Select only catalog references; retain empty candidate refs for not_evidenced; follow the field-qualified preference catalog."
            regression = "Add a case-specific test that replays the reported path/code and verifies independent hard-filter output."
        elif hard_violation and not hard_ok:
            root = "Explicit excluded-role matching was missed or misclassified by the deterministic constraint layer."
            fix = "Improve normalized title/seniority phrase matching without applying employer requirements as user filters."
            regression = "Test the same excluded-role phrase, title variant, and near-match as separate hard-filter cases."
        else:
            root = "Semantic classification, evidence selection, uncertainty, or explanation differed from the frozen expectation."
            fix = "Review the source excerpt and assessment rationale; do not resolve an ambiguous label in the agent's favor."
            regression = "Add the failing source-supported example as a synthetic regression without changing frozen labels."
        cases.append({"case_id": case_id, "expected_behavior": {
                "requirement_outcomes": expected, "hard_filter_violations": hard_violation,
                "required_uncertainties": label.get("required_uncertainties", [])},
            "actual_behavior": {"status": result.get("status"), "requirement_outcomes": actual,
                "candidate_evidence_refs": observed_support,
                "hard_filter_violations": result.get("actual_hard_filter_violations", []),
                "diagnostics": failure_codes},
            "severity": severity, "root_cause_hypothesis": root,
            "recommended_fix": fix, "regression_test_proposal": regression})
    return {"register_version": "matching-failure-register-v2.2", "cases": cases}


def score(prediction_path, package_path, workspace, run_id, session_id,
          prediction_completed_at):
    frozen_path = RUN_DIR / "freeze.v2.2.json"
    if not frozen_path.is_file():
        raise ValueError("freeze_missing")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    baseline = json.loads((CHALLENGE / "freeze.v2.json").read_text(encoding="utf-8"))
    inputs_path, labels_path = CHALLENGE / "inputs.v2.json", CHALLENGE / "labels.v2.json"
    if (_sha(inputs_path) != frozen["input_sha256"] or _sha(labels_path) != frozen["labels_sha256"] or
            frozen["input_sha256"] != baseline["input_sha256"] or frozen["labels_sha256"] != baseline["labels_sha256"]):
        raise ValueError("benchmark_freeze_integrity_failure")
    for name, digest in frozen["implementation_sha256"].items():
        paths = {"match_opportunities.py": ROOT / "skills/jobra/scripts/match_opportunities.py",
                 "prepare_matching.py": ROOT / "skills/jobra/scripts/prepare_matching.py",
                 "matching-assessment.schema.json": ROOT / "skills/jobra/references/matching-assessment.schema.json",
                 "evaluate_matching.py": ROOT / "evaluation/evaluate_matching.py",
                 "opportunity-matching.md": ROOT / "docs/opportunity-matching.md",
                 "build_prediction_package.py": RUN_DIR / "build_prediction_package.py",
                 "score_v2.2.py": RUN_DIR / "score_v2.2.py"}
        if _sha(paths[name]) != digest:
            raise ValueError("implementation_freeze_integrity_failure")
    if _sha(package_path) != frozen["prediction_package_sha256"]:
        raise ValueError("prediction_package_integrity_failure")
    if run_id != frozen["prediction_run_id"]:
        raise ValueError("prediction_run_id_mismatch")
    raw = json.loads(prediction_path.read_text(encoding="utf-8"))
    if raw.get("prediction_run_id") != run_id:
        raise ValueError("prediction_manifest_mismatch")
    benchmark = json.loads(inputs_path.read_text(encoding="utf-8"))
    golden = json.loads(labels_path.read_text(encoding="utf-8"))
    predictions = raw.get("predictions")
    expected_ids = {item["id"] for item in benchmark["cases"]}
    got_ids = [item.get("case_id") for item in predictions] if isinstance(predictions, list) else []
    if len(got_ids) != len(set(got_ids)) or set(got_ids) != expected_ids:
        raise ValueError("prediction_case_set_mismatch")
    report = evaluate(benchmark, golden, predictions, datetime.now(timezone.utc).date().isoformat(),
                      exclude_ambiguous_support=True)
    report["report_version"] = "matching-reliability-v2.2"
    report["evaluation_context"] = {"status": "separate_clean_projectless_codex_task",
        "prediction_session_id": session_id,
        "note": "Prediction task received only the frozen synthetic package, reference catalogs, matching schema, and contract; evaluator and labels were withheld."}
    report["limitations"] = [
        "Small synthetic regression set; no real-world performance or production-readiness claim.",
        "The same frozen 18 cases are used for regression comparability; no new unseen challenge cases were added.",
        "Golden labels are unchanged and have not received independent human adjudication.",
        "Evidence sufficiency is semantic; deterministic checks establish reference validity and catch only obvious lexical mismatch.",
        "Ambiguous evidence-support judgments are excluded and reported separately.",
        "The prior eight-opportunity live pilot remains observational only.",
    ]
    report["run_manifest"] = {"benchmark_version": frozen["benchmark_version"],
        "prediction_run_id": run_id, "prediction_session_id": session_id,
        "input_sha256": frozen["input_sha256"], "labels_sha256": frozen["labels_sha256"],
        "prediction_package_sha256": frozen["prediction_package_sha256"],
        "prediction_sha256": _sha(prediction_path), "implementation_sha256": frozen["implementation_sha256"],
        "frozen_at_utc": frozen["frozen_at_utc"],
        "prediction_completed_at_utc": prediction_completed_at,
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    failures = _failure_register(report, golden, predictions)
    suffix = uuid4().hex
    private_report = write_private_json_atomic(workspace, "evaluations",
        f"matching-v2.2-report-{run_id}-{suffix}.json", report)
    private_md = _write_private_markdown(workspace,
        f"matching-v2.2-report-{run_id}-{suffix}.md", render_markdown(report))
    failure_path = write_private_json_atomic(workspace, "evaluations",
        f"matching-v2.2-failures-{run_id}-{suffix}.json", failures)
    return report, failures, private_report, private_md, failure_path


def publish(report, failures):
    report_json = RUN_DIR / "report.v2.2.json"
    report_md = RUN_DIR / "report.v2.2.md"
    failure_json = RUN_DIR / "failure-register.v2.2.json"
    failure_md = RUN_DIR / "failure-register.v2.2.md"
    from evaluate_matching import render_markdown
    for path, contents in ((report_json, json.dumps(report, indent=2) + "\n"),
                           (report_md, render_markdown(report)),
                           (failure_json, json.dumps(failures, indent=2) + "\n")):
        with path.open("x", encoding="utf-8") as stream:
            stream.write(contents)
    lines = ["# Failure register — V0.2.2", "", "Synthetic regression failures only. See the machine-readable register for complete behavior and proposals.", "",
             "| Case | Severity | Expected | Observed | Root-cause hypothesis |", "|---|---|---|---|---|"]
    lines.extend(f"| {case['case_id']} | {case['severity']} | `{json.dumps(case['expected_behavior'], ensure_ascii=False)}` | `{json.dumps(case['actual_behavior'], ensure_ascii=False)}` | {case['root_cause_hypothesis']} |" for case in failures["cases"])
    with failure_md.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Score V0.2.2 blind matching regression predictions")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--prediction-completed-at", required=True)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        report, failures, *private_paths = score(args.predictions, args.package,
            args.workspace, args.run_id, args.session_id, args.prediction_completed_at)
        publish(report, failures)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, StorageError):
        parser.exit(1, "matching evaluation failed: frozen_input_or_storage_error\n")
    print(json.dumps({"status": "scored_and_published", "cases": report["case_count"],
                      "private_artifacts": [str(path.relative_to(args.workspace)) for path in private_paths],
                      "report": str(RUN_DIR / "report.v2.2.md"),
                      "failure_count": len(failures["cases"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
