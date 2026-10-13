"""Publish reviewed, synthetic-only JSON/Markdown evaluation artifacts once."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent


def _rate(metric):
    if metric["rate"] is None:
        return "n/a"
    return f"{metric['numerator']}/{metric['denominator']} ({metric['rate']:.3f})"


def render(report, repeat, failures):
    metrics = report["metrics"]
    manifest = report["run_manifest"]
    lines = ["# Blinded Matching Evaluation — V0.2.1", "",
        f"Dataset: `{report['dataset_version']}` · cases: {report['case_count']} · date: {report['evaluation_date']}",
        f"Prediction run: `{manifest['prediction_run_id']}` · session: `{report['evaluation_context']['prediction_session_id']}`",
        f"Frozen: {manifest['frozen_at_utc']} · predicted: {manifest['prediction_completed_at_utc']} · evaluated: {manifest['evaluated_at_utc']}",
        "Hashes:",
        f"- Input SHA-256: `{manifest['input_sha256']}`",
        f"- Golden SHA-256: `{manifest['labels_sha256']}`",
        f"- Prediction SHA-256: `{manifest['predictions_sha256']}`", "",
        "Predictions came from a separate clean projectless Codex task. It received only synthetic inputs and the matching contract; golden labels, prior reports, and evaluator output were not in its context.",
        "", "## Metrics", "", "| Measure | Numerator / denominator | Rate |", "|---|---:|---:|"]
    keys = [
        ("Requirement classification exact accuracy", "requirement_classification_accuracy"),
        ("Supported-match precision", "supported_match_precision"),
        ("Supported-match recall", "supported_match_recall"),
        ("Evidence-reference integrity (assessment level)", "evidence_reference_validity"),
        ("Semantic evidence support (adjudicated only)", "evidence_support_accuracy_adjudicated_only"),
        ("Hard-filter end-to-end success", "hard_filter_correctness"),
        ("Hard-filter correctness when aggregation ran", "hard_filter_correctness_when_aggregated"),
        ("Explicit exclusion end-to-end success", "explicit_exclusion_end_to_end_success"),
        ("Explicit exclusion case coverage", "explicit_exclusion_case_coverage"),
        ("Explicit exclusion accuracy when scored", "explicit_exclusion_accuracy_when_scored"),
        ("False unsupported-match rate", "false_unsupported_match_rate"),
        ("Not-evidenced handling recall", "not_evidenced_handling_recall"),
        ("Explanation completeness (structural)", "explanation_completeness_structural"),
        ("Schema/invariant compliance", "schema_invariant_compliance"),
        ("Deterministic aggregation reproducibility", "deterministic_aggregation_reproducibility"),
    ]
    for label, key in keys:
        metric = metrics[key]
        rate = "n/a" if metric["rate"] is None else f"{metric['rate']:.3f}"
        lines.append(f"| {label} | {metric['numerator']}/{metric['denominator']} | {rate} |")
    lines.extend(["", f"Ambiguous evidence-support labels excluded from classification/support accuracy: {report['ambiguous_requirement_count_excluded_from_accuracy']}.",
        f"Ambiguous support judgments: {metrics['ambiguous_evidence_support_unadjudicated']}. Unmatched requirement predictions: {report['unmatched_prediction_requirement_count']}, including {report['unmatched_positive_prediction_count_unadjudicated']} positive prediction(s) left unadjudicated.",
        "Hard-filter end-to-end success counts invalid assessments as unsuccessful because deterministic filtering could not produce a result. The conditional metric shows only cases where aggregation completed.",
        "", "### Per-class precision and recall", "", "| Class | Precision | Recall |", "|---|---:|---:|"])
    for category, result in metrics["per_class_precision_recall"].items():
        lines.append(f"| {category} | {_rate(result['precision'])} | {_rate(result['recall'])} |")
    lines.extend(["", "### Confusion matrix (ambiguous expected labels excluded)", "",
        "| Expected \\ Predicted | matched | inferred_support | not_evidenced | contradicted | cannot_assess | missing |",
        "|---|---:|---:|---:|---:|---:|---:|"])
    confusion = metrics["confusion_matrix"]
    for expected, row in confusion.items():
        lines.append("| " + expected + " | " + " | ".join(str(row.get(col, 0)) for col in
            ("matched", "inferred_support", "not_evidenced", "contradicted", "cannot_assess", "missing_prediction")) + " |")
    lines.extend(["", "## Per-case results", "", "| Case | Status | Exact category | Hard filter checked | Failure codes |", "|---|---|---:|---|---|"])
    for case in report["per_case"]:
        exact = f"{case.get('exact_category_correct', 0)}/{case.get('category_denominator', 0)}"
        failures = ", ".join(case.get("failure_categories", [])) or "—"
        lines.append(f"| {case['case_id']} | {case['status']} | {exact} | {case.get('hard_filter_checked', False)} | {failures} |")
    lines.extend(["", "## Failure register", "", "See [failure-register.v2.md](failure-register.v2.md) for expected behavior, observed behavior, severity, root-cause hypotheses, and regression proposals.",
        "", "## Repeatability", "", f"Six selected cases were assessed in another clean task: category agreement {repeat['classification_consistency']['numerator']}/{repeat['classification_consistency']['denominator']}; candidate evidence-reference agreement {repeat['candidate_evidence_reference_consistency']['numerator']}/{repeat['candidate_evidence_reference_consistency']['denominator']}; schema-valid outputs {repeat['primary_schema_validity']['numerator']}/{repeat['primary_schema_validity']['denominator']} primary and {repeat['repeat_schema_validity']['numerator']}/{repeat['repeat_schema_validity']['denominator']} repeat.",
        "Agreement is consistency only. One earlier repeat task was unscorable because its prompt did not include the requested output schema; it is recorded in the repeatability artifact.",
        "", "## Limits", "", "Golden labels were frozen before predictions and authored from synthetic source records without using matcher predictions. They have not received independent human adjudication. The benchmark is small and synthetic; these results are not production readiness or real-world accuracy claims.",
        "The earlier eight-opportunity pilot remains observational only: 12 saved requirements were partial summaries, not ground truth. No private profile or historical opportunity snapshot was used."])
    return "\n".join(lines) + "\n"


def _write_run_snapshot(path: Path, payload: str, identity_field: str, identity_value: str):
    if path.exists():
        if path.is_symlink():
            raise ValueError("unsafe_report_path")
        prior = json.loads(path.read_text(encoding="utf-8"))
        found = prior
        for key in identity_field.split("."):
            found = found.get(key) if isinstance(found, dict) else None
        if found != identity_value:
            raise ValueError("refusing_to_replace_different_run")
        path.write_text(payload, encoding="utf-8")
    else:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(payload)


def main():
    parser = argparse.ArgumentParser(description="Publish reviewed V2 synthetic evaluation reports without replacing prior reports")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repeat", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        repeat = json.loads(args.repeat.read_text(encoding="utf-8"))
        failures = json.loads((BASE / "failure-register.v2.json").read_text(encoding="utf-8"))
        frozen = json.loads((BASE / "freeze.v2.json").read_text(encoding="utf-8"))
        if report["run_manifest"]["input_sha256"] != frozen["input_sha256"] or report["run_manifest"]["labels_sha256"] != frozen["labels_sha256"]:
            raise ValueError("frozen_hash_mismatch")
        _write_run_snapshot(BASE / "report.v2.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                            "run_manifest.prediction_run_id", report["run_manifest"]["prediction_run_id"])
        _write_run_snapshot(BASE / "repeatability.v2.json", json.dumps(repeat, ensure_ascii=False, indent=2) + "\n",
                            "repeat_session_id", repeat["repeat_session_id"])
        failure_md_path = BASE / "failure-register.v2.md"
        if failure_md_path.exists() and failure_md_path.is_symlink():
            raise ValueError("unsafe_report_path")
        failure_md_path.write_text("# Failure Register — V0.2.1\n\n"
            "All cases use synthetic data. Severity prioritizes evidence that could mislead users, blocked explicit hard filters, and invalid assessments. The complete structured register is in [failure-register.v2.json](failure-register.v2.json).\n\n"
            "| Case | Severity | Observed failure |\n|---|---|---|\n" +
            "\n".join(f"| {item['case_id']} | {item['severity']} | {item['actual_behavior']}" for item in failures["failures"]) + "\n")
        report_path = BASE / "report.v2.md"
        if report_path.exists() and report_path.is_symlink():
            raise ValueError("unsafe_report_path")
        report_path.write_text(render(report, repeat, failures), encoding="utf-8")
    except (OSError, KeyError, TypeError, ValueError):
        parser.exit(1, "report publication failed: invalid_input_or_existing_output\n")
    print("published V0.2.1 synthetic reports without replacing existing files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
