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


_MATCH_STOPWORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
                    "in", "is", "of", "on", "or", "the", "to", "with", "experience",
                    "experienced", "knowledge", "ability", "skills", "skill", "required",
                    "requirement", "requirements", "preferred", "proficiency", "years", "year"}


def _substantive_terms(value):
    return {term for term in _norm(value).split() if len(term) > 1 and term not in _MATCH_STOPWORDS}


def validate_matching_sources(profile, preferences, opportunity_document):
    """Validate immutable source inputs, independently of Codex interpretation."""
    if validate_document(profile, "candidate_profile") or profile.get("verification_status") != "verified":
        raise MatchError("candidate_profile_must_be_verified_and_valid")
    if validate_document(preferences, "search_preferences"):
        raise MatchError("search_preferences_invalid")
    if validate_opportunities(opportunity_document):
        raise MatchError("opportunities_invalid")
    opportunities = {item["id"]: item for item in opportunity_document["opportunities"]}
    candidate_records = {}
    for section in SECTIONS:
        for record in records_for_downstream(profile, section):
            candidate_records[record["id"]] = (section, record)
    candidate_evidence = {item["id"]: item for item in profile["evidence"]
                          if item["review_status"] in ACCEPTED}
    return opportunities, candidate_records, candidate_evidence


def build_reference_catalog(profile, preferences, opportunity_document):
    """Return valid semantic references and their local provenance for Codex."""
    opportunities, candidate_records, candidate_evidence = validate_matching_sources(
        profile, preferences, opportunity_document)
    records_by_evidence = {identifier: [] for identifier in candidate_evidence}
    for record_id, (section, record) in candidate_records.items():
        for evidence_id in record["evidence_ids"]:
            if evidence_id in records_by_evidence:
                records_by_evidence[evidence_id].append({
                    "record_id": record_id, "section": section,
                    "name": record.get("name") or record.get("role") or record.get("degree") or record.get("title")
                })
    candidate_catalog = []
    for evidence_id, evidence in candidate_evidence.items():
        candidate_catalog.append({"evidence_id": evidence_id,
            "source_document_id": evidence["source_document_id"],
            "location": evidence.get("location"), "extraction": evidence["extraction"],
            "excerpt": evidence.get("excerpt"), "linked_records": records_by_evidence[evidence_id]})
    preference_catalog = []
    for field in ("preferred_roles", "excluded_roles", "locations", "work_arrangements", "seniority_preferences"):
        for index, value in enumerate(preferences[field], 1):
            preference_catalog.append({"reference_id": f"pref_{field}_{index:03d}",
                                       "field": field, "value": value})
    opportunity_catalog = []
    for opportunity in opportunity_document["opportunities"]:
        evidence_lookup = {item["id"]: item for item in opportunity["evidence"]}
        description_ids = opportunity["claims"]["description"]["evidence_ids"]
        requirement_slots = []
        for index, evidence_id in enumerate(description_ids, 1):
            evidence = evidence_lookup[evidence_id]
            requirement_slots.append({"requirement_id": f"r{index}",
                "job_evidence_id": evidence_id, "source_id": evidence["source_id"],
                "location": evidence.get("location"), "excerpt": evidence["excerpt"]})
        opportunity_catalog.append({"opportunity_id": opportunity["id"],
            "original_url": opportunity["original_url"],
            "claims": {field: {"value": opportunity["claims"][field]["value"],
                               "origin": opportunity["claims"][field]["origin"],
                               "evidence_ids": opportunity["claims"][field]["evidence_ids"]}
                       for field in ("title", "employer", "location", "work_arrangement", "seniority", "status")},
            "job_evidence": [{"evidence_id": evidence["id"], "source_id": evidence["source_id"],
                              "location": evidence.get("location"), "excerpt": evidence["excerpt"]}
                             for evidence in opportunity["evidence"]],
            "requirement_slots": requirement_slots})
    return {"catalog_version": "1", "candidate_evidence": candidate_catalog,
            "candidate_records": [{"record_id": identifier, "section": section,
                "name": record.get("name") or record.get("role") or record.get("degree") or record.get("title"),
                "evidence_ids": record["evidence_ids"]}
                for identifier, (section, record) in candidate_records.items()],
            "preferences": preference_catalog, "opportunities": opportunity_catalog}


