"""Deterministic scorer for evidence-grounded matching assessments."""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))
from local_storage import write_private_json_atomic
from match_opportunities import MatchError, build_match_results, validate_matching_inputs

POSITIVE = {"matched", "inferred_support"}
CATEGORIES = ("matched", "inferred_support", "not_evidenced", "contradicted", "cannot_assess")


def _metric(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None}


def evaluate(benchmark, golden, predictions, evaluation_date):
    cases = {item["id"]: item for item in benchmark["cases"]}
    candidate_gold = {item["case_id"]: item for item in golden["cases"]}
    candidate_predictions = {item["case_id"]: item for item in predictions}
    opportunity_by_id = {item["id"]: item for item in benchmark["opportunities"]["opportunities"]}
    per_case, flattened = [], []
    attempted = 0
    valid_cases = 0
    ref_valid = 0
    ref_total = 0
    hard_ok = explanation_ok = aggregation_ok = 0
    support_ok = 0
    support_total = sum(1 for item in golden["cases"] for req in item["requirements"]
                        if req["evidence_support"] != "ambiguous")
    ambiguous = sum(1 for item in golden["cases"] for req in item["requirements"]
                    if req["evidence_support"] == "ambiguous")
    false_unsupported = positive_predictions = 0
    not_evidenced_ok = not_evidenced_total = 0
    confusion = {truth: {**{guess: 0 for guess in CATEGORIES}, "missing_prediction": 0}
                 for truth in CATEGORIES}
    expected_requirement_count = sum(len(item["requirements"]) for item in golden["cases"])
    hard_total = explanation_total = len(cases)
    missed_supported = 0
    missing_predictions = sorted(set(cases) - set(candidate_predictions))
    for case_id, case in cases.items():
        prediction = candidate_predictions.get(case_id)
        expected = candidate_gold.get(case_id)
        if prediction is None or expected is None:
            if expected is not None:
                for gold_req in expected["requirements"]:
                    truth = gold_req["expected"]
                    confusion[truth]["missing_prediction"] += 1
                    if truth in POSITIVE:
                        missed_supported += 1
                    elif truth == "not_evidenced":
                        not_evidenced_total += 1
            per_case.append({"case_id": case_id, "status": "missing_prediction" if prediction is None else "missing_golden_label"})
            continue
        attempted += 1
        assessment = prediction["assessment"]
        actual_result = prediction.get("result")
        profile = benchmark["candidates"][case["candidate"]]
        preferences = benchmark["preferences"][case["preferences"]]
        opportunity = opportunity_by_id[case["opportunity"]]
        one_document = {"schema_version": "1", "opportunities": [opportunity]}
        errors = []
        try:
            validate_matching_inputs(profile, preferences, one_document, assessment)
            valid_cases += 1
            rebuilt = build_match_results(profile, preferences, one_document, assessment,
                                          evaluated_at=f"{evaluation_date}T00:00:00Z")
        except (MatchError, ValueError):
            rebuilt = None
            errors.append("schema_or_invariant_failure")
        if rebuilt is not None and actual_result is not None:
            # A caller may have used a different timestamp; compare substantive deterministic fields.
            got = actual_result.get("results", [])
            want = rebuilt.get("results", [])
            stable_keys = ("opportunity_id", "recommendation", "candidate_fit", "experience_alignment",
                           "location_work_mode", "career_alignment", "hard_filter_violations", "warnings", "assessment_scope")
            if len(got) == len(want) and all(all(g.get(k) == w.get(k) for k in stable_keys) for g, w in zip(got, want)):
                aggregation_ok += 1
            else:
                errors.append("deterministic_aggregation_mismatch")
        result = actual_result if actual_result is not None else rebuilt
        output = result.get("results", [{}])[0] if result else {}
        pred_assessment = assessment.get("assessments", [{}])[0]
        pred_reqs = {item["id"]: item for item in pred_assessment.get("requirements", [])}
        gold_reqs = {item["id"]: item for item in expected["requirements"]}
        case_correct = 0
        for req_id, gold_req in gold_reqs.items():
            pred_req = pred_reqs.get(req_id)
            if pred_req is None:
                continue
            truth, guess = gold_req["expected"], pred_req["outcome"]
            confusion[truth][guess] += 1
            flattened.append((truth, guess))
            case_correct += truth == guess
            pos = guess in POSITIVE
            positive_predictions += pos
            if pos and truth in {"not_evidenced", "contradicted"}:
                false_unsupported += 1
            if truth == "not_evidenced":
                not_evidenced_total += 1
                not_evidenced_ok += guess == "not_evidenced"
            if gold_req["evidence_support"] != "ambiguous":
                got_ids = set(pred_req.get("candidate_evidence_ids", []))
                expected_ids = set(gold_req["candidate_evidence_ids"])
                support_ok += (got_ids == expected_ids and
                               ((gold_req["evidence_support"] == "supported" and guess in POSITIVE | {"contradicted"}) or
                                (gold_req["evidence_support"] == "unsupported" and not got_ids)))
        unmatched_ids = sorted(set(pred_reqs) - set(gold_reqs))
        # Structural reference integrity spans requirement, experience, and
        # career assessments; semantic entailment is scored separately above.
        job_evidence = {item["id"] for item in opportunity["evidence"]}
        candidate_evidence = {item["id"] for item in profile["evidence"]
                              if item["review_status"] in ("confirmed", "corrected")}
        accepted_records = {rec["id"]: rec for section in
                            ("education", "experience", "projects", "technical_skills", "suggested_roles")
                            for rec in profile[section] if rec["review_status"] in ("confirmed", "corrected")}
        ref_items = [*pred_reqs.values(), pred_assessment.get("experience_alignment", {}),
                     pred_assessment.get("career_alignment", {})]
        refs_valid_for_case = True
        for ref_item in ref_items:
            job_refs = set(ref_item.get("job_evidence_ids", []))
            record_refs = set(ref_item.get("candidate_record_ids", []))
            evidence_refs = set(ref_item.get("candidate_evidence_ids", []))
            linked = {ref for record_id in record_refs if record_id in accepted_records
                      for ref in accepted_records[record_id]["evidence_ids"]}
            refs_valid_for_case &= (job_refs <= job_evidence and evidence_refs <= candidate_evidence and
                                    record_refs <= set(accepted_records) and
                                    (not record_refs or evidence_refs <= linked))
        ref_total += 1
        ref_valid += refs_valid_for_case
        hard_ok += set(output.get("hard_filter_violations", [])) == set(expected["hard_filter_violations"])
        complete_explanation = bool(output.get("explanation")) and all(
            bool(req.get("rationale")) and bool(req.get("job_evidence_ids")) for req in pred_reqs.values())
        explanation_ok += complete_explanation
        got_warnings = set(output.get("warnings", []))
        missing_warnings = sorted(set(expected["required_uncertainties"]) - got_warnings)
        if missing_warnings:
            errors.append("required_uncertainty_warning_missing")
        per_case.append({"case_id": case_id, "status": "evaluated" if rebuilt else "invalid_prediction",
                         "requirements": len(gold_reqs), "exact_category_correct": int(case_correct),
                         "category_denominator": len(gold_reqs), "hard_filter_correct": set(output.get("hard_filter_violations", [])) == set(expected["hard_filter_violations"]),
                         "unmatched_prediction_requirement_ids": unmatched_ids,
                         "missing_uncertainties": missing_warnings, "failure_categories": errors})
    tp = sum(guess in POSITIVE and truth in POSITIVE for truth, guess in flattened)
    fp = sum(guess in POSITIVE and truth not in POSITIVE for truth, guess in flattened)
    fn = sum(truth in POSITIVE and guess not in POSITIVE for truth, guess in flattened) + missed_supported
    exact = sum(truth == guess for truth, guess in flattened)
    metrics = {
        "requirement_classification_accuracy": _metric(exact, expected_requirement_count),
        "supported_match_precision": _metric(tp, tp + fp),
        "supported_match_recall": _metric(tp, tp + fn),
        "confusion_matrix": confusion,
        "evidence_reference_validity": _metric(ref_valid, ref_total),
        "evidence_support_accuracy_adjudicated_only": _metric(support_ok, support_total),
        "ambiguous_evidence_support_unadjudicated": ambiguous,
        "hard_filter_correctness": _metric(hard_ok, hard_total),
        "false_unsupported_match_rate": _metric(false_unsupported, positive_predictions),
        "not_evidenced_handling_recall": _metric(not_evidenced_ok, not_evidenced_total),
        "explanation_completeness_structural": _metric(explanation_ok, explanation_total),
        "schema_invariant_compliance": _metric(valid_cases, attempted),
        "deterministic_aggregation_reproducibility": _metric(aggregation_ok, attempted)
    }
    return {"report_version": "matching-evaluation-v1", "dataset_version": benchmark["dataset_version"],
            "gold_version": golden["gold_version"], "evaluation_date": evaluation_date,
            "case_count": len(cases), "prediction_attempts": attempted, "missing_prediction_cases": missing_predictions,
            "unmatched_prediction_requirement_count": sum(len(item.get("unmatched_prediction_requirement_ids", [])) for item in per_case),
            "evaluation_context": {"status": "executed_unblinded_same_codex_context",
                                   "note": "Codex created synthetic inputs and assessments in this task context; golden labels were stored separately and added after predictions, but there was no independent clean evaluation agent."},
            "metrics": metrics, "per_case": per_case,
            "limitations": ["Small synthetic benchmark; no real-world performance claim.",
                            "Evidence support accuracy excludes ambiguous judgments.",
                            "The agent assessment was not independently blinded.",
                            "Explanations are checked for required structure, not semantic quality."]}


