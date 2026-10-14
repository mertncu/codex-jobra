"""Prepare a reviewer packet from frozen V2.1 labels and V0.2.2 predictions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
RUN_DIR = Path(__file__).resolve().parent
SOURCE = ROOT / "evaluation/matching/challenge_v2"


def build_packet(prediction_path: Path):
    inputs = json.loads((SOURCE / "inputs.v2.json").read_text(encoding="utf-8"))
    labels = json.loads((SOURCE / "labels.v2.json").read_text(encoding="utf-8"))
    predictions = json.loads(prediction_path.read_text(encoding="utf-8"))
    input_cases = {item["id"]: item for item in inputs["cases"]}
    label_cases = {item["case_id"]: item for item in labels["cases"]}
    prediction_cases = {item["case_id"]: item for item in predictions["predictions"]}
    opportunities = {item["id"]: item for item in inputs["opportunities"]["opportunities"]}
    selected = {"case_07"} | {item["case_id"] for item in labels["cases"]
        if any(req["evidence_support"] == "ambiguous" for req in item["requirements"])}
    review_items = []
    for case_id in sorted(selected):
        case = input_cases[case_id]
        gold_case = label_cases[case_id]
        pred_case = prediction_cases[case_id]
        assessment = pred_case["assessment"]["assessments"][0]
        profile = inputs["candidates"][case["candidate"]]
        opportunity = opportunities[case["opportunity"]]
        req_lookup = {item["id"]: item for item in assessment["requirements"]}
        for gold in gold_case["requirements"]:
            actual = req_lookup.get(gold["id"])
            if actual is None:
                source_ids = set(gold.get("job_evidence_ids", []))
                matches = [item for item in assessment["requirements"]
                    if source_ids.intersection(item.get("job_evidence_ids", []))]
                actual = matches[0] if len(matches) == 1 else None
            candidate_refs = set(gold.get("candidate_evidence_ids", []))
            if actual:
                candidate_refs.update(actual.get("candidate_evidence_ids", []))
            evidence_by_id = {item["id"]: item for item in profile["evidence"]}
            job_refs = set(gold.get("job_evidence_ids", []))
            if actual:
                job_refs.update(actual.get("job_evidence_ids", []))
            job_by_id = {item["id"]: item for item in opportunity["evidence"]}
            if case_id == "case_07":
                disagreement = "The candidate has explicit Python skill and a Python project, but no evidence of giving product demonstrations. Decide whether the whole compound requirement is directly matched, only analogously supported, or undocumented in its product-demonstration facet."
            elif case_id == "case_11":
                disagreement = "AWS is listed and software employment is dated, but no cloud-operation duties are documented. Decide whether this is not_evidenced or cannot_assess; separately review the missing seniority/experience uncertainty warning."
            else:
                disagreement = "The frozen support label is ambiguous. Review whether the cited candidate evidence semantically supports the exact qualification and whether the existing classification expresses that relationship."
            review_items.append({
                "review_item_id": f"{case_id}_{gold['id']}", "case_id": case_id,
                "candidate_source_documents": profile["source_documents"],
                "candidate_evidence": [evidence_by_id[identifier] for identifier in sorted(candidate_refs)
                    if identifier in evidence_by_id],
                "opportunity": {"id": opportunity["id"], "title": opportunity["claims"]["title"]["value"],
                    "original_url": opportunity["original_url"],
                    "requirement_evidence": [job_by_id[identifier] for identifier in sorted(job_refs)
                        if identifier in job_by_id]},
                "agent_prediction": None if actual is None else {key: actual.get(key) for key in
                    ("id", "statement", "priority", "outcome", "evidence_quality", "candidate_record_ids",
                     "candidate_evidence_ids", "job_evidence_ids", "rationale")},
                "agent_experience_alignment": assessment.get("experience_alignment"),
                "frozen_golden_expectation": {key: gold.get(key) for key in
                    ("id", "expected", "evidence_support", "candidate_evidence_ids", "job_evidence_ids")},
                "frozen_required_uncertainties": gold_case.get("required_uncertainties", []),
                "disagreement_or_review_question": disagreement,
                "available_reviewer_decisions": {
                    "classification": ["matched", "inferred_support", "not_evidenced", "contradicted", "cannot_assess"],
                    "evidence_support": ["supported", "unsupported", "ambiguous"]},
                "reviewer_decision": None, "reviewer_evidence_support": None,
                "reviewer_rationale": None, "reviewer_id": None, "reviewed_at": None,
                "review_status": "pending"})
    return {"packet_version": "jobra-human-adjudication-v2.3",
        "source_dataset": "matching-challenge-v2", "source_predictions": predictions.get("prediction_run_id"),
        "golden_labels_modified": False, "independent_human_review_performed": False,
        "reviewer_instructions": "Inspect the synthetic source excerpts and job requirement. Choose a decision and evidence-support label, then fill reviewer_rationale. Do not resolve uncertainty in Jobra's favor by default.",
        "items": review_items}


def render_markdown(packet):
    lines = ["# Jobra V2.3 human adjudication packet", "",
        f"Source challenge: `{packet['source_dataset']}`. Golden labels modified: `{packet['golden_labels_modified']}`. Independent human review performed: `{packet['independent_human_review_performed']}`.",
        "", packet["reviewer_instructions"], ""]
    for item in packet["items"]:
        prediction = item["agent_prediction"] or {}
        expected = item["frozen_golden_expectation"]
        lines.extend([f"## {item['review_item_id']}", "",
            f"Question: {item['disagreement_or_review_question']}", "",
            f"Frozen expectation: `{expected['expected']}`; support `{expected['evidence_support']}`; refs `{expected['candidate_evidence_ids']}`.", "",
            f"Agent prediction: `{prediction.get('outcome')}`; quality `{prediction.get('evidence_quality')}`; refs `{prediction.get('candidate_evidence_ids')}`.", "",
            f"Agent rationale: {prediction.get('rationale', 'No aligned requirement prediction found.')}", "",
            "Candidate evidence:"])
        for evidence in item["candidate_evidence"]:
            lines.append(f"- `{evidence['id']}` ({evidence['source_document_id']} / {evidence.get('location', 'location unknown')}): {evidence.get('excerpt', '[no excerpt]')}")
        lines.append("Job evidence:")
        for evidence in item["opportunity"]["requirement_evidence"]:
            lines.append(f"- `{evidence['id']}` ({evidence.get('location', 'location unknown')}): {evidence['excerpt']}")
        lines.extend(["", "Available classification decisions: `matched`, `inferred_support`, `not_evidenced`, `contradicted`, `cannot_assess`.",
            "Available evidence-support decisions: `supported`, `unsupported`, `ambiguous`.",
            "Reviewer classification: **pending**", "Reviewer evidence support: **pending**",
            "Reviewer rationale: **required; not supplied**", ""])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Prepare synthetic matching adjudication packet")
    parser.add_argument("--predictions", type=Path, required=True)
    args = parser.parse_args()
    packet = build_packet(args.predictions)
    path = RUN_DIR / "human-review-packet.v2.3.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != packet:
            parser.error("existing review packet changed; refusing to overwrite reviewer decisions")
    else:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
    markdown_path = RUN_DIR / "human-review-packet.v2.3.md"
    if not markdown_path.exists():
        with markdown_path.open("x", encoding="utf-8") as stream:
            stream.write(render_markdown(packet))
    print(json.dumps({"status": "prepared", "items": len(packet["items"]),
        "unresolved": sum(item["review_status"] == "pending" for item in packet["items"]), "path": str(path)}))


if __name__ == "__main__":
    main()
