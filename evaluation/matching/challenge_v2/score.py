"""Score blind Codex assessments only after their prediction files are frozen."""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "evaluation"))
sys.path.insert(0, str(ROOT / "evaluation/matching"))
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))
from evaluate_matching import _write_private_markdown, evaluate, render_markdown
from local_storage import StorageError, write_private_json_atomic
from match_opportunities import MatchError, build_match_results, validate_matching_inputs

BASE = Path(__file__).resolve().parent


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score(prediction_file: Path, workspace: Path, run_id: str, session_id: str,
          prediction_completed_at: str | None = None):
    frozen = json.loads((BASE / "freeze.v2.json").read_text(encoding="utf-8"))
    input_path, labels_path = BASE / "inputs.v2.json", BASE / "labels.v2.json"
    if _sha(input_path) != frozen["input_sha256"] or _sha(labels_path) != frozen["labels_sha256"]:
        raise ValueError("frozen_benchmark_integrity_failure")
    if run_id != frozen["prediction_run_id"]:
        raise ValueError("prediction_run_id_mismatch")
    benchmark = json.loads(input_path.read_text(encoding="utf-8"))
    golden = json.loads(labels_path.read_text(encoding="utf-8"))
    raw = json.loads(prediction_file.read_text(encoding="utf-8"))
    predictions = raw.get("predictions", [])
    ids = [item.get("case_id") for item in predictions]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_prediction_case")
    cases = {item["id"]: item for item in benchmark["cases"]}
    opportunities = {item["id"]: item for item in benchmark["opportunities"]["opportunities"]}
    completed = []
    for item in predictions:
        case = cases.get(item.get("case_id"))
        if case is None or "assessment" not in item:
            raise ValueError("prediction_case_mismatch")
        profile = benchmark["candidates"][case["candidate"]]
        preferences = benchmark["preferences"][case["preferences"]]
        one_opportunity = {"schema_version": "1", "opportunities": [opportunities[case["opportunity"]]]}
        result = None
        try:
            validate_matching_inputs(profile, preferences, one_opportunity, item["assessment"])
            result = build_match_results(profile, preferences, one_opportunity, item["assessment"],
                                         evaluated_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
        except (MatchError, ValueError):
            pass
        completed.append({**item, "result": result})
    report = evaluate(benchmark, golden, completed, datetime.now(timezone.utc).date().isoformat(),
                      exclude_ambiguous_support=True)
    report["report_version"] = "matching-blind-challenge-v2"
    report["evaluation_context"] = {"status": "separate_clean_projectless_codex_task",
        "prediction_session_id": session_id,
        "note": "The prediction task received the frozen synthetic inputs and documented matching contract only; it had no repository, labels, prior reports, or evaluator output."}
    # The generic V1 evaluator is intentionally unblinded; replace its context
    # limitation for this independently isolated V2 run while retaining the
    # other applicable caveats.
    report["limitations"] = [
        "Small synthetic benchmark; no real-world performance or production-readiness claim.",
        "Golden labels are frozen and independently authored but have not received independent human adjudication.",
        "Evidence-support accuracy excludes ambiguous judgments; six support labels remain unadjudicated.",
        "Explanations are checked for required structure, not semantic quality.",
        "The earlier eight-opportunity live pilot is observational only and is not ground truth.",
    ]
    report["run_manifest"] = {"benchmark_version": frozen["benchmark_version"], "prediction_run_id": run_id,
        "input_sha256": frozen["input_sha256"], "labels_sha256": frozen["labels_sha256"],
        "predictions_sha256": _sha(prediction_file), "frozen_at_utc": frozen["frozen_at_utc"],
        "prediction_completed_at_utc": prediction_completed_at,
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    stem = f"matching-challenge-v2-{run_id}-{uuid4().hex}"
    report_path = write_private_json_atomic(workspace, "evaluations", stem + ".json", report)
    return report, report_path, prediction_file, render_markdown(report)


def main():
    parser = argparse.ArgumentParser(description="Score frozen blind matching challenge predictions")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--prediction-completed-at", help="Codex task completion time in UTC ISO 8601")
    parser.add_argument("--workspace", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        report, report_path, prediction_path, markdown = score(args.predictions, args.workspace,
                                                               args.run_id, args.session_id,
                                                               args.prediction_completed_at)
        markdown_path = _write_private_markdown(args.workspace,
            report_path.stem + "-human.md", markdown)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, StorageError):
        parser.exit(1, "matching evaluation failed: invalid_input_or_storage\n")
    print(json.dumps({"status": "scored", "case_count": report["case_count"],
                      "report": str(report_path.relative_to(args.workspace)),
                      "predictions": str(prediction_path.relative_to(args.workspace)),
                      "human_report": str(markdown_path.relative_to(args.workspace))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
