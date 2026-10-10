"""Validate and create a private, unverified candidate profile draft."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from local_storage import StorageError, write_private_json
from validate_profile import SECTIONS, validate_document


class DraftError(Exception):
    """A fixed, privacy-safe draft failure code."""


def validate_draft_against_ingestion(profile: object, ingested: object) -> list[str]:
    """Check pending-only draft state and evidence against extracted source segments."""
    issues = validate_document(profile, "candidate_profile")
    if issues:
        return issues
    if not isinstance(ingested, dict) or not isinstance(ingested.get("source_document"), dict):
        return ["ingestion: invalid structure"]
    segments = ingested.get("segments")
    if not isinstance(segments, list) or not segments:
        return ["ingestion: missing segments"]
    source_id = ingested["source_document"].get("id")
    if not isinstance(source_id, str) or profile["source_documents"] != [{"id": source_id, "kind": "resume"}]:
        issues.append("source_documents: does not match ingestion")
    if profile["verification_status"] != "draft":
        issues.append("verification_status: draft required")
    for section in SECTIONS:
        if profile["section_reviews"][section] != "pending":
            issues.append(f"section_reviews.{section}: pending required")
        for index, record in enumerate(profile[section]):
            if record["review_status"] != "pending":
                issues.append(f"{section}[{index}].review_status: pending required")
    by_location = {}
    for segment in segments:
        if isinstance(segment, dict) and isinstance(segment.get("location"), str) and isinstance(segment.get("text"), str):
            by_location.setdefault(segment["location"], []).append(segment["text"])
    for index, item in enumerate(profile["evidence"]):
        if item["review_status"] != "pending":
            issues.append(f"evidence[{index}].review_status: pending required")
        if item["source_document_id"] != source_id:
            issues.append(f"evidence[{index}].source_document_id: does not match ingestion")
        location = item.get("location")
        excerpt = item.get("excerpt")
        if not location or location not in by_location:
            issues.append(f"evidence[{index}].location: unknown source segment")
        elif not excerpt or not any(excerpt in text for text in by_location[location]):
            issues.append(f"evidence[{index}].excerpt: not found at source location")
    return issues


def save_profile_draft(profile: object, ingested: object, workspace: Path) -> Path:
    """Write only a new draft file; never replace any saved profile."""
    if validate_draft_against_ingestion(profile, ingested):
        raise DraftError("invalid_profile_draft")
    filename = f"draft-{uuid4().hex}.json"
    try:
        return write_private_json(workspace, "profiles", filename, profile)
    except StorageError:
        raise DraftError("unwritable_draft") from None


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DraftError("unreadable_json") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and save a local Jobra profile draft")
    parser.add_argument("profile_json", type=Path)
    parser.add_argument("ingestion_json", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        profile = _read_json(args.profile_json)
        ingested = _read_json(args.ingestion_json)
        output = save_profile_draft(profile, ingested, args.workspace)
    except DraftError as error:
        parser.exit(1, f"draft save failed: {error}\n")
    print(json.dumps({"status": "draft", "output": str(output.relative_to(args.workspace))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