def _assessment_errors(profile, preferences, opportunities, candidate_records,
                       candidate_evidence, assessment):
    """Return path/code diagnostics only; never echo candidate or posting values."""
    schema_path = Path(__file__).resolve().parent.parent / "references/matching-assessment.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    wrapper = {"schema_version": "1", "assessments": [assessment]}
    errors = []
    for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(wrapper):
        path = "assessments" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in list(error.absolute_path)[1:])
        errors.append({"path": path, "code": "schema_" + str(error.validator)})
    if errors:
        return errors
    opportunity = opportunities.get(assessment["opportunity_id"])
    if opportunity is None:
        return [{"path": "opportunity_id", "code": "unknown_opportunity_reference"}]
    job_evidence = {item["id"]: item for item in opportunity["evidence"]}
    errors = []
    catalog = build_reference_catalog(profile, preferences,
        {"schema_version": "1", "opportunities": [opportunity]})
    allowed_requirement_ids = {item["requirement_id"] for item in catalog["opportunities"][0]["requirement_slots"]}
    if any(item["id"] not in allowed_requirement_ids for item in assessment["requirements"]):
        errors.append({"path": "requirements.id", "code": "unknown_requirement_reference"})
    req_ids = [item["id"] for item in assessment["requirements"]]
    if len(set(req_ids)) != len(req_ids):
        errors.append({"path": "requirements", "code": "duplicate_requirement_id"})
    allowed_preference_ids = {item["reference_id"] for item in catalog["preferences"]
        if item["field"] == "preferred_roles"}
    career = assessment["career_alignment"]
    preference_refs = career.get("preference_refs", [])
    if preference_refs:
        if not set(preference_refs) <= allowed_preference_ids:
            errors.append({"path": "career_alignment.preference_refs", "code": "unknown_preference_reference"})
        resolved = {item["value"] for item in catalog["preferences"]
            if item["reference_id"] in preference_refs}
        if set(career["preference_terms"]) != resolved:
            errors.append({"path": "career_alignment.preference_terms", "code": "preference_reference_value_mismatch"})
    else:
        preference_terms = {_norm(x) for x in preferences["preferred_roles"]}
        if any(_norm(term) not in preference_terms for term in career["preference_terms"]):
            errors.append({"path": "career_alignment.preference_terms", "code": "unknown_preference_reference"})
    if career["outcome"] in ("aligned", "partial") and (
            not career["preference_terms"] or not career["job_evidence_ids"]):
        errors.append({"path": "career_alignment", "code": "career_alignment_missing_evidence_or_preference"})
    entries = [(f"requirements[{i}]", item) for i, item in enumerate(assessment["requirements"])]
    entries.append(("experience_alignment", assessment["experience_alignment"]))
    for path, item in entries:
        job_refs = set(item["job_evidence_ids"])
        record_refs = set(item["candidate_record_ids"])
        evidence_refs = set(item["candidate_evidence_ids"])
        if not job_refs <= set(job_evidence):
            errors.append({"path": path + ".job_evidence_ids", "code": "unknown_job_evidence_reference"})
        if not record_refs <= set(candidate_records):
            errors.append({"path": path + ".candidate_record_ids", "code": "unknown_or_unaccepted_candidate_record"})
        if not evidence_refs <= set(candidate_evidence):
            errors.append({"path": path + ".candidate_evidence_ids", "code": "unknown_or_unaccepted_candidate_evidence"})
        linked = {ref for record_id in record_refs if record_id in candidate_records
                  for ref in candidate_records[record_id][1]["evidence_ids"]}
        if record_refs and not evidence_refs <= linked:
            errors.append({"path": path + ".candidate_evidence_ids", "code": "candidate_evidence_not_linked_to_record"})
    job_refs = set(career["job_evidence_ids"])
    if not job_refs <= set(job_evidence):
        errors.append({"path": "career_alignment.job_evidence_ids", "code": "unknown_job_evidence_reference"})
    for index, req in enumerate(assessment["requirements"]):
        path = f"requirements[{index}]"
        outcome = req["outcome"]
        if not req["job_evidence_ids"]:
            errors.append({"path": path + ".job_evidence_ids", "code": "requirement_missing_job_evidence"})
        if outcome in ("matched", "inferred_support") and (
                not req["candidate_record_ids"] or not req["candidate_evidence_ids"]):
            errors.append({"path": path, "code": "positive_match_missing_candidate_evidence"})
        if outcome == "matched" and any(candidate_evidence.get(ref, {}).get("extraction") != "explicit"
                                         for ref in req["candidate_evidence_ids"]):
            errors.append({"path": path + ".outcome", "code": "inferred_support_must_be_labeled_uncertain"})
        if outcome == "not_evidenced" and (req["candidate_record_ids"] or req["candidate_evidence_ids"]):
            errors.append({"path": path, "code": "not_evidenced_requirement_has_candidate_reference"})
        if outcome == "contradicted" and (not req["candidate_evidence_ids"] or any(
                candidate_evidence.get(ref, {}).get("extraction") != "explicit"
                for ref in req["candidate_evidence_ids"])):
            errors.append({"path": path + ".candidate_evidence_ids", "code": "contradiction_requires_explicit_candidate_evidence"})
        quality = req.get("evidence_quality")
        if outcome == "matched" and quality != "direct_sufficient":
            errors.append({"path": path + ".evidence_quality", "code": "matched_requires_direct_sufficient_evidence"})
        if outcome == "matched" and req["candidate_record_ids"] and req["candidate_evidence_ids"]:
            requirement_terms = _substantive_terms(req["statement"])
            evidence_text = " ".join(candidate_evidence.get(ref, {}).get("excerpt", "") or ""
                                     for ref in req["candidate_evidence_ids"])
            record_text = " ".join(value for ref in req["candidate_record_ids"] if ref in candidate_records
                                   for value in candidate_records[ref][1].values() if isinstance(value, str))
            if not requirement_terms.intersection(_substantive_terms(evidence_text + " " + record_text)):
                errors.append({"path": path + ".candidate_evidence_ids",
                               "code": "matched_candidate_evidence_not_lexically_relevant"})
        if outcome == "inferred_support" and quality not in ("analogous_uncertain", "direct_sufficient"):
            errors.append({"path": path + ".evidence_quality", "code": "inferred_support_requires_quality_assessment"})
        if quality == "insufficient" and outcome in ("matched", "inferred_support"):
            errors.append({"path": path + ".outcome", "code": "insufficient_evidence_cannot_support_positive_match"})
    return errors


