"""Connect an integrated discovery run to fresh matching and private results.

This module prepares references and persists Codex-produced interpretations; it
does not perform discovery or semantic matching itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from local_storage import (StorageError, write_private_json_atomic,
                           write_private_text_atomic)
from match_opportunities import (MatchError, build_match_results_resilient,
                                 build_reference_catalog,
                                 explicit_exclusion_decisions,
                                 _markdown_url, _md_text,
                                 render_match_results_markdown,
                                 save_match_results)
from prepare_pipeline import (PreparationError, read_manifest, save_run_manifest,
                              transition_stage)
from validate_opportunities import validate_opportunities
from validate_profile import validate_document


class MatchingIntegrationError(ValueError):
    """Fixed-code, privacy-safe matching integration error."""


def _read_reference(reference, workspace, category):
    if not isinstance(reference, dict):
        raise MatchingIntegrationError("required_input_reference_missing")
    root = Path(workspace).resolve()
    private = root / ".jobra"
    if private.is_symlink():
        raise MatchingIntegrationError("unsafe_private_storage")
    path = root / reference.get("path", "")
    parent = private / category
    if path.is_symlink() or parent.is_symlink():
        raise MatchingIntegrationError("unsafe_private_storage")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(parent.resolve(strict=True))
        raw = resolved.read_bytes()
    except (OSError, ValueError):
        raise MatchingIntegrationError("required_input_unavailable") from None
    if hashlib.sha256(raw).hexdigest() != reference.get("sha256"):
        raise MatchingIntegrationError("input_hash_mismatch")
    try:
        return json.loads(raw.decode("utf-8")), resolved
    except (UnicodeError, ValueError):
        raise MatchingIntegrationError("input_document_invalid") from None


def _save_revision(manifest, workspace, previous_path):
    try:
        path = save_run_manifest(manifest, workspace, previous_path=previous_path)
    except (PreparationError, StorageError):
        raise MatchingIntegrationError("manifest_persistence_failed") from None
    return manifest, path


def _advance(manifest, workspace, path, stage, status, *, reason=None, error_code=None):
    try:
        updated = transition_stage(manifest, stage, status, reason=reason,
                                   error_code=error_code)
    except PreparationError as exc:
        raise MatchingIntegrationError(exc.code) from None
    return _save_revision(updated, workspace, path)


def _discovery_inputs(manifest, workspace):
    allowed = {"completed", "partial"}
    for stage in ("live_discovery", "opportunity_validation_and_persistence",
                  "deduplication_and_freshness"):
        if manifest["stages"][stage]["status"] not in allowed:
            raise MatchingIntegrationError("discovery_stage_not_usable")
    profile, _ = _read_reference(manifest["inputs"]["candidate_profile"], workspace, "profiles")
    preferences, _ = _read_reference(manifest["inputs"]["search_preferences"], workspace, "discovery")
    snapshot, snapshot_path = _read_reference(manifest["artifacts"]["opportunity_snapshot"], workspace, "opportunities")
    audit, audit_path = _read_reference(manifest["artifacts"]["discovery_audit"], workspace, "discovery")
    if validate_document(profile, "candidate_profile") or profile.get("verification_status") != "verified":
        raise MatchingIntegrationError("candidate_profile_must_be_verified")
    if validate_document(preferences, "search_preferences"):
        raise MatchingIntegrationError("search_preferences_invalid")
    if validate_opportunities(snapshot):
        raise MatchingIntegrationError("opportunity_snapshot_invalid")
    if not isinstance(audit, dict) or audit.get("run_id") != manifest["run_id"] or not isinstance(audit.get("observations"), list):
        raise MatchingIntegrationError("discovery_audit_invalid")
    return profile, preferences, snapshot, snapshot_path, audit, audit_path


def _audit_opportunity_states(audit):
    states = {}
    for item in audit["observations"]:
        if isinstance(item, dict) and isinstance(item.get("opportunity_id"), str):
            states[item["opportunity_id"]] = item.get("status", "unknown")
    return states


def _select_ids(snapshot, audit, maximum, selected_ids=None):
    records = snapshot["opportunities"]
    by_id = {item["id"]: item for item in records}
    states = _audit_opportunity_states(audit)
    fresh = [item["id"] for item in records if states.get(item["id"]) == "accepted_distinct"]
    reobserved = [item["id"] for item in records
                  if states.get(item["id"]) == "merged_same_opportunity"]
    possible = {item["id"] for item in records
                if states.get(item["id"]) == "possible_duplicate_requires_review"}
    if selected_ids is not None:
        if (not isinstance(selected_ids, (list, tuple)) or not selected_ids or
                any(not isinstance(identifier, str) or not identifier for identifier in selected_ids) or
                len(selected_ids) != len(set(selected_ids))):
            raise MatchingIntegrationError("selected_opportunity_ids_invalid")
        if len(selected_ids) > maximum:
            raise MatchingIntegrationError("assessment_budget_exceeded")
        if any(identifier not in by_id for identifier in selected_ids):
            raise MatchingIntegrationError("selected_opportunity_not_found")
        return list(selected_ids), possible
    previously_saved = [item["id"] for item in records if item["id"] not in states]
    # Possible duplicates remain visible but are not silently treated as unique
    # assessment targets. A user can explicitly select one for a review.
    ordered = fresh + reobserved + previously_saved
    return ordered[:maximum], possible


def prepare_matching_stage(manifest_path, workspace, selected_ids=None):
    """Create a fresh current catalog and advance the run to semantic assessment."""
    workspace = Path(workspace).resolve()
    try:
        manifest, current_path = read_manifest(manifest_path, workspace)
    except PreparationError as exc:
        raise MatchingIntegrationError(exc.code) from None
    if manifest["stages"]["matching_catalog_preparation"]["status"] not in ("pending", "partial", "failed"):
        raise MatchingIntegrationError("matching_catalog_stage_not_executable")
    if manifest["stages"]["semantic_assessment"]["status"] != "pending":
        raise MatchingIntegrationError("semantic_assessment_stage_already_started")
    profile, preferences, snapshot, snapshot_path, audit, audit_path = _discovery_inputs(manifest, workspace)
    selected, possible_duplicates = _select_ids(
        snapshot, audit, manifest["limits"]["max_opportunities_to_assess"], selected_ids)
    if not selected:
        raise MatchingIntegrationError("no_eligible_opportunities")

    manifest, current_path = _advance(manifest, workspace, current_path,
                                       "matching_catalog_preparation", "running")
    selected_document = {"schema_version": "1", "opportunities": snapshot["opportunities"]}
    try:
        selected_opportunities = {"schema_version": "1", "opportunities": [
            item for item in snapshot["opportunities"] if item["id"] in selected]}
        hard_exclusion_decisions = explicit_exclusion_decisions(selected_opportunities, preferences)
        hard_excluded = {item["opportunity_id"] for item in hard_exclusion_decisions}
        assessment_ids = [identifier for identifier in selected if identifier not in hard_excluded]
        catalog = build_reference_catalog(profile, preferences, selected_document, assessment_ids or selected)
        if not assessment_ids:
            catalog["opportunities"] = []
        catalog["pipeline_context"] = {
            "run_id": manifest["run_id"],
            "discovery_snapshot": manifest["artifacts"]["opportunity_snapshot"],
            "discovery_audit": manifest["artifacts"]["discovery_audit"],
            "selected_opportunity_ids": selected,
            "assessment_opportunity_ids": assessment_ids,
            "explicitly_excluded_ids": sorted(hard_excluded),
            "possible_duplicate_ids": sorted(possible_duplicates),
            "explicit_exclusions": hard_exclusion_decisions,
        }
        catalog_path = write_private_json_atomic(
            workspace, "matches", f"catalog-{manifest['run_id']}-{uuid4().hex}.json", catalog)
    except (MatchError, StorageError):
        manifest, current_path = _advance(manifest, workspace, current_path,
            "matching_catalog_preparation", "failed", error_code="matching_catalog_preparation_failed")
        raise MatchingIntegrationError("matching_catalog_preparation_failed") from None

    manifest["artifacts"]["matching_catalog"] = {
        "path": catalog_path.resolve().relative_to(workspace).as_posix(),
        "sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest()}
    manifest, current_path = _advance(manifest, workspace, current_path,
                                      "matching_catalog_preparation", "completed")
    manifest, current_path = _advance(manifest, workspace, current_path,
                                      "semantic_assessment", "running")
    return {"manifest": manifest, "manifest_path": current_path,
            "catalog_path": catalog_path, "selected_opportunity_ids": selected,
            "assessment_opportunity_ids": assessment_ids,
            "possible_duplicate_ids": sorted(possible_duplicates),
            "snapshot_path": snapshot_path, "audit_path": audit_path}


def _discovery_audit_summary(audit):
    visible_statuses = {"explicitly_rejected", "source_inaccessible", "invalid_observation",
                        "possible_duplicate_requires_review"}
    summaries = []
    for item in audit["observations"]:
        if not isinstance(item, dict) or item.get("status") not in visible_statuses:
            continue
        summary = {key: value for key, value in item.items()
             if key in ("observation_id", "opportunity_id", "status", "reason_code",
                        "reason_codes", "source_url", "relationship")}
        submitted = item.get("submitted_opportunity")
        if isinstance(submitted, dict):
            claims = submitted.get("claims", {})
            summary["opportunity_id"] = submitted.get("id")
            summary["title"] = claims.get("title", {}).get("value") if isinstance(claims, dict) else None
            summary["employer"] = claims.get("employer", {}).get("value") if isinstance(claims, dict) else None
            summary["source_url"] = submitted.get("original_url") or summary.get("source_url")
        summaries.append(summary)
    return summaries


def _render_pipeline_report(results, opportunities, audit_summary, context):
    report = render_match_results_markdown(results, opportunities)
    report = report.replace("# Private Jobra Matching Results",
        "# Private Jobra Discovery-to-Results\n\n"
        f"- Discovery run: `{context['run_id']}`\n"
        f"- Discovery snapshot: `{context['discovery_snapshot_path']}`\n"
        f"- Matching snapshot: `{context['result_snapshot_path']}`\n"
        "- Newly discovered records are identified from this run's audit. Other snapshot records are previously saved.\n"
        "- This is a Codex semantic assessment with deterministic validation and aggregation.\n\n"
        "## Opportunity results")
    lines = [report.rstrip(), "", "## Discovery audit items", ""]
    if not audit_summary:
        lines.append("No excluded, inaccessible, invalid, or possible-duplicate observations were recorded.")
    for item in audit_summary:
        status = item.get("status", "unknown")
        identifier = item.get("observation_id", "unidentified observation")
        codes = item.get("reason_codes")
        reason = item.get("reason_code") or (
            ", ".join(code for code in codes if isinstance(code, str))
            if isinstance(codes, list) else "no reason code")
        lines.append(f"- `{identifier}` — **{status}**; reason: `{reason}`")
        if item.get("source_url"):
            lines.append(f"  - Source: <{_markdown_url(item['source_url'])}>")
        if item.get("opportunity_id"):
            lines.append(f"  - Opportunity: `{item['opportunity_id']}`")
        if item.get("title") or item.get("employer"):
            identity = " — ".join(value for value in (item.get("employer"), item.get("title")) if value)
            lines.append(f"  - Listing: {_md_text(identity)}")
    return "\n".join(lines) + "\n"


def finalize_matching_stage(manifest_path, workspace, interpretation=None, repair_interpretation=None):
    """Validate/aggregate supplied assessments, preserving partial failures."""
    workspace = Path(workspace).resolve()
    try:
        manifest, current_path = read_manifest(manifest_path, workspace)
    except PreparationError as exc:
        raise MatchingIntegrationError(exc.code) from None
    if manifest["stages"]["semantic_assessment"]["status"] != "running":
        raise MatchingIntegrationError("semantic_assessment_not_running")
    if manifest["stages"]["aggregation_and_results"]["status"] != "pending":
        raise MatchingIntegrationError("aggregation_stage_already_started")
    profile, preferences, snapshot, snapshot_path, audit, _ = _discovery_inputs(manifest, workspace)
    catalog, _ = _read_reference(manifest["artifacts"]["matching_catalog"], workspace, "matches")
    selected = catalog.get("pipeline_context", {}).get("selected_opportunity_ids")
    assessment_ids = catalog.get("pipeline_context", {}).get("assessment_opportunity_ids")
    if not isinstance(selected, list) or not selected or not isinstance(assessment_ids, list):
        raise MatchingIntegrationError("matching_catalog_invalid")
    if interpretation is None:
        interpretation = {"schema_version": "1", "assessments": []}
    try:
        if manifest["artifacts"]["assessment"] is not None:
            raise MatchingIntegrationError("assessment_artifact_already_exists")
        assessment_path = write_private_json_atomic(
            workspace, "matches", f"assessment-{manifest['run_id']}-{uuid4().hex}.json", interpretation)
        assessment_reference = {"path": assessment_path.resolve().relative_to(workspace).as_posix(),
                                "sha256": hashlib.sha256(assessment_path.read_bytes()).hexdigest()}
        if repair_interpretation is not None:
            repair_path = write_private_json_atomic(
                workspace, "matches", f"assessment-repair-{manifest['run_id']}-{uuid4().hex}.json", repair_interpretation)
            repair_reference = {"path": repair_path.resolve().relative_to(workspace).as_posix(),
                                "sha256": hashlib.sha256(repair_path.read_bytes()).hexdigest()}
        else:
            repair_reference = None
    except StorageError:
        raise MatchingIntegrationError("assessment_persistence_failed") from None

    manifest["artifacts"]["assessment"] = assessment_reference
    manifest, current_path = _advance(manifest, workspace, current_path,
                                      "aggregation_and_results", "running")
    try:
        result = build_match_results_resilient(
            profile, preferences, snapshot, interpretation, repair_interpretation,
            selected_ids=None)
    except MatchError as exc:
        manifest, current_path = _advance(manifest, workspace, current_path,
            "aggregation_and_results", "failed", error_code="result_aggregation_failed")
        raise MatchingIntegrationError("result_aggregation_failed") from None

    audit_states = _audit_opportunity_states(audit)
    selected_set = set(selected)
    assessment_set = set(assessment_ids)
    possible_duplicates = set(catalog["pipeline_context"].get("possible_duplicate_ids", []))
    for item in result["results"]:
        identifier = item["opportunity_id"]
        audit_status = audit_states.get(identifier)
        if audit_status == "accepted_distinct":
            origin = "newly_discovered"
        elif audit_status == "possible_duplicate_requires_review":
            origin = "newly_observed_possible_duplicate"
        else:
            origin = "previously_saved"
        item["discovery_origin"] = {
            "classification": origin,
            "discovery_audit_status": audit_status,
            "assessment_selected": identifier in assessment_set,
            "possible_duplicate_requires_review": identifier in possible_duplicates,
        }
        if identifier in possible_duplicates:
            item.setdefault("warnings", []).append("possible_duplicate_requires_review")
    result["pipeline"] = {"run_id": manifest["run_id"],
        "discovery_snapshot": manifest["artifacts"]["opportunity_snapshot"],
        "discovery_audit": manifest["artifacts"]["discovery_audit"],
        "matching_catalog": manifest["artifacts"]["matching_catalog"],
        "assessment": assessment_reference, "repair_assessment": repair_reference,
        "selected_opportunity_ids": selected}
    try:
        result_path = save_match_results(result, workspace)
        result["pipeline"]["result_snapshot_path"] = result_path.resolve().relative_to(workspace).as_posix()
        report = _render_pipeline_report(result, snapshot, _discovery_audit_summary(audit), {
            "run_id": manifest["run_id"],
            "discovery_snapshot_path": manifest["artifacts"]["opportunity_snapshot"]["path"],
            "result_snapshot_path": result_path.resolve().relative_to(workspace).as_posix()})
        # Save JSON again would violate immutability, so the snapshot intentionally
        # contains all references except its own path; the manifest is authoritative.
        report_path = write_private_text_atomic(workspace, "matches",
            result_path.stem + "-pipeline.md", report)
    except (StorageError, OSError):
        manifest, current_path = _advance(manifest, workspace, current_path,
            "aggregation_and_results", "failed", error_code="result_persistence_failed")
        raise MatchingIntegrationError("result_persistence_failed") from None

    statuses = {item["workflow_status"] for item in result["results"]}
    chosen_statuses = {item["workflow_status"] for item in result["results"]
                       if item["opportunity_id"] in assessment_set and
                       item["workflow_status"] != "excluded_by_explicit_user_constraint"}
    if "assessment_failed_validation" in chosen_statuses:
        semantic_target, semantic_reason = "partial", "assessment_validation_failures"
    elif chosen_statuses != {"successfully_assessed"}:
        semantic_target, semantic_reason = "partial", "assessments_incomplete"
    elif len(selected_set) < len(snapshot["opportunities"]):
        semantic_target, semantic_reason = "partial", "assessment_budget_left_unassessed_records"
    else:
        semantic_target, semantic_reason = "completed", None
    manifest["artifacts"]["assessment"] = assessment_reference
    manifest["artifacts"]["result_snapshot"] = {
        "path": result_path.resolve().relative_to(workspace).as_posix(),
        "sha256": hashlib.sha256(result_path.read_bytes()).hexdigest()}
    manifest["artifacts"]["result_report"] = {
        "path": report_path.resolve().relative_to(workspace).as_posix(),
        "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest()}
    manifest, current_path = _advance(manifest, workspace, current_path,
        "semantic_assessment", semantic_target,
        reason=semantic_reason if semantic_target == "partial" else None)
    if statuses - {"successfully_assessed", "excluded_by_explicit_user_constraint"}:
        aggregation_target, aggregation_reason = "partial", "unassessed_or_failed_opportunities_visible"
    elif semantic_target == "partial":
        aggregation_target, aggregation_reason = "partial", "semantic_work_incomplete"
    else:
        aggregation_target, aggregation_reason = "completed", None
    manifest, current_path = _advance(manifest, workspace, current_path,
        "aggregation_and_results", aggregation_target,
        reason=aggregation_reason if aggregation_target == "partial" else None)
    return {"manifest": manifest, "manifest_path": current_path,
            "result": result, "result_snapshot_path": result_path,
            "result_report_path": report_path, "semantic_stage_status": semantic_target,
            "aggregation_stage_status": aggregation_target}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Continue a discovery run into fresh local matching results")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="build a fresh catalog from an integrated discovery snapshot")
    prepare.add_argument("--workspace", type=Path, default=Path.cwd())
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--opportunity-id", action="append", dest="selected_ids")
    finalize = sub.add_parser("finalize", help="validate assessments, aggregate results, and finish manifest stages")
    finalize.add_argument("--workspace", type=Path, default=Path.cwd())
    finalize.add_argument("--manifest", type=Path, required=True)
    finalize.add_argument("--assessment", type=Path)
    finalize.add_argument("--repair", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_matching_stage(args.manifest, args.workspace, args.selected_ids)
            workspace = args.workspace.resolve()
            output = {"status": "prepared", "manifest": str(result["manifest_path"].relative_to(workspace)),
                      "catalog": str(result["catalog_path"].relative_to(workspace)),
                      "selected_opportunity_ids": result["selected_opportunity_ids"],
                      "assessment_opportunity_ids": result["assessment_opportunity_ids"],
                      "possible_duplicate_ids": result["possible_duplicate_ids"]}
        else:
            assessment = json.loads(args.assessment.read_text(encoding="utf-8")) if args.assessment else None
            repair = json.loads(args.repair.read_text(encoding="utf-8")) if args.repair else None
            result = finalize_matching_stage(args.manifest, args.workspace, assessment, repair)
            workspace = args.workspace.resolve()
            output = {"status": result["manifest"]["run_status"],
                      "manifest": str(result["manifest_path"].relative_to(workspace)),
                      "result_snapshot": str(result["result_snapshot_path"].relative_to(workspace)),
                      "result_report": str(result["result_report_path"].relative_to(workspace)),
                      "semantic_stage": result["semantic_stage_status"],
                      "aggregation_stage": result["aggregation_stage_status"]}
    except (MatchingIntegrationError, MatchError, StorageError, OSError, UnicodeError, ValueError):
        parser.exit(1, "matching integration failed: see private run manifest for safe stage diagnostics\n")
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
