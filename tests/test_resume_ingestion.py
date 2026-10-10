"""Synthetic local resume ingestion and draft workflow tests."""

import copy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from pypdf import PdfWriter


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/jobra/scripts"
sys.path.insert(0, str(SCRIPTS))

from ingest_resume import IngestionError, ingest_resume  # noqa: E402
from save_profile_draft import DraftError, save_profile_draft, validate_draft_against_ingestion  # noqa: E402
from validate_profile import validate_document  # noqa: E402


FIXTURES = ROOT / "tests/fixtures"


def synthetic_draft(ingested):
    """Stand in for Codex reasoning over known synthetic fixture text."""
    source = ingested["source_document"]
    pending = {section: "pending" for section in
               ("education", "experience", "projects", "technical_skills", "suggested_roles")}
    claims = (
        ("ev_school", "Example University - BSc Computer Science", "explicit"),
        ("ev_intern", "Software intern at Example Studio", "explicit"),
        ("ev_project", "Built a sample task tracker with Python", "explicit"),
        ("ev_skill", "Python", "explicit"),
        ("ev_role", "Built a sample task tracker with Python", "inferred"),
    )
    evidence = []
    for identifier, excerpt, extraction in claims:
        segment = next(item for item in ingested["segments"] if excerpt in item["text"])
        evidence.append({
            "id": identifier,
            "source_document_id": source["id"],
            "location": segment["location"],
            "excerpt": excerpt,
            "extraction": extraction,
            "review_status": "pending",
        })
    return {
        "schema_version": "1",
        "verification_status": "draft",
        "section_reviews": pending,
        "source_documents": [source],
        "evidence": evidence,
        "education": [{"id": "edu_1", "origin": "extracted", "review_status": "pending", "evidence_ids": ["ev_school"], "institution": "Example University", "credential": "BSc", "field": "Computer Science"}],
        "experience": [{"id": "exp_1", "origin": "extracted", "review_status": "pending", "evidence_ids": ["ev_intern"], "organization": "Example Studio", "role": "Software intern", "kind": "internship"}],
        "projects": [{"id": "proj_1", "origin": "extracted", "review_status": "pending", "evidence_ids": ["ev_project"], "name": "Sample task tracker"}],
        "technical_skills": [{"id": "skill_1", "origin": "extracted", "review_status": "pending", "evidence_ids": ["ev_skill"], "name": "Python", "level": "unknown"}],
        "suggested_roles": [{"id": "role_1", "origin": "extracted", "review_status": "pending", "evidence_ids": ["ev_role"], "title": "Software developer"}],
    }


