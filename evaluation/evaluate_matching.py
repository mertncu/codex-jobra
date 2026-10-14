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
from match_opportunities import (MatchError, build_match_results,
                                 build_match_results_resilient,
                                 validate_matching_inputs)

POSITIVE = {"matched", "inferred_support"}
CATEGORIES = ("matched", "inferred_support", "not_evidenced", "contradicted", "cannot_assess")


def _metric(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None}


def _align_prediction_requirements(gold_requirements, predicted_requirements):
    """Align agent-assigned IDs to frozen labels by source evidence references."""
    remaining = list(predicted_requirements.values())
    aligned = {}
    for gold in gold_requirements:
        match = next((item for item in remaining if item.get("id") == gold["id"]), None)
        if match is None:
            sources = set(gold.get("job_evidence_ids", []))
            candidates = [item for item in remaining if sources.intersection(item.get("job_evidence_ids", []))]
            match = candidates[0] if len(candidates) == 1 else None
        if match is not None:
            aligned[gold["id"]] = match
            remaining.remove(match)
    return aligned, remaining


def evaluate(benchmark, golden, predictions, evaluation_date, *, exclude_ambiguous_support=False):
    cases = {item["id"]: item for item in benchmark["cases"]}
    candidate_gold = {item["case_id"]: item for item in golden["cases"]}
    candidate_predictions = {item["case_id"]: item for item in predictions}
    opportunity_by_id = {item["id"]: item for item in benchmark["opportunities"]["opportunities"]}
    per_case, flattened = [], []
    attempted = 0
    valid_cases = first_pass_valid = hard_executed = 0
    ref_valid = 0
    ref_total = 0
    hard_ok = hard_scored = explanation_ok = aggregation_ok = aggregation_checks = 0
    explicit_filter_total = sum(bool(item["hard_filter_violations"]) for item in golden["cases"])
    explicit_filter_scored = explicit_filter_ok = 0
    support_ok = 0
    support_total = sum(1 for item in golden["cases"] for req in item["requirements"]
                        if req["evidence_support"] != "ambiguous")
    ambiguous = sum(1 for item in golden["cases"] for req in item["requirements"]
                    if req["evidence_support"] == "ambiguous")
    false_unsupported = positive_predictions = unmatched_positive = 0
    not_evidenced_ok = not_evidenced_total = 0
    confusion = {truth: {**{guess: 0 for guess in CATEGORIES}, "missing_prediction": 0}
                 for truth in CATEGORIES}
    ambiguous_requirement_count = sum(1 for item in golden["cases"] for req in item["requirements"]
                                     if exclude_ambiguous_support and req["evidence_support"] == "ambiguous")
    expected_requirement_count = sum(1 for item in golden["cases"] for req in item["requirements"]
                                    if not exclude_ambiguous_support or req["evidence_support"] != "ambiguous")
    hard_total = explanation_total = len(cases)
    missed_supported = 0
    missing_predictions = sorted(set(cases) - set(candidate_predictions))
    for case_id, case in cases.items():
        prediction = candidate_predictions.get(case_id)
        expected = candidate_gold.get(case_id)
        if prediction is None or expected is None:
            if expected is not None:
                for gold_req in expected["requirements"]:
                    if exclude_ambiguous_support and gold_req["evidence_support"] == "ambiguous":
                        continue
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
        passed_first_pass = False
        try:
            validate_matching_inputs(profile, preferences, one_document, assessment)
            first_pass_valid += 1
            passed_first_pass = True
        except MatchError as exc:
            # MatchError contains a fixed validator code, never user content.
            errors.append(f"schema_or_invariant_failure:{exc}")
        except ValueError:
            errors.append("validation_failure")
        repair = prediction.get("repair_assessment")
        try:
            rebuilt = build_match_results_resilient(profile, preferences, one_document,
                assessment, repair, evaluated_at=f"{evaluation_date}T00:00:00Z")
        except (MatchError, ValueError):
            rebuilt = None
        resilient_output = rebuilt.get("results", [{}])[0] if rebuilt else {}
        semantically_aggregated = resilient_output.get("semantic_assessment", {}).get("status") == "aggregated"
        valid_cases += bool(semantically_aggregated)
        if resilient_output.get("hard_filter", {}).get("status") == "computed":
            hard_executed += 1
        if rebuilt is not None and actual_result is not None:
            aggregation_checks += 1
            # A caller may have used a different timestamp; compare substantive deterministic fields.
            got = actual_result.get("results", [])
            want = rebuilt.get("results", [])
            stable_keys = ("opportunity_id", "recommendation", "candidate_fit", "experience_alignment",
                           "location_work_mode", "career_alignment", "hard_filter_violations", "warnings", "assessment_scope")
            if len(got) == len(want) and all(all(g.get(k) == w.get(k) for k in stable_keys) for g, w in zip(got, want)):
                aggregation_ok += 1
            else:
                errors.append("deterministic_aggregation_mismatch")
        result = rebuilt
        output = result.get("results", [{}])[0] if result else {}
        pred_assessment = assessment.get("assessments", [{}])[0]
        pred_reqs = {item["id"]: item for item in pred_assessment.get("requirements", [])}
        gold_reqs = {item["id"]: item for item in expected["requirements"]}
        aligned_reqs, unmatched_predictions = _align_prediction_requirements(
            expected["requirements"], pred_reqs)
        case_correct = 0
        aligned_outcomes = {}
        case_scored = sum(1 for req in gold_reqs.values()
                          if not exclude_ambiguous_support or req["evidence_support"] != "ambiguous")
        for req_id, gold_req in gold_reqs.items():
            pred_req = aligned_reqs.get(req_id)
            if pred_req is None:
                continue
            if exclude_ambiguous_support and gold_req["evidence_support"] == "ambiguous":
                continue
            truth, guess = gold_req["expected"], pred_req["outcome"]
            aligned_outcomes[req_id] = guess
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
        unmatched_ids = sorted(item["id"] for item in unmatched_predictions)
        unmatched_positive += sum(item["outcome"] in POSITIVE for item in unmatched_predictions)
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
        for req in pred_reqs.values():
            record_refs = set(req.get("candidate_record_ids", []))
            evidence_refs = set(req.get("candidate_evidence_ids", []))
            if req.get("outcome") == "not_evidenced" and (record_refs or evidence_refs):
                refs_valid_for_case = False
            if req.get("outcome") in POSITIVE and (not record_refs or not evidence_refs):
                refs_valid_for_case = False
            if req.get("outcome") == "contradicted" and (
                    not evidence_refs or any(profile_evidence["id"] in evidence_refs and
                    profile_evidence["extraction"] != "explicit" for profile_evidence in profile["evidence"])):
                refs_valid_for_case = False
        ref_total += 1
        ref_valid += refs_valid_for_case
        hard_checked = (output.get("hard_filter", {}).get("status") == "computed" or
                        bool(output.get("opportunity_id")))
        hard_correct = set(output.get("hard_filter_violations", [])) == set(expected["hard_filter_violations"])
        if hard_checked:
            hard_scored += 1
            hard_ok += hard_correct
            if expected["hard_filter_violations"]:
                explicit_filter_scored += 1
                explicit_filter_ok += hard_correct
        complete_explanation = bool(output.get("explanation")) and all(
            bool(req.get("rationale")) and bool(req.get("job_evidence_ids")) for req in pred_reqs.values())
        explanation_ok += complete_explanation
        got_warnings = set(output.get("warnings", []))
        missing_warnings = sorted(set(expected["required_uncertainties"]) - got_warnings)
        if missing_warnings:
            errors.append("required_uncertainty_warning_missing")
        per_case.append({"case_id": case_id, "status": "evaluated" if semantically_aggregated else "invalid_prediction",
                         "first_pass_valid": passed_first_pass,
                         "post_repair_valid": bool(semantically_aggregated),
                         "hard_filter_executed": hard_checked,
                         "actual_hard_filter_violations": output.get("hard_filter_violations", []),
                         "actual_requirement_outcomes": aligned_outcomes,
                         "requirements": len(gold_reqs), "exact_category_correct": int(case_correct),
                         "category_denominator": case_scored,
                         "ambiguous_requirements_excluded": sum(1 for req in gold_reqs.values()
                             if exclude_ambiguous_support and req["evidence_support"] == "ambiguous"),
                         "hard_filter_checked": hard_checked,
                         "hard_filter_correct": hard_correct if hard_checked else None,
                         "unmatched_prediction_requirement_ids": unmatched_ids,
                         "missing_uncertainties": missing_warnings, "failure_categories": errors})
    tp = sum(guess in POSITIVE and truth in POSITIVE for truth, guess in flattened)
    fp = sum(guess in POSITIVE and truth not in POSITIVE for truth, guess in flattened)
    fn = sum(truth in POSITIVE and guess not in POSITIVE for truth, guess in flattened) + missed_supported
    exact = sum(truth == guess for truth, guess in flattened)
    per_class = {}
    for category in CATEGORIES:
        true_positive = confusion[category][category]
        false_positive_class = sum(confusion[truth][category] for truth in CATEGORIES if truth != category)
        false_negative_class = sum(confusion[category][guess] for guess in CATEGORIES if guess != category)
        false_negative_class += confusion[category]["missing_prediction"]
        per_class[category] = {"precision": _metric(true_positive, true_positive + false_positive_class),
                               "recall": _metric(true_positive, true_positive + false_negative_class)}
    metrics = {
        "requirement_classification_accuracy": _metric(exact, expected_requirement_count),
        "supported_match_precision": _metric(tp, tp + fp),
        "supported_match_recall": _metric(tp, tp + fn),
        "confusion_matrix": confusion,
        "per_class_precision_recall": per_class,
        "evidence_reference_validity": _metric(ref_valid, ref_total),
        "evidence_support_accuracy_adjudicated_only": _metric(support_ok, support_total),
        "ambiguous_evidence_support_unadjudicated": ambiguous,
        "hard_filter_correctness": _metric(hard_ok, hard_total),
        "hard_filter_execution": _metric(hard_executed, attempted),
        "hard_filter_correctness_when_aggregated": _metric(hard_ok, hard_scored),
        "explicit_exclusion_end_to_end_success": _metric(explicit_filter_ok, explicit_filter_total),
        "explicit_exclusion_case_coverage": _metric(explicit_filter_scored, explicit_filter_total),
        "explicit_exclusion_accuracy_when_scored": _metric(explicit_filter_ok, explicit_filter_scored),
        "false_unsupported_match_rate": _metric(false_unsupported, positive_predictions),
        "not_evidenced_handling_recall": _metric(not_evidenced_ok, not_evidenced_total),
        "explanation_completeness_structural": _metric(explanation_ok, explanation_total),
        "schema_invariant_compliance": _metric(valid_cases, attempted),
        "first_pass_schema_invariant_validity": _metric(first_pass_valid, attempted),
        "post_repair_schema_invariant_validity": _metric(valid_cases, attempted),
        "end_to_end_aggregation_success": _metric(valid_cases, attempted),
        "deterministic_aggregation_reproducibility": _metric(aggregation_ok, aggregation_checks)
    }
    return {"report_version": "matching-evaluation-v1", "dataset_version": benchmark["dataset_version"],
            "gold_version": golden["gold_version"], "evaluation_date": evaluation_date,
            "case_count": len(cases), "prediction_attempts": attempted, "missing_prediction_cases": missing_predictions,
            "unmatched_prediction_requirement_count": sum(len(item.get("unmatched_prediction_requirement_ids", [])) for item in per_case),
            "unmatched_positive_prediction_count_unadjudicated": unmatched_positive,
            "ambiguous_requirement_count_excluded_from_accuracy": ambiguous_requirement_count,
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
             f"| Hard-filter execution | {fmt('hard_filter_execution')} |",
             f"| Hard-filter correctness | {fmt('hard_filter_correctness')} |",
             f"| False unsupported-match rate | {fmt('false_unsupported_match_rate')} |",
             f"| Not-evidenced handling recall | {fmt('not_evidenced_handling_recall')} |",
             f"| Explanation completeness (structural) | {fmt('explanation_completeness_structural')} |",
             f"| First-pass schema/invariant validity | {fmt('first_pass_schema_invariant_validity')} |",
             f"| Post-repair schema/invariant validity | {fmt('post_repair_schema_invariant_validity')} |",
             f"| Schema/invariant compliance | {fmt('schema_invariant_compliance')} |",
             f"| End-to-end aggregation success | {fmt('end_to_end_aggregation_success')} |",
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