def render_markdown(report):
    metrics = report["metrics"]
    def fmt(name):
        value = metrics[name]
        return f"{value['numerator']}/{value['denominator']}" + (f" ({value['rate']:.3f})" if value["rate"] is not None else " (n/a)")
    lines = [f"# Matching Evaluation {report['dataset_version']}", "",
             f"Date: {report['evaluation_date']} · Cases: {report['case_count']}",
             f"Agent context: {report['evaluation_context']['status']}", "",
             "| Metric | Result |", "|---|---:|",
             f"| Exact requirement classification | {fmt('requirement_classification_accuracy')} |",
             f"| Supported match precision | {fmt('supported_match_precision')} |",
             f"| Supported match recall | {fmt('supported_match_recall')} |",
             f"| Evidence reference validity | {fmt('evidence_reference_validity')} |",
             f"| Adjudicated evidence support accuracy | {fmt('evidence_support_accuracy_adjudicated_only')} |",
             f"| Hard-filter correctness | {fmt('hard_filter_correctness')} |",
             f"| False unsupported-match rate | {fmt('false_unsupported_match_rate')} |",
             f"| Not-evidenced handling recall | {fmt('not_evidenced_handling_recall')} |",
             f"| Explanation completeness (structural) | {fmt('explanation_completeness_structural')} |",
             f"| Schema/invariant compliance | {fmt('schema_invariant_compliance')} |",
             f"| Aggregation reproducibility | {fmt('deterministic_aggregation_reproducibility')} |", "",
             f"Ambiguous evidence judgments excluded: {metrics['ambiguous_evidence_support_unadjudicated']}", "",
             "| Case | Status | Exact labels | Hard filter | Uncertainty omissions |", "|---|---|---:|---|---:|"]
    lines.extend(f"| {x['case_id']} | {x['status']} | {x.get('exact_category_correct', 0)}/{x.get('category_denominator', 0)} | {x.get('hard_filter_correct', 'n/a')} | {len(x.get('missing_uncertainties', []))} |" for x in report["per_case"])
    lines.extend(["", "## Limitations", ""] + [f"- {item}" for item in report["limitations"]])
    return "\n".join(lines) + "\n"