def validate_matching_inputs(profile, preferences, opportunity_document, interpretation):
    """Strict compatibility validator for a complete semantic interpretation."""
    opportunities, candidate_records, candidate_evidence = validate_matching_sources(
        profile, preferences, opportunity_document)
    if not isinstance(interpretation, dict) or interpretation.get("schema_version") != "1":
        raise MatchError("interpretation_schema_invalid")
    assessments = interpretation.get("assessments")
    if not isinstance(assessments, list) or not assessments or len({
            item.get("opportunity_id") for item in assessments if isinstance(item, dict)}) != len(assessments):
        raise MatchError("interpretation_opportunity_ids_invalid")
    for assessment in assessments:
        errors = _assessment_errors(profile, preferences, opportunities, candidate_records,
                                    candidate_evidence, assessment)
        if errors:
            raise MatchError(errors[0]["code"])
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


def _attempt_assessments(document):
    if not isinstance(document, dict) or document.get("schema_version") != "1" or not isinstance(document.get("assessments"), list):
        return {}, [{"path": "assessments", "code": "interpretation_root_invalid"}]
    mapping = {}
    errors = []
    for index, assessment in enumerate(document["assessments"]):
        if not isinstance(assessment, dict) or not isinstance(assessment.get("opportunity_id"), str):
            errors.append({"path": f"assessments[{index}]", "code": "assessment_opportunity_id_missing"})
            continue
        identifier = assessment["opportunity_id"]
        if identifier in mapping:
            errors.append({"path": f"assessments[{index}].opportunity_id", "code": "duplicate_assessment_opportunity"})
            continue
        mapping[identifier] = assessment
    return mapping, errors