class ResumeIngestionTests(unittest.TestCase):
    def test_pdf_pages_and_stable_source_id(self):
        path = FIXTURES / "synthetic-resume.pdf"
        result = ingest_resume(path)
        self.assertEqual("pdf", result["format"])
        self.assertEqual(["page 1", "page 2"], [item["location"] for item in result["segments"]])
        self.assertIn("Example University", result["segments"][0]["text"])
        self.assertIn("Example Studio", result["segments"][1]["text"])
        self.assertEqual(result["source_document"]["id"], ingest_resume(path)["source_document"]["id"])

    def test_docx_paragraphs_sections_and_tables(self):
        result = ingest_resume(FIXTURES / "synthetic-resume.docx")
        self.assertEqual("docx", result["format"])
        university = next(item for item in result["segments"] if "Example University" in item["text"])
        self.assertEqual("Education", university["section"])
        self.assertTrue(university["location"].startswith("paragraph "))
        project = next(item for item in result["segments"] if "task tracker" in item["text"])
        self.assertEqual("table 1, row 1, cell 1", project["location"])

    def test_markdown_and_txt_line_locations(self):
        markdown = ingest_resume(FIXTURES / "synthetic-resume.md")
        school = next(item for item in markdown["segments"] if "Example University" in item["text"])
        self.assertEqual("Education", school["section"])
        self.assertEqual("line 4", school["location"])
        plain = ingest_resume(FIXTURES / "synthetic-resume.txt")
        self.assertEqual("line 1", plain["segments"][0]["location"])
        self.assertEqual("line 3", plain["segments"][1]["location"])

    def test_missing_unsupported_empty_and_unreadable(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = (("missing.pdf", None, "missing_file"),
                     ("resume.rtf", b"ignored", "unsupported_format"),
                     ("empty.txt", b"", "empty_document"),
                     ("whitespace.txt", b"  \n\n\t", "empty_document"),
                     ("bad.txt", b"\xff\xfe\x00", "unreadable_document"),
                     ("bad.pdf", b"not a PDF", "invalid_format"),
                     ("bad.docx", b"not a DOCX", "unreadable_document"))
            for filename, data, expected in cases:
                with self.subTest(filename=filename):
                    path = root / filename
                    if data is not None:
                        path.write_bytes(data)
                    with self.assertRaises(IngestionError) as caught:
                        ingest_resume(path)
                    self.assertEqual(expected, str(caught.exception))

    def test_image_only_pdf_has_no_text(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "blank.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            with path.open("wb") as stream:
                writer.write(stream)
            with self.assertRaises(IngestionError) as caught:
                ingest_resume(path)
            self.assertEqual("empty_document", str(caught.exception))

    def test_cli_writes_private_json_without_stdout_text(self):
        with TemporaryDirectory() as temporary:
            run = subprocess.run(
                [sys.executable, str(SCRIPTS / "ingest_resume.py"), str(FIXTURES / "synthetic-resume.md"), "--workspace", temporary],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, run.returncode)
            self.assertNotIn("Example University", run.stdout + run.stderr)
            metadata = json.loads(run.stdout)
            output = Path(temporary) / metadata["output"]
            self.assertTrue(output.is_file())
            self.assertEqual(0o600, output.stat().st_mode & 0o777)
            self.assertEqual("markdown", json.loads(output.read_text())["format"])
            second = subprocess.run(
                [sys.executable, str(SCRIPTS / "ingest_resume.py"), str(FIXTURES / "synthetic-resume.md"), "--workspace", temporary],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(1, second.returncode)
            self.assertIn("output_exists", second.stderr)
            self.assertNotIn("Example University", second.stderr)

    def test_complete_synthetic_draft_workflow(self):
        ingested = ingest_resume(FIXTURES / "synthetic-resume.md")
        profile = synthetic_draft(ingested)
        self.assertEqual([], validate_document(profile, "candidate_profile"))
        self.assertEqual([], validate_draft_against_ingestion(profile, ingested))
        self.assertEqual("unknown", profile["technical_skills"][0]["level"])
        self.assertEqual("inferred", profile["evidence"][-1]["extraction"])
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            saved = save_profile_draft(profile, ingested, root)
            self.assertTrue(saved.is_file())
            self.assertEqual("draft", json.loads(saved.read_text())["verification_status"])
            self.assertEqual(0o600, saved.stat().st_mode & 0o777)

    def test_draft_cli_validates_and_hides_private_text(self):
        ingested = ingest_resume(FIXTURES / "synthetic-resume.md")
        profile = synthetic_draft(ingested)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposed = root / ".jobra/proposed.json"
            proposed.parent.mkdir()
            proposed.write_text(json.dumps(profile), encoding="utf-8")
            extracted = root / ".jobra/ingested.json"
            extracted.write_text(json.dumps(ingested), encoding="utf-8")
            command = [sys.executable, str(SCRIPTS / "save_profile_draft.py"),
                       str(proposed), str(extracted), "--workspace", temporary]
            run = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(0, run.returncode)
            self.assertNotIn("Example University", run.stdout + run.stderr)
            saved = root / json.loads(run.stdout)["output"]
            self.assertEqual(profile, json.loads(saved.read_text(encoding="utf-8")))
            profile["verification_status"] = "verified"
            proposed.write_text(json.dumps(profile), encoding="utf-8")
            refused = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(1, refused.returncode)
            self.assertIn("invalid_profile_draft", refused.stderr)
            self.assertNotIn("Example University", refused.stderr)

    def test_invalid_draft_and_fabricated_evidence_rejected(self):
        ingested = ingest_resume(FIXTURES / "synthetic-resume.md")
        profile = synthetic_draft(ingested)
        invalid = copy.deepcopy(profile)
        invalid["education"][0].pop("institution")
        with TemporaryDirectory() as temporary:
            with self.assertRaises(DraftError):
                save_profile_draft(invalid, ingested, Path(temporary))
        for key, value in (("location", "page 999"), ("excerpt", "Invented qualification")):
            altered = copy.deepcopy(profile)
            altered["evidence"][0][key] = value
            self.assertTrue(validate_draft_against_ingestion(altered, ingested))

    def test_no_accidental_verification_or_verified_overwrite(self):
        ingested = ingest_resume(FIXTURES / "synthetic-resume.md")
        profile = synthetic_draft(ingested)
        verified = copy.deepcopy(profile)
        verified["verification_status"] = "verified"
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / ".jobra/profiles/verified.json"
            existing.parent.mkdir(parents=True)
            existing.write_text("existing verified profile")
            with self.assertRaises(DraftError):
                save_profile_draft(verified, ingested, root)
            saved = save_profile_draft(profile, ingested, root)
            self.assertNotEqual(existing, saved)
            self.assertEqual("existing verified profile", existing.read_text())


if __name__ == "__main__":
    unittest.main()
