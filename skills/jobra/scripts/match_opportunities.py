"""Validate Codex's evidence-linked interpretation and aggregate a local match report."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
from local_storage import StorageError, write_private_json_atomic
from validate_opportunities import validate_opportunities
from validate_profile import ACCEPTED, SECTIONS, records_for_downstream, validate_document


class MatchError(ValueError):
    """Fixed privacy-safe matching validation error."""


def _norm(value):
    value = unicodedata.normalize("NFKD", (value or "").casefold().replace("ı", "i"))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _has_phrase(haystack, needle):
    h, n = _norm(haystack), _norm(needle)
    return bool(n) and (h == n or f" {n} " in f" {h} ")


def validate_matching_inputs(profile, preferences, opportunity_document, interpretation):
    """Validate all input contracts and interpretation references without logging data."""
    if validate_document(profile, "candidate_profile") or profile.get("verification_status") != "verified":
        raise MatchError("candidate_profile_must_be_verified_and_valid")
    if validate_document(preferences, "search_preferences"):
        raise MatchError("search_preferences_invalid")
    if validate_opportunities(opportunity_document):
        raise MatchError("opportunities_invalid")
    schema_path = Path(__file__).resolve().parent.parent / "references/matching-assessment.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(interpretation)):
        raise MatchError("interpretation_schema_invalid")

    opportunities = {item["id"]: item for item in opportunity_document["opportunities"]}
    assessments = interpretation["assessments"]
    if not assessments or len({item["opportunity_id"] for item in assessments}) != len(assessments):
        raise MatchError("interpretation_opportunity_ids_invalid")
    candidate_records = {}
    for section in SECTIONS:
        # This call guarantees only accepted records in a verified profile are eligible.
        for record in records_for_downstream(profile, section):
            candidate_records[record["id"]] = (section, record)
    candidate_evidence = {item["id"]: item for item in profile["evidence"] if item["review_status"] in ACCEPTED}
    for assessment in assessments:
        if assessment["opportunity_id"] not in opportunities:
            raise MatchError("unknown_opportunity_reference")
        opportunity = opportunities[assessment["opportunity_id"]]
        job_evidence = {item["id"]: item for item in opportunity["evidence"]}
        if len({req["id"] for req in assessment["requirements"]}) != len(assessment["requirements"]):
            raise MatchError("duplicate_requirement_id")
        preference_terms = {_norm(x) for x in preferences["preferred_roles"]}
        if any(_norm(term) not in preference_terms for term in assessment["career_alignment"]["preference_terms"]):
            raise MatchError("unknown_preference_reference")
        if assessment["career_alignment"]["outcome"] in ("aligned", "partial") and (
                not assessment["career_alignment"]["preference_terms"] or not assessment["career_alignment"]["job_evidence_ids"]):
            raise MatchError("career_alignment_missing_evidence_or_preference")
        for item in [*assessment["requirements"], assessment["experience_alignment"]]:
            if not set(item["job_evidence_ids"]) <= set(job_evidence):
                raise MatchError("unknown_job_evidence_reference")
            if not set(item["candidate_record_ids"]) <= set(candidate_records):
                raise MatchError("unknown_or_unaccepted_candidate_record")
            if not set(item["candidate_evidence_ids"]) <= set(candidate_evidence):
                raise MatchError("unknown_or_unaccepted_candidate_evidence")
            linked = {ref for record_id in item["candidate_record_ids"]
                      for ref in candidate_records[record_id][1]["evidence_ids"]}
            if item["candidate_record_ids"] and not set(item["candidate_evidence_ids"]) <= linked:
                raise MatchError("candidate_evidence_not_linked_to_record")
        if not set(assessment["career_alignment"]["job_evidence_ids"]) <= set(job_evidence):
            raise MatchError("unknown_job_evidence_reference")
        for requirement in assessment["requirements"]:
            outcome = requirement["outcome"]
            if not requirement["job_evidence_ids"]:
                raise MatchError("requirement_missing_job_evidence")
            if outcome == "matched" and (not requirement["candidate_record_ids"] or not requirement["candidate_evidence_ids"]):
                raise MatchError("matched_requirement_missing_candidate_evidence")
            if outcome == "matched" and any(candidate_evidence[ref]["extraction"] != "explicit"
                                             for ref in requirement["candidate_evidence_ids"]):
                raise MatchError("inferred_support_must_be_labeled_uncertain")
            if outcome == "inferred_support" and (not requirement["candidate_record_ids"] or not requirement["candidate_evidence_ids"]):
                raise MatchError("inferred_support_missing_candidate_evidence")
            if outcome == "not_evidenced" and (requirement["candidate_record_ids"] or requirement["candidate_evidence_ids"]):
                raise MatchError("not_evidenced_requirement_has_candidate_reference")
            if outcome == "contradicted":
                if not requirement["candidate_evidence_ids"] or any(
                        candidate_evidence[ref]["extraction"] != "explicit" for ref in requirement["candidate_evidence_ids"]):
                    raise MatchError("contradiction_requires_explicit_candidate_evidence")
    return opportunities


def _location_and_mode(opportunity, preferences):
    claims = opportunity["claims"]
    arrangement = claims["work_arrangement"]["value"]
    location = claims["location"]["value"]
    if arrangement is None:
        mode = "unknown"
    elif arrangement in preferences["work_arrangements"]:
        mode = "compatible"
    else:
        mode = "not_preferred"
    if not location:
        geography = "unknown"
    else:
        loc = _norm(location)
        local_terms = [_norm(x) for x in preferences["locations"] if _norm(x) in {"istanbul", "turkiye", "turkey"}]
        if arrangement == "remote" and any(x in loc for x in ("worldwide", "global", "work from anywhere")):
            geography = "uncertain_remote_eligibility"
        elif any(term and (term in loc or (term == "turkey" and "turkiye" in loc) or
                           (term == "turkiye" and "turkey" in loc)) for term in local_terms):
            geography = "compatible"
        elif arrangement in ("hybrid", "onsite") and "istanbul" in loc and any("istanbul" in _norm(x) for x in preferences["locations"]):
            geography = "compatible"
        else:
            geography = "uncertain"
    return {"location": geography, "work_arrangement": mode}


def _excluded_by_preference(opportunity, preferences):
    title = opportunity["claims"]["title"]["value"] or ""
    seniority = opportunity["claims"]["seniority"]["value"] or ""
    text = f"{title} {seniority}"
    return [term for term in preferences["excluded_roles"] if _has_phrase(text, term)]


def build_match_results(profile, preferences, opportunity_document, interpretation, evaluated_at=None):
    opportunities = validate_matching_inputs(profile, preferences, opportunity_document, interpretation)
    evaluated_at = evaluated_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    results = []
    for assessment in interpretation["assessments"]:
        opportunity = opportunities[assessment["opportunity_id"]]
        outcomes = [req["outcome"] for req in assessment["requirements"]]
        excluded = _excluded_by_preference(opportunity, preferences)
        if excluded:
            recommendation = "excluded_by_explicit_user_constraint"
        elif not outcomes:
            recommendation = "insufficient_information"
        elif all(outcome == "matched" for outcome in outcomes):
            recommendation = "promising_evidence"
        elif any(outcome in ("matched", "inferred_support") for outcome in outcomes):
            recommendation = "review_gaps_or_uncertainty"
        elif any(outcome == "cannot_assess" for outcome in outcomes):
            recommendation = "insufficient_information"
        else:
            recommendation = "limited_evidenced_fit"
        fit = {name: sum(outcome == name for outcome in outcomes)
               for name in ("matched", "inferred_support", "not_evidenced", "contradicted", "cannot_assess")}
        dims = _location_and_mode(opportunity, preferences)
        status = opportunity["claims"]["status"]["value"] if opportunity["claims"]["status"]["origin"] == "observed" else None
        warnings = []
        warnings.append("assessment_limited_to_requirements_with_cited_snapshot_evidence")
        if status is None:
            warnings.append("application_status_unknown")
        else:
            warnings.append("application_status_observed_at_last_source_check_not_current_guarantee")
        if dims["location"].startswith("uncertain") or dims["location"] == "unknown":
            warnings.append("location_or_remote_eligibility_uncertain")
        if dims["work_arrangement"] == "unknown":
            warnings.append("work_arrangement_unknown")
        if assessment["experience_alignment"]["outcome"] in ("uncertain", "unknown", "higher_than_evidenced"):
            warnings.append("seniority_or_experience_alignment_uncertain")
        record_by_id = {record["id"]: (section, record) for section in SECTIONS for record in profile[section]}
        unknown_skill_level = any(record_by_id[record_id][1]["level"] == "unknown"
                                  for req in assessment["requirements"] if req["outcome"] == "matched"
                                  for record_id in req["candidate_record_ids"]
                                  if record_by_id[record_id][0] == "technical_skills")
        if unknown_skill_level:
            warnings.append("skill_proficiency_level_unknown")
        if "inferred_support" in outcomes:
            warnings.append("some_requirement_matches_are_inference_dependent")
        explanations = {
            "excluded_by_explicit_user_constraint": "An explicit excluded-role preference matches this posting.",
            "insufficient_information": "The available cited evidence is insufficient for a reliable assessment.",
            "promising_evidence": "All assessed posting requirements have explicit candidate evidence; review the uncertainty warnings before deciding.",
            "review_gaps_or_uncertainty": "Some assessed requirements have supporting evidence while other requirements remain uncertain or not evidenced.",
            "limited_evidenced_fit": "The assessed requirements are not supported by the available profile evidence; unmentioned skills remain unknown."
        }
        results.append({
            "opportunity_id": opportunity["id"], "original_url": opportunity["original_url"],
            "title": opportunity["claims"]["title"]["value"], "employer": opportunity["claims"]["employer"]["value"],
            "last_observed_at": opportunity["last_observed_at"], "evaluated_at": evaluated_at,
            "recommendation": recommendation, "explanation": explanations[recommendation],
            "assessment_scope": "Only requirements represented by evidence in the supplied opportunity snapshot were assessed.",
            "candidate_fit": {"requirement_counts": fit, "requirements": assessment["requirements"]},
            "experience_alignment": assessment["experience_alignment"],
            "location_work_mode": dims, "career_alignment": assessment["career_alignment"],
            "hard_filter_violations": excluded, "warnings": warnings
        })
    return {"schema_version": "1", "evaluation_method": "Codex evidence-linked semantic interpretation; deterministic Python validation and aggregation", "results": results}


def save_match_results(document, workspace):
    return write_private_json_atomic(workspace, "matches", f"snapshot-{uuid4().hex}.json", document)


def main():
    parser = argparse.ArgumentParser(description="Validate and persist local evidence-grounded match results")
    parser.add_argument("profile", type=Path)
    parser.add_argument("preferences", type=Path)
    parser.add_argument("opportunities", type=Path)
    parser.add_argument("interpretation", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        inputs = [json.loads(path.read_text(encoding="utf-8")) for path in
                  (args.profile, args.preferences, args.opportunities, args.interpretation)]
        result = build_match_results(*inputs)
        path = save_match_results(result, args.workspace)
    except (OSError, UnicodeError, ValueError, StorageError):
        parser.exit(1, "matching failed: invalid_input_or_storage\n")
    print(json.dumps({"status": "saved", "output": str(path.relative_to(args.workspace)), "count": len(result["results"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
