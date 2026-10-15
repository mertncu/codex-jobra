"""Validate Codex-produced discovery observations and persist an auditable snapshot.

This module never searches the web. It accepts observations from the skill, uses
the existing opportunity contract and lifecycle helpers, and creates private,
immutable artifacts plus manifest revisions.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4
from urllib.parse import urlsplit

from local_storage import StorageError, write_private_json_atomic
from opportunity_lifecycle import LifecycleError, classify_relationship, merge_same_opportunity, freshness_state
from prepare_pipeline import PreparationError, read_manifest, save_run_manifest, transition_stage
from save_opportunities import OpportunityError, save_opportunities
from validate_opportunities import validate_opportunities


class DiscoveryIntegrationError(ValueError):
    """Fixed-code integration error; never includes posting or candidate text."""

    def __init__(self, code: str, manifest_path: Path | None = None):
        super().__init__(code)
        self.code = code
        self.manifest_path = manifest_path


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _file_reference(path: Path, workspace: Path):
    raw = path.read_bytes()
    return {"path": path.resolve().relative_to(workspace.resolve()).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest()}


def _read_reference(reference, workspace, category):
    if not isinstance(reference, dict):
        raise DiscoveryIntegrationError("required_artifact_missing")
    root = Path(workspace).resolve()
    private = root / ".jobra"
    if private.is_symlink():
        raise DiscoveryIntegrationError("unsafe_private_storage")
    path = root / reference["path"]
    expected_parent = private / category
    if path.is_symlink() or expected_parent.is_symlink():
        raise DiscoveryIntegrationError("unsafe_private_storage")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(expected_parent.resolve(strict=True))
        raw = resolved.read_bytes()
    except (OSError, ValueError):
        raise DiscoveryIntegrationError("required_artifact_unavailable") from None
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise DiscoveryIntegrationError("artifact_hash_mismatch")
    try:
        return json.loads(raw.decode("utf-8")), resolved
    except (UnicodeError, ValueError):
        raise DiscoveryIntegrationError("artifact_invalid") from None


def _save_revision(manifest, workspace, previous_path):
    try:
        path = save_run_manifest(manifest, workspace, previous_path=previous_path)
    except (PreparationError, StorageError):
        raise DiscoveryIntegrationError("manifest_persistence_failed") from None
    return manifest, path


def _persist_transition(manifest, workspace, manifest_path, stage, status, *, error_code=None, reason=None):
    try:
        updated = transition_stage(manifest, stage, status, error_code=error_code, reason=reason)
    except PreparationError as exc:
        raise DiscoveryIntegrationError(exc.code, manifest_path) from None
    return _save_revision(updated, workspace, manifest_path)


def _eligibility(manifest):
    required = ("candidate_profile_validation", "search_preferences_validation",
                "opportunity_snapshot_selection", "discovery_plan_preparation")
    if any(manifest["stages"][name]["status"] != "completed" for name in required):
        raise DiscoveryIntegrationError("pipeline_inputs_not_ready")
    if manifest["stages"]["live_discovery"]["status"] not in ("pending", "partial", "failed"):
        raise DiscoveryIntegrationError("discovery_stage_not_executable")
    if manifest["stages"]["opportunity_validation_and_persistence"]["status"] != "pending":
        raise DiscoveryIntegrationError("opportunity_stage_already_started")
    if manifest["stages"]["deduplication_and_freshness"]["status"] != "pending":
        raise DiscoveryIntegrationError("lifecycle_stage_already_started")


def _check_observation_envelope(manifest, payload, plan):
    if not isinstance(payload, dict) or payload.get("schema_version") != "1":
        return "observations_contract_invalid"
    queries = payload.get("queries_executed")
    observations = payload.get("observations")
    execution_status = payload.get("execution_status")
    if (not isinstance(queries, list) or not all(isinstance(q, str) for q in queries) or
            len(queries) != len(set(queries)) or execution_status not in ("completed", "partial", "interrupted") or
            not isinstance(observations, list)):
        return "observations_contract_invalid"
    observation_ids = [item.get("observation_id") for item in observations
                       if isinstance(item, dict) and isinstance(item.get("observation_id"), str)]
    if len(observation_ids) != len(set(observation_ids)):
        return "duplicate_observation_identifier"
    allowed_queries = plan.get("queries")
    if not isinstance(allowed_queries, list) or any(query not in allowed_queries for query in queries):
        return "query_outside_prepared_plan"
    if len(queries) > manifest["limits"]["max_discovery_queries"]:
        return "query_budget_exceeded"
    if len(observations) > manifest["limits"]["max_opportunities_to_discover"]:
        return "opportunity_budget_exceeded"
    planned_target = plan.get("target_maximum", manifest["limits"]["max_opportunities_to_discover"])
    if len(observations) > min(planned_target, manifest["limits"]["max_opportunities_to_discover"]):
        return "opportunity_budget_exceeded"
    if execution_status == "completed" and not queries:
        return "executed_query_list_missing"
    return None


def _single_record_errors(record):
    if not isinstance(record, dict):
        return ["opportunity_record_invalid"]
    return validate_opportunities({"schema_version": "1", "opportunities": [record]})


def _record_observation_errors(observation):
    if not isinstance(observation, dict):
        return ["observation_invalid"]
    if not isinstance(observation.get("observation_id"), str) or not re.fullmatch(r"obs_[A-Za-z0-9_-]{1,64}", observation["observation_id"]):
        return ["observation_identifier_invalid"]
    outcome = observation.get("outcome")
    if outcome == "opportunity":
        return _single_record_errors(observation.get("opportunity"))
    if outcome == "inaccessible":
        if not isinstance(observation.get("source_url"), str) or not observation.get("source_url"):
            return ["inaccessible_source_reference_missing"]
        parts = urlsplit(observation["source_url"])
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None or parts.password is not None:
            return ["inaccessible_source_reference_invalid"]
        if not isinstance(observation.get("reason_code"), str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", observation["reason_code"]):
            return ["inaccessible_reason_invalid"]
        return []
    if outcome == "rejected":
        if not isinstance(observation.get("reason_code"), str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", observation["reason_code"]):
            return ["rejection_reason_required"]
        return []
    return ["observation_outcome_invalid"]


def _append_valid_record(catalog, record, audit_entry):
    """Conservatively merge trusted identity matches; keep review candidates distinct."""
    candidate = deepcopy(record)
    for index, prior in enumerate(catalog):
        relationship, reason = classify_relationship(prior, candidate)
        if relationship == "same_opportunity_high_confidence":
            try:
                catalog[index] = merge_same_opportunity(prior, candidate)
                audit_entry.update(status="merged_same_opportunity", relationship=relationship,
                                   relationship_reason=reason, merged_into=prior["id"])
                return
            except LifecycleError:
                audit_entry.update(status="possible_duplicate_requires_review",
                                   relationship="possible_duplicate_requires_review",
                                   relationship_reason="identity matched but records conflict; no merge performed",
                                   review_required=True)
                return
        if relationship == "possible_duplicate_requires_review":
            audit_entry.update(status="possible_duplicate_requires_review",
                               relationship=relationship, relationship_reason=reason,
                               compared_with=prior["id"], review_required=True)
            # Preserve the valid source record independently; only its relationship is uncertain.
            catalog.append(candidate)
            return
    catalog.append(candidate)
    audit_entry.update(status="accepted_distinct", relationship="distinct_opportunities")


def execute_discovery(manifest_path, payload, workspace):
    """Consume Codex observations, validate, deduplicate, and persist private artifacts.

    One invalid observation is isolated in the audit. Valid observations are
    retained and can still produce a partial usable snapshot.
    """
    workspace = Path(workspace).resolve()
    try:
        manifest, current_path = read_manifest(manifest_path, workspace)
    except PreparationError as exc:
        raise DiscoveryIntegrationError(exc.code) from None
    _eligibility(manifest)
    try:
        plan, _ = _read_reference(manifest["artifacts"]["discovery_query_plan"], workspace, "discovery")
        selected_document = None
        selected_ref = manifest["inputs"]["selected_opportunity_snapshot"]
        if selected_ref is not None:
            selected_document, _ = _read_reference(selected_ref, workspace, "opportunities")
            if validate_opportunities(selected_document):
                raise DiscoveryIntegrationError("saved_opportunity_snapshot_invalid")
    except DiscoveryIntegrationError as exc:
        raise exc

    # Publish a running revision before processing so an interrupted run remains visible.
    manifest, current_path = _persist_transition(manifest, workspace, current_path, "live_discovery", "running")
    envelope_error = _check_observation_envelope(manifest, payload, plan)
    if envelope_error:
        manifest, current_path = _persist_transition(manifest, workspace, current_path, "live_discovery", "failed",
                                                       error_code=envelope_error)
        raise DiscoveryIntegrationError(envelope_error, current_path)

    run_id = manifest["run_id"]
    observations_path = None
    try:
        observations_path = write_private_json_atomic(
            workspace, "discovery", f"observations-{run_id}-{uuid4().hex}.json", payload)
    except StorageError:
        manifest, current_path = _persist_transition(manifest, workspace, current_path, "live_discovery", "failed",
                                                       error_code="observation_storage_failed")
        raise DiscoveryIntegrationError("observation_storage_failed", current_path) from None
    manifest["artifacts"]["discovery_observations"] = _file_reference(observations_path, workspace)
    live_state = payload["execution_status"]
    live_target = "partial" if live_state != "completed" else "completed"
    live_reason = "interrupted" if live_state == "interrupted" else "discovery_incomplete"
    manifest, current_path = _persist_transition(
        manifest, workspace, current_path, "live_discovery", live_target,
        reason=live_reason if live_target == "partial" else None)

    validation_stage = "opportunity_validation_and_persistence"
    manifest, current_path = _persist_transition(manifest, workspace, current_path, validation_stage, "running")
    catalog = deepcopy(selected_document["opportunities"] if selected_document else [])
    audit_entries = []
    accepted_count = 0
    incomplete = live_state != "completed"
    for index, observation in enumerate(payload["observations"]):
        base = {"index": index}
        if isinstance(observation, dict) and isinstance(observation.get("observation_id"), str):
            base["observation_id"] = observation["observation_id"]
        errors = _record_observation_errors(observation)
        outcome = observation.get("outcome") if isinstance(observation, dict) else None
        if errors:
            base.update(status="invalid_observation", reason_codes=errors)
            # Keep the original item for private audit; never echo it to command output.
            base["submitted_observation"] = deepcopy(observation)
            audit_entries.append(base)
            incomplete = True
            continue
        if outcome == "inaccessible":
            base.update(status="source_inaccessible", reason_code=observation["reason_code"],
                        source_url=observation["source_url"])
            audit_entries.append(base)
            incomplete = True
            continue
        if outcome == "rejected":
            base.update(status="explicitly_rejected", reason_code=observation["reason_code"],
                        submitted_opportunity=deepcopy(observation.get("opportunity")))
            audit_entries.append(base)
            incomplete = True
            continue
        base["opportunity_id"] = observation["opportunity"]["id"]
        _append_valid_record(catalog, observation["opportunity"], base)
        accepted_count += 1
        if base["status"] == "possible_duplicate_requires_review":
            incomplete = True
        audit_entries.append(base)

    audit = {
        "audit_version": "1", "run_id": run_id, "created_at": _now(),
        "query_count": len(payload["queries_executed"]),
        "observation_count": len(payload["observations"]),
        "valid_opportunity_count": accepted_count,
        "resulting_catalog_count": len(catalog),
        "execution_status": live_state,
        "observations": audit_entries,
        "freshness": [{"opportunity_id": item["id"], **freshness_state(item)} for item in catalog],
    }
    try:
        audit_path = write_private_json_atomic(workspace, "discovery", f"audit-{run_id}-{uuid4().hex}.json", audit)
        manifest["artifacts"]["discovery_audit"] = _file_reference(audit_path, workspace)
        snapshot_path = None
        if accepted_count:
            snapshot_document = {"schema_version": "1", "opportunities": catalog}
            snapshot_path = save_opportunities(snapshot_document, workspace)
            manifest["artifacts"]["opportunity_snapshot"] = _file_reference(snapshot_path, workspace)
    except (StorageError, OpportunityError):
        manifest, current_path = _persist_transition(manifest, workspace, current_path, validation_stage,
                                                       "failed", error_code="opportunity_persistence_failed")
        raise DiscoveryIntegrationError("opportunity_persistence_failed", current_path) from None

    if not accepted_count:
        # An audit is useful for diagnosis, but without one valid opportunity there is no usable result.
        manifest, current_path = _persist_transition(manifest, workspace, current_path, validation_stage,
                                                       "failed", error_code="no_valid_opportunities")
        manifest, current_path = _persist_transition(manifest, workspace, current_path,
                                                       "deduplication_and_freshness", "skipped",
                                                       reason="no_valid_opportunities")
        raise DiscoveryIntegrationError("no_valid_opportunities", current_path)

    validation_target = "partial" if incomplete else "completed"
    validation_reason = "observation_failures_or_review" if incomplete else None
    manifest["artifacts"]["discovery_audit"] = _file_reference(audit_path, workspace)
    manifest["artifacts"]["opportunity_snapshot"] = _file_reference(snapshot_path, workspace)
    manifest, current_path = _persist_transition(
        manifest, workspace, current_path, validation_stage, validation_target,
        reason=validation_reason)

    manifest, current_path = _persist_transition(manifest, workspace, current_path,
                                                   "deduplication_and_freshness", "running")
    dedup_target = "partial" if incomplete else "completed"
    dedup_reason = "review_or_observation_uncertainty" if incomplete else None
    manifest, current_path = _persist_transition(
        manifest, workspace, current_path, "deduplication_and_freshness", dedup_target,
        reason=dedup_reason)
    return {"manifest": manifest, "manifest_path": current_path,
            "snapshot_path": snapshot_path, "audit_path": audit_path,
            "accepted_count": accepted_count, "observation_count": len(payload["observations"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Integrate Codex-produced opportunity observations; never searches")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.observations.read_text(encoding="utf-8"))
        result = execute_discovery(args.manifest, payload, args.workspace)
        print(json.dumps({"status": result["manifest"]["run_status"],
                          "accepted_count": result["accepted_count"],
                          "observation_count": result["observation_count"],
                          "manifest": str(result["manifest_path"].relative_to(args.workspace.resolve())),
                          "snapshot": str(result["snapshot_path"].relative_to(args.workspace.resolve())) if result["snapshot_path"] else None,
                          "audit": str(result["audit_path"].relative_to(args.workspace.resolve()))}))
        return 0
    except DiscoveryIntegrationError as exc:
        print(json.dumps({"status": "failed", "error": exc.code,
                          "manifest": str(exc.manifest_path.relative_to(args.workspace.resolve())) if exc.manifest_path else None}))
        return 1
    except (OSError, UnicodeError, ValueError, StorageError):
        print(json.dumps({"status": "failed", "error": "discovery_input_or_storage_invalid"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
