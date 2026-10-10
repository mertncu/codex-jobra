"""Prepare human review packets and summarize explicit evaluation judgments.

This module never assigns a review category. Reports omit source text and
predicted values; review packets remain in ignored local storage.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from evaluate_candidate import (
    EvaluationError, _gold_evidence_ok, _key, _prediction_claims, evaluate_dataset,
)
from ingest_resume import IngestionError, ingest_resume
from local_storage import StorageError, write_private_json_atomic


CLAIM_CATEGORIES = frozenset(("valid_extra", "unsupported", "incorrect", "ambiguous"))
EVIDENCE_CATEGORIES = frozenset(("sufficient_support", "insufficient_support", "ambiguous"))


class AdjudicationError(Exception):
    """Fixed, privacy-safe failure code."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _file_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _sources(claim: dict, evidence_by_id: dict, ingestion: dict) -> list[dict]:
    sources = []
    for evidence_id in claim["evidence_ids"]:
        item = evidence_by_id.get(evidence_id)
        if item is None:
            continue
        location = item.get("location")
        source_text = next((segment["text"] for segment in ingestion["segments"]
                            if segment["location"] == location), None)
        sources.append({"ref": evidence_id, "source_document_id": item["source_document_id"],
                        "location": location, "cited_excerpt": item.get("excerpt"),
                        "source_segment": source_text})
    return sources


def build_packet(dataset: dict, resume_dir: Path, predictions_dir: Path,
                 baseline: dict, baseline_sha256: str) -> dict:
    """Reproduce strict results before exposing only their unresolved items."""
    if not isinstance(baseline, dict) or not isinstance(baseline.get("evaluation_date"), str):
        raise AdjudicationError("invalid_baseline")
    try:
        reproduced = evaluate_dataset(dataset, resume_dir, predictions_dir,
                                      baseline["evaluation_date"])
    except (EvaluationError, IngestionError, KeyError, TypeError, ValueError, OSError):
        raise AdjudicationError("invalid_inputs") from None
    if reproduced != baseline or reproduced["prediction_count"] != len(dataset["cases"]):
        raise AdjudicationError("baseline_mismatch")
    if reproduced["scored_prediction_count"] != len(dataset["cases"]):
        raise AdjudicationError("unscored_prediction")

    items = []
    prediction_hashes = {}
    for case in dataset["cases"]:
        case_id = case["id"]
        prediction_path = predictions_dir / f"{case_id}.json"
        profile = json.loads(prediction_path.read_text(encoding="utf-8"))
        prediction_hashes[case_id] = _file_digest(prediction_path)
        ingestion = ingest_resume(resume_dir / case["resume"])
        evidence_by_id = {item["id"]: item for item in profile["evidence"]}
        golden_by_key = defaultdict(list)
        for gold in case["claims"]:
            for value in (gold["value"], *gold.get("aliases", [])):
                golden_by_key[_key(gold["section"], gold["field"], value)].append(gold)
        matched_ids = set()
        for index, claim in enumerate(_prediction_claims(profile), start=1):
            key = _key(claim["section"], claim["field"], claim["value"])
            gold = next((candidate for candidate in golden_by_key[key]
                         if candidate["id"] not in matched_ids), None)
            sources = _sources(claim, evidence_by_id, ingestion)
            if gold is not None:
                matched_ids.add(gold["id"])
                if not _gold_evidence_ok(claim, gold, evidence_by_id, ingestion):
                    items.append({"id": f"{case_id}:evidence:{gold['id']}",
                                  "kind": "evidence_mismatch", "case_id": case_id,
                                  "claim": {"section": claim["section"], "field": claim["field"],
                                            "value": claim["value"]},
                                  "gold_claim_id": gold["id"],
                                  "gold_references": gold["evidence"], "sources": sources})
            elif any(source["source_segment"] is not None and source["cited_excerpt"]
                     and source["cited_excerpt"] in source["source_segment"]
                     and source["source_document_id"] == ingestion["source_document"]["id"]
                     for source in sources):
                items.append({"id": f"{case_id}:claim:{index:03d}",
                              "kind": "unmatched_claim", "case_id": case_id,
                              "claim": {"section": claim["section"], "field": claim["field"],
                                        "value": claim["value"]}, "sources": sources})
    expected_claims = sum(item["unmatched_for_review"] for item in baseline["cases"])
    expected_evidence = sum(len(item["incorrect_evidence_gold_ids"]) for item in baseline["cases"])
    if sum(item["kind"] == "unmatched_claim" for item in items) != expected_claims or \
            sum(item["kind"] == "evidence_mismatch" for item in items) != expected_evidence:
        raise AdjudicationError("packet_count_mismatch")
    body = {"schema_version": "1", "dataset_version": dataset["dataset_version"],
            "baseline_report_sha256": baseline_sha256,
            "prediction_sha256": prediction_hashes, "items": items}
    return {**body, "packet_id": _digest(body)}


