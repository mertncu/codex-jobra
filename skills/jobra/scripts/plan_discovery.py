"""Prepare an offline search plan; never send profile data or run searches."""

import argparse
import json
from itertools import product
from pathlib import Path
from uuid import uuid4

from local_storage import StorageError, write_private_json_atomic
from validate_profile import SECTIONS, validate_document, records_for_downstream


class DiscoveryError(Exception):
    """Fixed privacy-safe failure code."""


def _phrase(value):
    if not value.strip() or len(value) > 200 or any(ord(char) < 32 for char in value):
        raise DiscoveryError("invalid_search_term")
    return '"' + value.replace('"', ' ').strip() + '"'


def build_search_plan(profile, preferences):
    if validate_document(profile, "candidate_profile") or profile["verification_status"] != "verified":
        raise DiscoveryError("verified_profile_required")
    if validate_document(preferences, "search_preferences"):
        raise DiscoveryError("invalid_search_preferences")
    essential = ("preferred_roles", "locations", "work_arrangements", "seniority_preferences")
    if any(not preferences[field] for field in essential):
        raise DiscoveryError("essential_preferences_missing")
    excluded = {value.strip().casefold() for value in preferences["excluded_roles"]}
    roles = [role for role in preferences["preferred_roles"] if role.strip().casefold() not in excluded]
    if not roles:
        raise DiscoveryError("conflicting_role_preferences")
    dimensions = [roles] + [preferences[field] for field in essential[1:]]
    count = 1
    for values in dimensions:
        count *= len(values)
    if count > 100:
        raise DiscoveryError("search_scope_too_broad")
    negative = " ".join("-" + _phrase(value) for value in preferences["excluded_roles"])
    queries = []
    for terms in product(*dimensions):
        query = " ".join(_phrase(term) for term in terms) + " jobs careers"
        if negative:
            query += " " + negative
        if query not in queries:
            queries.append(query)
    evidence = {item["id"]: item for item in profile["evidence"]}
    facts = {}
    for section in SECTIONS:
        if section == "suggested_roles":
            continue
        facts[section] = [record["id"] for record in records_for_downstream(profile, section)
                          if record["origin"] == "user" or all(
                              evidence[ref]["extraction"] == "explicit" for ref in record["evidence_ids"])]
    return {"schema_version": "1", "status": "awaiting_query_approval",
            "target_maximum": 10, "preferences": json.loads(json.dumps(preferences)),
            "verified_fact_ids_local_only": facts, "queries": queries,
            "query_source": "user_preferences_only"}


def main():
    parser = argparse.ArgumentParser(description="Prepare a private Jobra discovery plan")
    parser.add_argument("profile", type=Path)
    parser.add_argument("preferences", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        preferences = json.loads(args.preferences.read_text(encoding="utf-8"))
        plan = build_search_plan(profile, preferences)
        output = write_private_json_atomic(args.workspace, "discovery", f"plan-{uuid4().hex}.json", plan)
    except (OSError, UnicodeError, ValueError, DiscoveryError, StorageError):
        parser.exit(1, "discovery plan failed: invalid_input_or_storage\n")
    print(json.dumps({"status": plan["status"], "output": str(output.relative_to(args.workspace)),
                      "query_count": len(plan["queries"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
