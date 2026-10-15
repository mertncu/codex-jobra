"""Prepare a private Jobra pipeline run without searching or semantic matching."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from local_storage import StorageError, write_private_json_atomic
from plan_discovery import DiscoveryError, build_search_plan
from validate_opportunities import validate_opportunities
from validate_profile import validate_document


STAGES = (
    "candidate_profile_validation", "search_preferences_validation",
    "opportunity_snapshot_selection", "discovery_plan_preparation",
    "live_discovery", "opportunity_validation_and_persistence",
    "deduplication_and_freshness", "matching_catalog_preparation",
    "semantic_assessment", "aggregation_and_results",
)
DEFAULT_LIMITS = {
    "max_discovery_queries": 10,
    "max_opportunities_to_discover": 10,
    "max_opportunities_to_assess": 10,
    "max_retries": 1,
}
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "references/run-manifest.schema.json"
class PreparationError(ValueError):
    """A fixed, privacy-safe preparation error."""

    def __init__(self, code: str, stage: str):
        super().__init__(code)
        self.code = code
        self.stage = stage


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _manifest_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_manifest(manifest):
    """Validate manifest shape and explicit stage-state invariants."""
    errors = sorted(Draft202012Validator(
        _manifest_schema(), format_checker=FormatChecker()).iter_errors(manifest),
        key=lambda error: (list(map(str, error.absolute_path)), error.validator or ""))
    if errors:
        return ["manifest_schema_invalid"]
    for stage_name, stage in manifest["stages"].items():
        status = stage["status"]
        if status == "running" and stage["attempts"] < 1:
            return ["running_stage_has_no_attempt"]
        if status == "failed" and not stage["error_codes"]:
            return ["failed_stage_missing_error_code"]
        if status in ("partial", "skipped") and not stage["incomplete_reasons"]:
            return ["incomplete_stage_missing_reason"]
    if manifest["run_status"] != _derive_run_status(manifest["stages"]):
        return ["run_status_inconsistent"]
    return []


def _derive_run_status(stages):
    statuses = [stage["status"] for stage in stages.values()]
    if "running" in statuses:
        return "running"
    if "failed" in statuses:
        return "partial" if "completed" in statuses else "failed"
    if "partial" in statuses:
        return "partial"
    if all(status in ("completed", "skipped") for status in statuses):
        return "completed"
    if stages["discovery_plan_preparation"]["status"] == "completed":
        downstream = ("live_discovery", "opportunity_validation_and_persistence",
                      "deduplication_and_freshness", "matching_catalog_preparation",
                      "semantic_assessment", "aggregation_and_results")
        if all(stages[name]["status"] == "pending" for name in downstream):
            return "prepared"
        if any(stages[name]["status"] != "pending" for name in downstream):
            return "running"
    if any(status == "completed" for status in statuses):
        return "preparing"
    return "preparing"


def transition_stage(manifest, stage_name, target_status, *, error_code=None, reason=None):
    """Return a new manifest revision after one valid explicit stage transition."""
    if validate_manifest(manifest):
        raise PreparationError("manifest_invalid", "manifest")
    if stage_name not in STAGES or target_status not in {"running", "completed", "partial", "failed", "skipped"}:
        raise PreparationError("invalid_stage_transition", "manifest")
    updated = deepcopy(manifest)
    stage = updated["stages"][stage_name]
    current = stage["status"]
    allowed = ((current == "pending" and target_status in ("running", "skipped")) or
               (current == "running" and target_status in ("completed", "partial", "failed", "skipped")) or
               (current in ("partial", "failed") and target_status == "running"))
    if not allowed:
        raise PreparationError("invalid_stage_transition", stage_name)
    if target_status == "running":
        if current in ("partial", "failed") and stage["attempts"] - 1 >= updated["limits"]["max_retries"]:
            raise PreparationError("retry_budget_exceeded", stage_name)
        stage["attempts"] += 1
    if target_status == "failed":
        if not _valid_code(error_code):
            raise PreparationError("failed_stage_requires_error_code", stage_name)
        stage["error_codes"] = sorted(set(stage["error_codes"] + [error_code]))
    elif target_status == "partial" and error_code is not None:
        if not _valid_code(error_code):
            raise PreparationError("invalid_stage_transition", stage_name)
        stage["error_codes"] = sorted(set(stage["error_codes"] + [error_code]))
    elif error_code is not None:
        raise PreparationError("invalid_stage_transition", stage_name)
    if target_status in ("partial", "skipped"):
        if not _valid_code(reason):
            raise PreparationError("incomplete_stage_requires_reason", stage_name)
        stage["incomplete_reasons"] = sorted(set(stage["incomplete_reasons"] + [reason]))
    elif reason is not None:
        raise PreparationError("invalid_stage_transition", stage_name)
    stage["status"] = target_status
    updated["revision"] += 1
    updated["updated_at"] = _now()
    updated["run_status"] = _derive_run_status(updated["stages"])
    if validate_manifest(updated):
        raise PreparationError("manifest_transition_invalid", stage_name)
    return updated


def _valid_code(value):
    return isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{1,63}", value) is not None


ERROR_HINTS = {
    "verified_profile_missing": "save a verified profile under .jobra/profiles or pass --profile",
    "profile_selection_ambiguous": "pass --profile with the intended verified profile path",
    "candidate_profile_unverified": "complete profile review and verification before preparation",
    "candidate_profile_invalid": "repair the selected profile or pass --profile for another valid profile",
    "search_preferences_missing": "save preferences under .jobra/discovery or pass --preferences",
    "preferences_selection_ambiguous": "pass --preferences with the intended preferences path",
    "search_preferences_invalid": "repair the selected preferences document or pass --preferences",
    "opportunity_snapshot_selection_ambiguous": "pass --opportunity-snapshot with the intended snapshot path",
    "saved_opportunity_snapshot_invalid": "repair the selected snapshot or pass --opportunity-snapshot for a valid snapshot",
    "query_budget_exceeded": "narrow preferences or raise --max-discovery-queries within the supported limit",
    "search_scope_too_broad": "reduce the role, location, work-mode, or seniority combinations in preferences",
    "empty_discovery_plan": "add at least one preferred role, location, work arrangement, and seniority preference",
}


def _new_manifest(limits):
    now = _now()
    return {
        "manifest_version": "1", "run_id": "run_" + uuid4().hex,
        "revision": 1, "created_at": now, "updated_at": now,
        "run_status": "preparing", "previous_manifest_reference": None,
        "inputs": {"candidate_profile": None, "search_preferences": None,
                   "selected_opportunity_snapshot": None},
        "limits": dict(limits),
        "stages": {name: {"status": "pending", "attempts": 0,
                          "error_codes": [], "incomplete_reasons": []} for name in STAGES},
        "artifacts": {"discovery_query_plan": None, "opportunity_snapshot": None,
                      "matching_catalog": None, "assessment": None,
                      "result_snapshot": None, "result_report": None},
    }


def _transition_in_place(manifest, stage_name, status, *, error_code=None, reason=None):
    """Preparation-only transition helper; one final revision is published."""
    # Use the same state machine while keeping preparation's multiple local
    # validation steps inside a single immutable manifest revision.
    previous_revision = manifest["revision"]
    updated = transition_stage(manifest, stage_name, status,
                               error_code=error_code, reason=reason)
    updated["revision"] = previous_revision
    manifest.clear()
    manifest.update(updated)


def _ensure_workspace_category(workspace, category):
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise PreparationError("workspace_invalid", "candidate_profile_validation")
    expected = (root / ".jobra" / category)
    if (root / ".jobra").is_symlink() or expected.is_symlink():
        raise PreparationError("input_storage_unsafe", "candidate_profile_validation")
    return root, expected


def _checked_input_path(path, workspace, category, stage):
    root, expected_dir = _ensure_workspace_category(workspace, category)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_symlink():
        raise PreparationError("input_file_unsafe", stage)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(expected_dir.resolve())
    except (OSError, ValueError):
        raise PreparationError("input_file_missing_or_outside_private_directory", stage) from None
    if not resolved.is_file() or resolved.suffix.lower() != ".json":
        raise PreparationError("input_file_invalid", stage)
    return resolved


def _read_json(path, stage, invalid_code):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise PreparationError(invalid_code, stage) from None


def _reference(path, workspace):
    root = Path(workspace).resolve()
    relative = path.resolve().relative_to(root).as_posix()
    raw = path.read_bytes()
    return {"path": relative, "sha256": hashlib.sha256(raw).hexdigest()}


def _resolve_profile(workspace, explicit):
    stage = "candidate_profile_validation"
    if explicit is not None:
        paths = [_checked_input_path(explicit, workspace, "profiles", stage)]
    else:
        _, directory = _ensure_workspace_category(workspace, "profiles")
        paths = sorted(directory.glob("verified-*.json")) if directory.exists() else []
        if not paths:
            raise PreparationError("verified_profile_missing", stage)
        if len(paths) > 1:
            raise PreparationError("profile_selection_ambiguous", stage)
        paths = [_checked_input_path(paths[0], workspace, "profiles", stage)]
    profile = _read_json(paths[0], stage, "candidate_profile_invalid")
    errors = validate_document(profile, "candidate_profile")
    if errors:
        raise PreparationError("candidate_profile_invalid", stage)
    if profile.get("verification_status") != "verified":
        raise PreparationError("candidate_profile_unverified", stage)
    return profile, paths[0]


def _resolve_preferences(workspace, explicit):
    stage = "search_preferences_validation"
    if explicit is not None:
        paths = [_checked_input_path(explicit, workspace, "discovery", stage)]
    else:
        _, directory = _ensure_workspace_category(workspace, "discovery")
        paths = sorted(directory.glob("preferences-*.json")) if directory.exists() else []
        if not paths:
            raise PreparationError("search_preferences_missing", stage)
        if len(paths) > 1:
            raise PreparationError("preferences_selection_ambiguous", stage)
        paths = [_checked_input_path(paths[0], workspace, "discovery", stage)]
    preferences = _read_json(paths[0], stage, "search_preferences_invalid")
    if validate_document(preferences, "search_preferences"):
        raise PreparationError("search_preferences_invalid", stage)
    return preferences, paths[0]


def _resolve_opportunities(workspace, explicit):
    stage = "opportunity_snapshot_selection"
    if explicit is not None:
        paths = [_checked_input_path(explicit, workspace, "opportunities", stage)]
    else:
        _, directory = _ensure_workspace_category(workspace, "opportunities")
        paths = sorted(directory.glob("snapshot-*.json")) if directory.exists() else []
        if len(paths) > 1:
            raise PreparationError("opportunity_snapshot_selection_ambiguous", stage)
        if not paths:
            return None, None
        paths = [_checked_input_path(paths[0], workspace, "opportunities", stage)]
    document = _read_json(paths[0], stage, "saved_opportunity_snapshot_invalid")
    if validate_opportunities(document):
        raise PreparationError("saved_opportunity_snapshot_invalid", stage)
    return document, paths[0]


def _skip_pending_stages(manifest, reason):
    for name in STAGES:
        if manifest["stages"][name]["status"] == "pending":
            _transition_in_place(manifest, name, "skipped", reason=reason)


def prepare_run(workspace, *, profile_path=None, preferences_path=None,
                opportunity_snapshot_path=None, limits=None):
    """Validate local inputs and persist one prepared/failed run manifest."""
    workspace = Path(workspace).resolve()
    limits = dict(DEFAULT_LIMITS if limits is None else limits)
    manifest = _new_manifest(limits)
    try:
        # Validate limits before creating a filesystem artifact.
        if (set(limits) != set(DEFAULT_LIMITS) or
                any(type(value) is not int for value in limits.values()) or
                not 1 <= limits["max_discovery_queries"] <= 100 or
                not 1 <= limits["max_opportunities_to_discover"] <= 100 or
                not 1 <= limits["max_opportunities_to_assess"] <= 100 or
                not 0 <= limits["max_retries"] <= 5):
            raise PreparationError("execution_limits_invalid", "candidate_profile_validation")
        initial_path = save_run_manifest(manifest, workspace)
    except (StorageError, PreparationError) as exc:
        if isinstance(exc, PreparationError):
            raise
        raise PreparationError("manifest_storage_failed", "candidate_profile_validation") from None

    # Profile, preferences, and optional prior snapshot are independently
    # resolved so one failure does not hide actionable errors in another input.
    resolved = {}
    selectors = (
        ("candidate_profile_validation", "candidate_profile", _resolve_profile,
         profile_path),
        ("search_preferences_validation", "search_preferences", _resolve_preferences,
         preferences_path),
        ("opportunity_snapshot_selection", "selected_opportunity_snapshot",
         _resolve_opportunities, opportunity_snapshot_path),
    )
    for stage, input_name, resolver, explicit in selectors:
        _transition_in_place(manifest, stage, "running")
        try:
            value, path = resolver(workspace, explicit)
            resolved[input_name] = value
            if path is not None:
                manifest["inputs"][input_name] = _reference(path, workspace)
            _transition_in_place(manifest, stage, "completed")
        except PreparationError as exc:
            _transition_in_place(manifest, stage, "failed", error_code=exc.code)
            resolved[input_name] = None

    plan_stage = "discovery_plan_preparation"
    if resolved.get("candidate_profile") is None or resolved.get("search_preferences") is None:
        _transition_in_place(manifest, plan_stage, "skipped", reason="required_input_failed")
        _skip_pending_stages(manifest, "upstream_stage_failed")
    else:
        _transition_in_place(manifest, plan_stage, "running")
        try:
            plan = build_search_plan(resolved["candidate_profile"], resolved["search_preferences"])
            queries = plan.get("queries")
            if not isinstance(queries, list) or not queries:
                raise PreparationError("empty_discovery_plan", plan_stage)
            if len(queries) > limits["max_discovery_queries"]:
                raise PreparationError("query_budget_exceeded", plan_stage)
            plan["target_maximum"] = limits["max_opportunities_to_discover"]
            plan_path = write_private_json_atomic(
                workspace, "discovery", f"plan-{manifest['run_id']}.json", plan)
            manifest["artifacts"]["discovery_query_plan"] = _reference(plan_path, workspace)
            _transition_in_place(manifest, plan_stage, "completed")
        except DiscoveryError as exc:
            code = str(exc) if _valid_code(str(exc)) else "discovery_plan_invalid"
            _transition_in_place(manifest, plan_stage, "failed", error_code=code)
            _skip_pending_stages(manifest, "upstream_stage_failed")
        except PreparationError as exc:
            if exc.code == "query_budget_exceeded":
                _transition_in_place(manifest, plan_stage, "partial", error_code=exc.code,
                                     reason="query_budget_exceeded")
            else:
                _transition_in_place(manifest, plan_stage, "failed", error_code=exc.code)
            _skip_pending_stages(manifest, "upstream_stage_failed")
        except StorageError:
            _transition_in_place(manifest, plan_stage, "failed", error_code="query_plan_storage_failed")
            _skip_pending_stages(manifest, "upstream_stage_failed")

    manifest["revision"] = 2
    manifest["updated_at"] = _now()
    manifest["previous_manifest_reference"] = _reference(initial_path, workspace)
    manifest["run_status"] = _derive_run_status(manifest["stages"])
    errors = validate_manifest(manifest)
    if errors:
        raise PreparationError("prepared_manifest_invalid", "manifest")
    try:
        final_path = save_run_manifest(manifest, workspace)
    except StorageError:
        raise PreparationError("manifest_storage_failed", "manifest") from None
    return manifest, final_path


def save_run_manifest(manifest, workspace, *, previous_path=None):
    """Atomically save a private, create-only manifest revision."""
    document = deepcopy(manifest)
    if previous_path is not None:
        document["previous_manifest_reference"] = _reference(Path(previous_path), workspace)
    errors = validate_manifest(document)
    if errors:
        raise PreparationError(errors[0], "manifest")
    filename = f"{document['run_id']}-r{document['revision']:04d}.json"
    return write_private_json_atomic(Path(workspace), "discovery", filename, document)


def read_manifest(path, workspace):
    """Read a manifest from private Jobra storage and validate its contract."""
    safe_path = _checked_input_path(path, workspace, "discovery", "manifest")
    if not safe_path.name.startswith("run_") or "-r" not in safe_path.stem:
        raise PreparationError("manifest_path_invalid", "manifest")
    manifest = _read_json(safe_path, "manifest", "manifest_invalid")
    if validate_manifest(manifest):
        raise PreparationError("manifest_invalid", "manifest")
    return manifest, safe_path


def _parser():
    parser = argparse.ArgumentParser(description="Prepare or advance a private Jobra pipeline run")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="validate inputs and prepare an offline discovery plan")
    prepare.add_argument("--workspace", type=Path, default=Path.cwd())
    prepare.add_argument("--profile", type=Path)
    prepare.add_argument("--preferences", type=Path)
    prepare.add_argument("--opportunity-snapshot", type=Path)
    prepare.add_argument("--max-discovery-queries", type=int, default=DEFAULT_LIMITS["max_discovery_queries"])
    prepare.add_argument("--max-opportunities-to-discover", type=int, default=DEFAULT_LIMITS["max_opportunities_to_discover"])
    prepare.add_argument("--max-opportunities-to-assess", type=int, default=DEFAULT_LIMITS["max_opportunities_to_assess"])
    prepare.add_argument("--max-retries", type=int, default=DEFAULT_LIMITS["max_retries"])
    advance = subparsers.add_parser("transition", help="persist one explicit stage-state transition as a new revision")
    advance.add_argument("--workspace", type=Path, default=Path.cwd())
    advance.add_argument("--manifest", type=Path, required=True)
    advance.add_argument("--stage", choices=STAGES, required=True)
    advance.add_argument("--status", choices=("running", "completed", "partial", "failed", "skipped"), required=True)
    advance.add_argument("--error-code")
    advance.add_argument("--reason")
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()
    try:
        if args.command == "prepare":
            limits = {
                "max_discovery_queries": args.max_discovery_queries,
                "max_opportunities_to_discover": args.max_opportunities_to_discover,
                "max_opportunities_to_assess": args.max_opportunities_to_assess,
                "max_retries": args.max_retries,
            }
            manifest, path = prepare_run(workspace, profile_path=args.profile,
                preferences_path=args.preferences,
                opportunity_snapshot_path=args.opportunity_snapshot, limits=limits)
            stage_errors = {name: stage["error_codes"] for name, stage in manifest["stages"].items()
                            if stage["error_codes"]}
            stage_reasons = {name: stage["incomplete_reasons"] for name, stage in manifest["stages"].items()
                             if stage["incomplete_reasons"]}
            codes = sorted({code for codes in stage_errors.values() for code in codes})
            print(json.dumps({"status": manifest["run_status"], "run_id": manifest["run_id"],
                              "manifest": str(path.relative_to(workspace)),
                              "query_plan": (manifest["artifacts"]["discovery_query_plan"] or {}).get("path"),
                              "query_count": len(json.loads(Path(workspace, manifest["artifacts"]["discovery_query_plan"]["path"]).read_text())["queries"])
                                  if manifest["artifacts"]["discovery_query_plan"] else 0,
                              "stage_errors": stage_errors, "incomplete_reasons": stage_reasons,
                              "hints": sorted({ERROR_HINTS[code] for code in codes if code in ERROR_HINTS})}))
            return 0 if manifest["run_status"] == "prepared" else 1
        manifest, old_path = read_manifest(args.manifest, workspace)
        updated = transition_stage(manifest, args.stage, args.status,
                                   error_code=args.error_code, reason=args.reason)
        new_path = save_run_manifest(updated, workspace, previous_path=old_path)
        print(json.dumps({"status": updated["run_status"], "manifest": str(new_path.relative_to(workspace))}))
        return 0
    except PreparationError as exc:
        print(json.dumps({"status": "failed", "error": exc.code, "stage": exc.stage}))
        return 1
    except (OSError, ValueError, StorageError):
        print(json.dumps({"status": "failed", "error": "preparation_input_or_storage_invalid"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
