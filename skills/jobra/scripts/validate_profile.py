"""Deterministic validation for Jobra v1 JSON documents.

Return privacy-safe diagnostics; never log or transmit candidate data.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import json
import re
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker


SECTIONS = ("education", "experience", "projects", "technical_skills", "suggested_roles")
ACCEPTED = frozenset(("confirmed", "corrected"))
SCHEMAS = {
    "candidate_profile": "candidate-profile.schema.json",
    "search_preferences": "search-preferences.schema.json",
}
FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks("uri")
def _valid_uri(value: object) -> bool:
    """Check absolute URI syntax without optional jsonschema format extras."""
    if not isinstance(value, str):
        return True  # The schema's type keyword reports non-string values.
    if not value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return False
    try:
        parts = urlsplit(value)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*", parts.scheme):
            return False
        if parts.scheme.lower() in ("http", "https"):
            return bool(parts.hostname) and (parts.port is None or 0 < parts.port <= 65535)
        return bool(parts.netloc or parts.path)
    except ValueError:
        return False


def _schema_errors(document: object, kind: str) -> list[str]:
    schema_path = Path(__file__).resolve().parent.parent / "references" / SCHEMAS[kind]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
    errors = []
    for error in validator.iter_errors(document):
        path = "$"
        for part in error.absolute_path:
            path += f"[{part}]" if isinstance(part, int) else f".{part}"
        errors.append(f"{path}: {error.validator} validation failed")
    return sorted(errors)


def validate_document(document: object, kind: str) -> list[str]:
    """Validate a candidate_profile or search_preferences document.

JSON Schema runs first. Cross-record checks run only for a schema-valid profile.
Results contain paths and rule names, never input values or raw excerpts.
"""
    if kind not in SCHEMAS:
        raise ValueError("Unknown Jobra document kind")
    errors = _schema_errors(document, kind)
    if errors or kind == "search_preferences":
        return errors
    return validate_profile_invariants(document)


def records_for_downstream(profile: Mapping, section: str) -> list[dict]:
    """Return only reviewed, accepted records from a verified profile.

Research and matching must use this view; rejected records remain in storage.
"""
    if section not in SECTIONS:
        raise ValueError("Unknown Jobra profile section")
    if validate_document(profile, "candidate_profile") or profile["verification_status"] != "verified":
        raise ValueError("Candidate profile is not verified and valid")
    return [record for record in profile[section] if record["review_status"] in ACCEPTED]


def validate_profile_invariants(profile: Mapping) -> list[str]:
    """Return path-oriented errors; never include profile field values."""
    errors: list[str] = []
    documents = profile["source_documents"]
    evidence = profile["evidence"]
    records = [(section, index, record) for section in SECTIONS
               for index, record in enumerate(profile[section])]

    def unique_ids(items: list, path: str) -> set[str]:
        seen: set[str] = set()
        for index, item in enumerate(items):
            identifier = item["id"]
            if identifier in seen:
                errors.append(f"{path}[{index}].id: duplicate identifier")
            seen.add(identifier)
        return seen

    document_ids = unique_ids(documents, "source_documents")
    evidence_ids = unique_ids(evidence, "evidence")
    unique_ids([record for _, _, record in records], "records")
    evidence_by_id = {item["id"]: item for item in evidence}

    for index, item in enumerate(evidence):
        if item["source_document_id"] not in document_ids:
            errors.append(f"evidence[{index}].source_document_id: unknown document")
        if item["review_status"] == "corrected" and "correction_note" not in item:
            errors.append(f"evidence[{index}].correction_note: required for correction")

    for section, index, record in records:
        path = f"{section}[{index}]"
        references = record["evidence_ids"]
        if record["origin"] == "extracted" and not references:
            errors.append(f"{path}.evidence_ids: extracted record requires evidence")
        if record["origin"] == "user" and references:
            errors.append(f"{path}.evidence_ids: user-origin record cannot cite extracted evidence")
        if record["review_status"] == "corrected" and "correction_note" not in record:
            errors.append(f"{path}.correction_note: required for correction")
        for ref in references:
            if ref not in evidence_ids:
                errors.append(f"{path}.evidence_ids: unknown evidence")
            elif record["review_status"] in ACCEPTED and evidence_by_id[ref]["review_status"] == "rejected":
                errors.append(f"{path}.evidence_ids: accepted record cites rejected evidence")
        if section == "technical_skills" and record["origin"] == "extracted" and record["level"] != "unknown":
            if record["review_status"] not in ACCEPTED:
                errors.append(f"{path}.level: extracted proficiency requires user review")

    if profile["verification_status"] == "verified":
        for section in SECTIONS:
            if profile["section_reviews"][section] != "confirmed":
                errors.append(f"section_reviews.{section}: required before profile verification")
        for index, item in enumerate(evidence):
            if item["review_status"] == "pending":
                errors.append(f"evidence[{index}].review_status: pending evidence")
        for section, index, record in records:
            if record["review_status"] == "pending":
                errors.append(f"{section}[{index}].review_status: pending record")
            if record["review_status"] in ACCEPTED:
                for ref in record["evidence_ids"]:
                    if ref in evidence_by_id and evidence_by_id[ref]["review_status"] not in ACCEPTED:
                        errors.append(f"{section}[{index}].evidence_ids: supporting evidence not accepted")
    return errors