def _validate_packet(packet: object, baseline_sha256: str) -> dict:
    if not isinstance(packet, dict):
        raise AdjudicationError("invalid_packet")
    body = {key: value for key, value in packet.items() if key != "packet_id"}
    if (packet.get("schema_version") != "1" or packet.get("packet_id") != _digest(body)
            or packet.get("baseline_report_sha256") != baseline_sha256
            or not isinstance(packet.get("items"), list)):
        raise AdjudicationError("invalid_packet")
    ids = set()
    for item in packet["items"]:
        if not isinstance(item, dict) or item.get("kind") not in ("unmatched_claim", "evidence_mismatch"):
            raise AdjudicationError("invalid_packet")
        if not isinstance(item.get("id"), str) or item["id"] in ids or not isinstance(item.get("sources"), list):
            raise AdjudicationError("invalid_packet")
        if any(not isinstance(source, dict) or not isinstance(source.get("ref"), str)
               for source in item["sources"]):
            raise AdjudicationError("invalid_packet")
        ids.add(item["id"])
    return packet


def validate_judgments(packet: dict, decisions: object) -> list[dict]:
    """Accept only explicit, sourced, non-conflicting human attestations."""
    if not isinstance(decisions, dict) or decisions.get("packet_id") != packet["packet_id"]:
        raise AdjudicationError("invalid_judgments")
    if decisions.get("reviewer_type") != "human" or not isinstance(decisions.get("reviewer"), str) \
            or not decisions["reviewer"].strip():
        raise AdjudicationError("reviewer_required")
    try:
        date.fromisoformat(decisions["reviewed_at"])
    except (KeyError, TypeError, ValueError):
        raise AdjudicationError("invalid_review_date") from None
    judgments = decisions.get("judgments")
    if not isinstance(judgments, list):
        raise AdjudicationError("invalid_judgments")
    by_id = {item["id"]: item for item in packet["items"]}
    seen = set()
    for judgment in judgments:
        if not isinstance(judgment, dict) or judgment.get("item_id") not in by_id:
            raise AdjudicationError("unknown_item")
        item_id = judgment["item_id"]
        if item_id in seen:
            raise AdjudicationError("duplicate_judgment")
        seen.add(item_id)
        item = by_id[item_id]
        categories = CLAIM_CATEGORIES if item["kind"] == "unmatched_claim" else EVIDENCE_CATEGORIES
        if not isinstance(judgment.get("category"), str) or judgment["category"] not in categories:
            raise AdjudicationError("invalid_category")
        if not isinstance(judgment.get("rationale"), str) or not judgment["rationale"].strip():
            raise AdjudicationError("rationale_required")
        valid_refs = {source["ref"] for source in item["sources"]}
        if not valid_refs:
            valid_refs = {"no_source"}
        if not isinstance(judgment.get("source_ref"), str) or judgment["source_ref"] not in valid_refs:
            raise AdjudicationError("invalid_source_reference")
    return judgments


