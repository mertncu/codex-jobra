"""Offline opportunity schema and provenance validation; no source content in errors."""

from datetime import datetime, date
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from validate_profile import FORMAT_CHECKER

CHECKER = FormatChecker()


@CHECKER.checks("uri")
def _uri(value):
    return FORMAT_CHECKER.conforms(value, "uri")


@CHECKER.checks("date-time")
def _timestamp(value):
    if not isinstance(value, str):
        return True
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})", value):
        return False
    try:
        if value[-6] in "+-" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
            return False
        _time(value)
        return True
    except ValueError:
        return False


@CHECKER.checks("date")
def _date(value):
    if not isinstance(value, str):
        return True
    try:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) and bool(date.fromisoformat(value))
    except ValueError:
        return False


def _time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))


def validate_opportunities(document):
    schema = json.loads((Path(__file__).resolve().parent.parent /
                         "references/opportunities.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=CHECKER)
    # Do not expose property names: arbitrary extra keys may contain private text.
    errors = sorted({f"schema: {error.validator} validation failed"
                     for error in validator.iter_errors(document)})
    if errors:
        return errors
    opportunity_ids = set()
    for index, opportunity in enumerate(document["opportunities"]):
        prefix = f"opportunities[{index}]"

        def fail(rule):
            errors.append(f"{prefix}: {rule}")

        if opportunity["id"] in opportunity_ids:
            fail("duplicate opportunity identifier")
        opportunity_ids.add(opportunity["id"])
        discovered = _time(opportunity["discovered_at"])
        last = _time(opportunity["last_observed_at"])
        if discovered > last:
            fail("discovery follows last observation")
        sources = {source["id"]: source for source in opportunity["sources"]}
        evidence = {item["id"]: item for item in opportunity["evidence"]}
        if len(sources) != len(opportunity["sources"]):
            fail("duplicate source identifier")
        if len(evidence) != len(opportunity["evidence"]):
            fail("duplicate evidence identifier")
        urls = [opportunity["original_url"]] + [source["url"] for source in sources.values()]
        for url in urls:
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None or parts.password is not None:
                fail("invalid source URL")
        if not any(source["url"] == opportunity["original_url"] and
                   source["platform"] == opportunity["source_platform"] for source in sources.values()):
            fail("original posting lacks source observation")
        for source in sources.values():
            observed = _time(source["observed_at"])
            if not discovered <= observed <= last:
                fail("source observation outside discovery window")
        if not any(_time(source["observed_at"]) == last for source in sources.values()):
            fail("last observation lacks source record")
        for item in evidence.values():
            source = sources.get(item["source_id"])
            if source is None:
                fail("unknown evidence source")
            elif source["access"] != "accessible":
                fail("content evidence cites inaccessible observation")
        for field, claim in opportunity["claims"].items():
            for ref in claim["evidence_ids"]:
                if ref not in evidence:
                    fail(f"claims.{field}: unknown evidence")
            if field in ("salary", "seniority", "employment_type", "posting_date", "status") and claim["origin"] == "inferred":
                fail(f"claims.{field}: explicit observation required")
            if field == "posting_date" and claim["value"] is not None:
                posting = date.fromisoformat(claim["value"])
                if posting > last.date():
                    fail("posting date follows last observation")
                for ref in claim["evidence_ids"]:
                    source = sources.get(evidence.get(ref, {}).get("source_id"))
                    if source and posting > _time(source["observed_at"]).date():
                        fail("posting date follows supporting observation")
            if field == "status" and claim["origin"] != "unknown":
                for ref in claim["evidence_ids"]:
                    source = sources.get(evidence.get(ref, {}).get("source_id"))
                    if source and (_time(source["observed_at"]) != last or source["access"] != "accessible"):
                        fail("status requires latest accessible evidence")
                if any(_time(source["observed_at"]) == last and source["access"] == "inaccessible"
                       for source in sources.values()):
                    fail("latest inaccessible observation requires unknown status")
    return sorted(set(errors))
