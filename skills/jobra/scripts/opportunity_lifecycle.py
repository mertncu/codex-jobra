"""Deterministic duplicate review and append-only freshness observations."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class LifecycleError(ValueError):
    """Fixed-code lifecycle failure; never includes posting content."""


def _dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalize_posting_url(url):
    """Normalize harmless URL differences while retaining job-identifying query values."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.port and parts.port not in (80, 443):
        host += f":{parts.port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"ref", "source", "gh_src"}]
    query.sort()
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(query), ""))


def _norm(value):
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").casefold()))


def classify_relationship(left, right):
    """Return (classification, reason) without merging any input records."""
    if left["id"] == right["id"]:
        return "same_opportunity_high_confidence", "stable opportunity identifier matches"
    left_urls = {normalize_posting_url(left["original_url"])} | {
        normalize_posting_url(item["url"]) for item in left["sources"]}
    right_urls = {normalize_posting_url(right["original_url"])} | {
        normalize_posting_url(item["url"]) for item in right["sources"]}
    if left_urls & right_urls:
        return "same_opportunity_high_confidence", "canonical posting URL matches"
    left_id = left.get("claims", {}).get("posting_id", {}).get("value")
    right_id = right.get("claims", {}).get("posting_id", {}).get("value")
    left_employer = _norm(left["claims"]["employer"].get("value"))
    right_employer = _norm(right["claims"]["employer"].get("value"))
    if left_id and right_id and _norm(left_id) == _norm(right_id) and left_employer and left_employer == right_employer:
        return "same_opportunity_high_confidence", "explicit posting ID and employer match"
    if (left_employer and left_employer == right_employer and
            _norm(left["claims"]["title"].get("value")) == _norm(right["claims"]["title"].get("value"))):
        a, b = _norm(left["claims"]["location"].get("value")), _norm(right["claims"]["location"].get("value"))
        if not a or not b or a == b:
            return "possible_duplicate_requires_review", "employer and title match; location is compatible"
    return "distinct_opportunities", "no trustworthy identity match"


def merge_same_opportunity(left, right):
    """Conservatively merge only high-confidence, non-conflicting records, preserving all evidence."""
    classification, _ = classify_relationship(left, right)
    if classification != "same_opportunity_high_confidence":
        raise LifecycleError("merge_requires_high_confidence_identity")
    if right["id"] < left["id"]:
        left, right = right, left
    a, b = deepcopy(left), deepcopy(right)
    merged = deepcopy(a)
    sources = {item["id"]: item for item in a["sources"]}
    evidence = {item["id"]: item for item in a["evidence"]}
    source_map, evidence_map = {}, {}
    for source in b["sources"]:
        old = source["id"]
        if old not in sources:
            source["id"] = old
        elif sources[old] != source:
            source["id"] = "src_" + hashlib.sha256((b["id"] + old + source["url"]).encode()).hexdigest()[:20]
        source_map[old] = source["id"]
        sources[source["id"]] = source
    for item in b["evidence"]:
        old = item["id"]
        item["source_id"] = source_map[item["source_id"]]
        if old in evidence and evidence[old] != item:
            item["id"] = "ev_" + hashlib.sha256((b["id"] + old + item["excerpt"]).encode()).hexdigest()[:20]
        evidence_map[old] = item["id"]
        evidence[item["id"]] = item
    for name, claim in b["claims"].items():
        claim["evidence_ids"] = [evidence_map.get(ref, ref) for ref in claim["evidence_ids"]]
        current = merged["claims"].get(name)
        if current is None:
            merged["claims"][name] = claim
        elif current["value"] is None and claim["value"] is not None:
            merged["claims"][name] = claim
        elif claim["value"] is not None and current["value"] is not None and current["value"] != claim["value"]:
            if name != "status":
                raise LifecycleError("conflicting_claims_require_review")
            # Current status cannot be carried across observations with disagreement.
            merged["claims"][name] = {"value": None, "origin": "unknown", "evidence_ids": []}
        elif current["value"] == claim["value"]:
            current["evidence_ids"] = sorted(set(current["evidence_ids"] + claim["evidence_ids"]))
    merged["sources"] = sorted(sources.values(), key=lambda x: (x["observed_at"], x["url"], x["id"]))
    merged["evidence"] = sorted(evidence.values(), key=lambda x: (x["source_id"], x["id"]))
    merged["discovered_at"] = min((a["discovered_at"], b["discovered_at"]), key=_dt)
    merged["last_observed_at"] = max((a["last_observed_at"], b["last_observed_at"]), key=_dt)
    latest = [s for s in merged["sources"] if _dt(s["observed_at"]) == _dt(merged["last_observed_at"])]
    if any(s["access"] == "inaccessible" for s in latest):
        merged["claims"]["status"] = {"value": None, "origin": "unknown", "evidence_ids": []}
    else:
        latest_ids = {s["id"] for s in latest}
        evidence_by_id = {item["id"]: item for item in merged["evidence"]}
        status = merged["claims"]["status"]
        if status["origin"] != "unknown" and not all(
                evidence_by_id[ref]["source_id"] in latest_ids for ref in status["evidence_ids"]):
            merged["claims"]["status"] = {"value": None, "origin": "unknown", "evidence_ids": []}
    merged["original_url"] = min((a["original_url"], b["original_url"]))
    selected = next(s for s in merged["sources"] if s["url"] == merged["original_url"])
    merged["source_platform"] = selected["platform"]
    return merged


def append_observation(opportunity, source, evidence=(), explicit_status=None, status_evidence_ids=()):
    """Return a new record with an appended observation; prior record is never mutated."""
    result = deepcopy(opportunity)
    try:
        observed = datetime.fromisoformat(source["observed_at"].replace("Z", "+00:00"))
        latest = datetime.fromisoformat(result["last_observed_at"].replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError):
        raise LifecycleError("invalid_observation_time") from None
    if observed < latest or source.get("id") in {x["id"] for x in result["sources"]}:
        raise LifecycleError("observation_must_be_new_and_monotonic")
    result["sources"].append(deepcopy(source))
    result["evidence"].extend(deepcopy(list(evidence)))
    result["last_observed_at"] = source["observed_at"]
    result["claims"]["status"] = {"value": None, "origin": "unknown", "evidence_ids": []}
    if explicit_status is not None:
        if source["access"] != "accessible" or not status_evidence_ids:
            raise LifecycleError("explicit_status_requires_accessible_evidence")
        known = {item["id"] for item in result["evidence"]}
        if not set(status_evidence_ids) <= known:
            raise LifecycleError("unknown_status_evidence")
        result["claims"]["status"] = {"value": explicit_status, "origin": "observed", "evidence_ids": list(status_evidence_ids)}
    return result


def freshness_state(opportunity):
    """Describe the latest recorded observation; do not infer current vacancy status."""
    latest = max(opportunity["sources"], key=lambda x: _dt(x["observed_at"]))
    result = latest.get("observation_result", "reachable" if latest["access"] == "accessible" else "unknown")
    return {"discovered_at": opportunity["discovered_at"], "last_observed_at": latest["observed_at"],
            "source_reachable": latest["access"] == "accessible", "observation_result": result,
            "application_status": opportunity["claims"]["status"]["value"] if
            opportunity["claims"]["status"]["origin"] == "observed" and latest["access"] == "accessible" else None}