def _write_private_markdown(workspace, filename, content):
    private = Path(workspace) / ".jobra"
    directory = private / "evaluations"
    for part in (private, directory):
        if part.is_symlink():
            raise ValueError("unsafe_storage")
        part.mkdir(mode=0o700, exist_ok=True)
        if not part.is_dir():
            raise ValueError("unsafe_storage")
        os.chmod(part, 0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".pending-", suffix=".md", delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, directory / filename)
    except FileExistsError:
        raise ValueError("output_exists") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return directory / filename


def main():
    parser = argparse.ArgumentParser(description="Evaluate synthetic matching assessments against separate golden labels")
    parser.add_argument("--predictions", type=Path, required=True, help="Directory of case JSON files or one combined prediction JSON")
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    try:
        benchmark = json.loads((ROOT / "evaluation/matching/benchmark.v1.json").read_text(encoding="utf-8"))
        golden = json.loads((ROOT / "evaluation/matching/golden.v1.json").read_text(encoding="utf-8"))
        if args.predictions.is_dir():
            predictions = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.predictions.glob("*.json"))]
        else:
            loaded = json.loads(args.predictions.read_text(encoding="utf-8"))
            predictions = loaded.get("predictions", [loaded])
        report = evaluate(benchmark, golden, predictions, args.date)
        ident = uuid4().hex
        report_path = write_private_json_atomic(args.workspace, "evaluations", f"matching-report-{ident}.json", report)
        md_path = _write_private_markdown(args.workspace, f"matching-report-{ident}.md", render_markdown(report))
    except (OSError, UnicodeError, ValueError):
        parser.exit(1, "matching evaluation failed: invalid_input_or_storage\n")
    print(json.dumps({"status": "evaluated", "cases": report["case_count"], "report": str(report_path.relative_to(args.workspace)), "human_report": str(md_path.relative_to(args.workspace))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
