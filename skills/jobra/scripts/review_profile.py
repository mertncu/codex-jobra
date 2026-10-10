"""Apply explicit human review decisions to immutable local profile snapshots.

Operation JSON is private input. Errors and CLI output never contain profile values.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from uuid import uuid4

from local_storage import StorageError, write_private_json_atomic
from validate_profile import ACCEPTED, SECTIONS, validate_document


class ReviewError(Exception):
    """A fixed, privacy-safe review failure code."""


SECTION_FIELDS = {
    "education": {"institution", "credential", "field", "period"},
    "experience": {"organization", "role", "kind", "period", "summary"},
    "projects": {"name", "summary", "url"},
    "technical_skills": {"name", "level"},
    "suggested_roles": {"title"},
}
REQUIRED_SECTION_FIELDS = {
    "education": {"institution"},
    "experience": {"organization", "role", "kind"},
    "projects": {"name"},
    "technical_skills": {"name", "level"},
    "suggested_roles": {"title"},
}


def _record(profile: dict, section: str, identifier: str) -> dict:
    if section not in SECTIONS:
        raise ReviewError("invalid_section")
    for record in profile[section]:
        if record["id"] == identifier:
            return record
    raise ReviewError("record_not_found")


def _evidence(profile: dict, identifier: str) -> dict:
    for item in profile["evidence"]:
        if item["id"] == identifier:
            return item
    raise ReviewError("evidence_not_found")


def _require_accepted_evidence(profile: dict, record: dict) -> None:
    if any(_evidence(profile, ref)["review_status"] not in ACCEPTED
           for ref in record["evidence_ids"]):
        raise ReviewError("supporting_evidence_unreviewed")


def _reset_section(profile: dict, section: str) -> None:
    profile["section_reviews"][section] = "pending"


def _require_fields(operation: dict, required: set[str], allowed: set[str]) -> None:
    if not required <= operation.keys() or operation.keys() - allowed:
        raise ReviewError("invalid_operation")


def apply_review_operation(profile: object, operation: object) -> dict:
    """Validate input, apply one explicit decision to a copy, then validate it."""
    if validate_document(profile, "candidate_profile"):
        raise ReviewError("invalid_profile")
    if profile["verification_status"] != "draft":
        raise ReviewError("verified_profile_locked")
    if not isinstance(operation, dict) or not isinstance(operation.get("action"), str):
        raise ReviewError("invalid_operation")
    result = copy.deepcopy(profile)
    action = operation["action"]
    if action == "review_evidence":
        _require_fields(operation, {"action", "evidence_id", "decision"},
                        {"action", "evidence_id", "decision", "changes", "remove_fields", "correction_note"})
        item = _evidence(result, operation["evidence_id"])
        if item["review_status"] != "pending" or operation["decision"] not in ("confirmed", "corrected", "rejected"):
            raise ReviewError("invalid_transition")
        changes = operation.get("changes", {})
        removed = operation.get("remove_fields", [])
        if (not isinstance(changes, dict) or changes.keys() - {"location", "excerpt", "extraction"}
                or not isinstance(removed, list) or any(not isinstance(field, str) or field not in ("location", "excerpt") for field in removed)
                or len(set(removed)) != len(removed) or set(removed) & changes.keys()):
            raise ReviewError("invalid_operation")
        if operation["decision"] == "corrected":
            if not isinstance(operation.get("correction_note"), str) or not operation["correction_note"].strip():
                raise ReviewError("correction_note_required")
            item.update(changes)
            for field in removed:
                item.pop(field, None)
            item["correction_note"] = operation["correction_note"]
        elif changes or removed or "correction_note" in operation:
            raise ReviewError("invalid_operation")
        item["review_status"] = operation["decision"]
        for section in SECTIONS:
            if any(item["id"] in record["evidence_ids"] for record in result[section]):
                _reset_section(result, section)
    elif action in ("confirm_record", "correct_record", "reject_record"):
        required = {"action", "section", "record_id"}
        allowed = required | ({"changes", "remove_fields", "correction_note"} if action == "correct_record" else set())
        _require_fields(operation, required | ({"correction_note"} if action == "correct_record" else set()), allowed)
        section = operation["section"]
        record = _record(result, section, operation["record_id"])
        if record["review_status"] == "rejected":
            raise ReviewError("invalid_transition")
        if action == "confirm_record":
            if record["review_status"] != "pending":
                raise ReviewError("invalid_transition")
            _require_accepted_evidence(result, record)
            record["review_status"] = "confirmed"
        elif action == "correct_record":
            changes = operation.get("changes", {})
            removed = operation.get("remove_fields", [])
            if (not isinstance(changes, dict) or changes.keys() - SECTION_FIELDS[section]
                    or not isinstance(removed, list)
                    or any(not isinstance(field, str) or field not in SECTION_FIELDS[section] - REQUIRED_SECTION_FIELDS[section] for field in removed)
                    or len(set(removed)) != len(removed) or set(removed) & changes.keys()
                    or not (changes or removed)):
                raise ReviewError("invalid_operation")
            if not isinstance(operation["correction_note"], str) or not operation["correction_note"].strip():
                raise ReviewError("correction_note_required")
            _require_accepted_evidence(result, record)
            record.update(changes)
            for field in removed:
                record.pop(field, None)
            record["review_status"] = "corrected"
            record["correction_note"] = operation["correction_note"]
        else:
            record["review_status"] = "rejected"
        _reset_section(result, section)
    elif action == "add_record":
        _require_fields(operation, {"action", "section", "record"}, {"action", "section", "record"})
        section = operation["section"]
        if section not in SECTIONS or not isinstance(operation["record"], dict):
            raise ReviewError("invalid_operation")
        record = copy.deepcopy(operation["record"])
        if any(key in record for key in ("origin", "review_status", "evidence_ids", "correction_note")):
            raise ReviewError("invalid_operation")
        record.update({"origin": "user", "review_status": "pending", "evidence_ids": []})
        result[section].append(record)
        _reset_section(result, section)
    elif action == "confirm_section":
        _require_fields(operation, {"action", "section"}, {"action", "section"})
        section = operation["section"]
        if section not in SECTIONS:
            raise ReviewError("invalid_section")
        if any(record["review_status"] == "pending" for record in result[section]):
            raise ReviewError("pending_records")
        for record in result[section]:
            if any(_evidence(result, ref)["review_status"] == "pending" for ref in record["evidence_ids"]):
                raise ReviewError("pending_evidence")
        result["section_reviews"][section] = "confirmed"
    elif action == "finalize":
        _require_fields(operation, {"action", "approved"}, {"action", "approved"})
        if operation["approved"] is not True:
            raise ReviewError("final_approval_required")
        if any(result["section_reviews"][section] != "confirmed" for section in SECTIONS):
            raise ReviewError("pending_sections")
        if any(item["review_status"] == "pending" for item in result["evidence"]):
            raise ReviewError("pending_evidence")
        if any(record["review_status"] == "pending" for section in SECTIONS for record in result[section]):
            raise ReviewError("pending_records")
        result["verification_status"] = "verified"
    else:
        raise ReviewError("unknown_action")
    if validate_document(result, "candidate_profile"):
        raise ReviewError("invalid_review_result")
    return result


def save_review_operation(profile_path: Path, operation_path: Path, workspace: Path) -> Path:
    """Read private operation and profile, then publish a validated new snapshot."""
    root = Path(workspace).resolve()
    private = root / ".jobra"
    profiles = private / "profiles"
    try:
        source = Path(profile_path).resolve(strict=True)
        request = Path(operation_path).resolve(strict=True)
        if source.parent != profiles or not request.is_relative_to(private):
            raise ReviewError("unsafe_input_path")
        profile = json.loads(source.read_text(encoding="utf-8"))
        operation = json.loads(request.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ReviewError("unreadable_json") from None
    result = apply_review_operation(profile, operation)
    prefix = "verified" if result["verification_status"] == "verified" else "review"
    try:
        return write_private_json_atomic(root, "profiles", f"{prefix}-{uuid4().hex}.json", result)
    except StorageError:
        raise ReviewError("unwritable_profile") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply one explicit Jobra profile review operation")
    parser.add_argument("profile_json", type=Path)
    parser.add_argument("operation_json", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        output = save_review_operation(args.profile_json, args.operation_json, args.workspace)
    except ReviewError as error:
        parser.exit(1, f"profile review failed: {error}\n")
    print(json.dumps({"status": "verified" if output.name.startswith("verified-") else "draft",
                      "output": str(output.relative_to(args.workspace.resolve()))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