def build_match_results_resilient(profile, preferences, opportunity_document,
                                  interpretation, repair_interpretation=None,
                                  evaluated_at=None):
    """Compute hard constraints for every valid source even if semantics fail.

    A single repair document is supported. Raw attempts and fixed diagnostics are
    retained in the local snapshot for audit; failed semantics are never repaired
    by Python or replaced with guessed references.
    """
    opportunities, candidate_records, candidate_evidence = validate_matching_sources(
        profile, preferences, opportunity_document)
    if repair_interpretation is not None and not isinstance(repair_interpretation, dict):
        raise MatchError("repair_interpretation_invalid")
    attempts = [interpretation]
    if repair_interpretation is not None:
        attempts.append(repair_interpretation)
    attempt_maps = [_attempt_assessments(item) for item in attempts]
    evaluated_at = evaluated_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    results = []
    for opportunity in opportunity_document["opportunities"]:
        opportunity_id = opportunity["id"]
        excluded = _excluded_by_preference(opportunity, preferences)
        dimensions = _location_and_mode(opportunity, preferences)
        attempt_history = []
        chosen = None
        errors = []
        for index, (assessment_map, root_errors) in enumerate(attempt_maps, 1):
            assessment = assessment_map.get(opportunity_id)
            if assessment is None:
                attempt_errors = root_errors or [{"path": "assessments", "code": "assessment_missing"}]
            else:
                attempt_errors = list(root_errors)
                attempt_errors.extend(_assessment_errors(profile, preferences, opportunities,
                    candidate_records, candidate_evidence, assessment))
            attempt_history.append({"attempt": index,
                "kind": "initial" if index == 1 else "single_bounded_repair",
                "assessment": assessment, "diagnostics": attempt_errors})
            if not attempt_errors and assessment is not None:
                chosen = assessment
                break
            errors = attempt_errors
        if chosen is None:
            results.append({"opportunity_id": opportunity_id,
                "original_url": opportunity["original_url"],
                "semantic_assessment": {"status": "invalid", "diagnostics": errors},
                "candidate_fit": None, "experience_alignment": None,
                "career_alignment": None,
                "hard_filter": {"status": "computed", "excluded_roles": excluded,
                                "location_work_mode": dimensions},
                "hard_filter_violations": excluded,
                "recommendation": "excluded_by_explicit_user_constraint" if excluded else "assessment_unavailable",
                "warnings": ["semantic_assessment_invalid", "hard_filter_evaluated_independently"],
                "repair_history": attempt_history})
            continue
        one_document = {"schema_version": "1", "opportunities": [opportunity]}
        one_interpretation = {"schema_version": "1", "assessments": [chosen]}
        aggregated = build_match_results(profile, preferences, one_document,
                                         one_interpretation, evaluated_at=evaluated_at)["results"][0]
        aggregated["semantic_assessment"] = {"status": "aggregated", "diagnostics": []}
        aggregated["hard_filter"] = {"status": "computed", "excluded_roles": excluded,
                                     "location_work_mode": dimensions}
        aggregated["repair_history"] = attempt_history
        results.append(aggregated)
    return {"schema_version": "2",
            "evaluation_method": "Codex semantic interpretation; deterministic catalog, validation, hard filters, and aggregation",
            "results": results}


def save_match_results(document, workspace):
    return write_private_json_atomic(workspace, "matches", f"snapshot-{uuid4().hex}.json", document)


def main():
    parser = argparse.ArgumentParser(description="Validate, audit, and persist local evidence-grounded match results")
    parser.add_argument("profile", type=Path)
    parser.add_argument("preferences", type=Path)
    parser.add_argument("opportunities", type=Path)
    parser.add_argument("interpretation", type=Path)
    parser.add_argument("--repair", type=Path,
                        help="one Codex repair attempt, produced from validator diagnostics and the reference catalog")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        profile, preferences, opportunities, interpretation = [json.loads(path.read_text(encoding="utf-8")) for path in
                  (args.profile, args.preferences, args.opportunities, args.interpretation)]
        repair = json.loads(args.repair.read_text(encoding="utf-8")) if args.repair else None
        result = build_match_results_resilient(profile, preferences, opportunities,
                                               interpretation, repair)
        path = save_match_results(result, args.workspace)
    except (OSError, UnicodeError, ValueError, StorageError):
        parser.exit(1, "matching failed: invalid_input_or_storage\n")
    valid = sum(item["semantic_assessment"]["status"] == "aggregated" for item in result["results"])
    print(json.dumps({"status": "saved", "output": str(path.relative_to(args.workspace)),
                      "count": len(result["results"]), "semantic_aggregated": valid,
                      "semantic_failed": len(result["results"]) - valid}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