def _ratio(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def summarize(packet: dict, baseline: dict, decisions: dict | None = None) -> dict:
    """Leave unreviewed and ambiguous items unresolved and uncredited."""
    judgments = validate_judgments(packet, decisions) if decisions is not None else []
    by_id = {item["id"]: item for item in packet["items"]}
    claim_counts = {category: 0 for category in CLAIM_CATEGORIES}
    evidence_counts = {category: 0 for category in EVIDENCE_CATEGORIES}
    for judgment in judgments:
        kind = by_id[judgment["item_id"]]["kind"]
        destination = claim_counts if kind == "unmatched_claim" else evidence_counts
        destination[judgment["category"]] += 1
    claim_total = sum(item["kind"] == "unmatched_claim" for item in packet["items"])
    evidence_total = len(packet["items"]) - claim_total
    claim_unreviewed = claim_total - sum(claim_counts.values())
    evidence_unreviewed = evidence_total - sum(evidence_counts.values())
    strict = baseline["metrics"]
    precision = strict["claim_precision"]
    evidence = strict["evidence_attribution_accuracy"]
    unresolved = (claim_unreviewed + claim_counts["ambiguous"]
                  + evidence_unreviewed + evidence_counts["ambiguous"])
    return {
        "schema_version": "1", "dataset_version": packet["dataset_version"],
        "packet_id": packet["packet_id"], "baseline_report_sha256": packet["baseline_report_sha256"],
        "status": "pending_independent_review" if unresolved else "review_complete",
        "reviewer": decisions["reviewer"] if decisions is not None else None,
        "reviewed_at": decisions["reviewed_at"] if decisions is not None else None,
        "judgments_sha256": _digest(decisions) if decisions is not None else None,
        "original_strict_metrics": strict,
        "review_counts": {"total_items": len(packet["items"]), "adjudicated_items": len(judgments),
                          "unresolved_items": unresolved,
                          "unmatched_claims": {"total": claim_total, "unreviewed": claim_unreviewed,
                                               **claim_counts},
                          "evidence_mismatches": {"total": evidence_total, "unreviewed": evidence_unreviewed,
                                                  **evidence_counts},
                          "confirmed_incorrect_or_unsupported": claim_counts["incorrect"] + claim_counts["unsupported"]},
        "review_adjusted_metrics": {
            "claim_precision_lower_bound": _ratio(precision["numerator"] + claim_counts["valid_extra"],
                                                  precision["denominator"]),
            "evidence_accuracy_on_strict_matches_lower_bound":
                _ratio(evidence["numerator"] + evidence_counts["sufficient_support"],
                       evidence["denominator"]),
        },
        "limitations": ["Unreviewed or ambiguous items receive no credit.",
                        "Evidence accuracy covers only originally matched claims; evidence for valid extras is not scored.",
                        "Reviewer identity is an attestation, not independently authenticated."],
    }


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise AdjudicationError("unreadable_json") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or summarize Jobra evaluation adjudication")
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--dataset", type=Path, default=Path(__file__).resolve().parents[3] / "evaluation/golden.v1.json")
    prepare.add_argument("--resumes", type=Path, default=Path(__file__).resolve().parents[3] / "evaluation/resumes")
    prepare.add_argument("--predictions", type=Path, required=True)
    prepare.add_argument("--baseline-report", type=Path, required=True)
    prepare.add_argument("--workspace", type=Path, default=Path.cwd())
    score = sub.add_parser("score")
    score.add_argument("--packet", type=Path, required=True)
    score.add_argument("--judgments", type=Path)
    score.add_argument("--dataset", type=Path, default=Path(__file__).resolve().parents[3] / "evaluation/golden.v1.json")
    score.add_argument("--resumes", type=Path, default=Path(__file__).resolve().parents[3] / "evaluation/resumes")
    score.add_argument("--predictions", type=Path, required=True)
    score.add_argument("--baseline-report", type=Path, required=True)
    score.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        baseline_sha = _file_digest(args.baseline_report)
        baseline = _read_json(args.baseline_report)
        if args.action == "prepare":
            packet = build_packet(_read_json(args.dataset), args.resumes, args.predictions,
                                  baseline, baseline_sha)
            output = write_private_json_atomic(args.workspace, "evaluations",
                                               f"adjudication-packet-{uuid4().hex}.json", packet)
            result = {"status": "review_packet", "output": str(output.relative_to(args.workspace)),
                      "items": len(packet["items"])}
        else:
            packet = _validate_packet(_read_json(args.packet), baseline_sha)
            regenerated = build_packet(_read_json(args.dataset), args.resumes, args.predictions,
                                       baseline, baseline_sha)
            if packet != regenerated:
                raise AdjudicationError("packet_mismatch")
            decisions = _read_json(args.judgments) if args.judgments else None
            report = summarize(packet, baseline, decisions)
            output = write_private_json_atomic(args.workspace, "evaluations",
                                               f"adjudication-report-{uuid4().hex}.json", report)
            result = {"status": report["status"], "output": str(output.relative_to(args.workspace)),
                      "adjudicated_items": report["review_counts"]["adjudicated_items"],
                      "unresolved_items": report["review_counts"]["unresolved_items"]}
    except (AdjudicationError, StorageError, OSError, TypeError, ValueError, KeyError):
        parser.exit(1, "adjudication failed: invalid_input_or_storage\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
