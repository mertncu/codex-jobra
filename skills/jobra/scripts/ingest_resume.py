"""Extract local resume text and source locations without semantic inference."""

from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re

from docx import Document
from docx.table import Table
from pypdf import PdfReader

from local_storage import StorageError, write_private_json


MAX_FILE_BYTES = 10 * 1024 * 1024
FORMATS = {".pdf": "pdf", ".docx": "docx", ".md": "markdown", ".txt": "txt"}


class IngestionError(Exception):
    """A fixed, privacy-safe ingestion failure code."""


def _clean(text: str) -> str:
    return text.replace("\x00", "").strip()


def _pdf_segments(data: bytes) -> list[dict]:
    if b"%PDF-" not in data[:1024]:
        raise IngestionError("invalid_format")
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise IngestionError("unreadable_document")
        segments = []
        for page_number, page in enumerate(reader.pages, start=1):
            content = _clean(page.extract_text() or "")
            if content:
                segments.append({"location": f"page {page_number}", "text": content})
        return segments
    except IngestionError:
        raise
    except Exception:
        raise IngestionError("unreadable_document") from None


def _docx_segments(data: bytes) -> list[dict]:
    try:
        document = Document(BytesIO(data))
        segments = []
        section = None
        paragraph_number = 0
        table_number = 0
        for block in document.iter_inner_content():
            if isinstance(block, Table):
                table_number += 1
                for row_number, row in enumerate(block.rows, start=1):
                    for cell_number, cell in enumerate(row.cells, start=1):
                        content = _clean(cell.text)
                        if content:
                            item = {"location": f"table {table_number}, row {row_number}, cell {cell_number}", "text": content}
                            if section:
                                item["section"] = section
                            segments.append(item)
                continue
            paragraph_number += 1
            content = _clean(block.text)
            if not content:
                continue
            if block.style and block.style.name.startswith("Heading"):
                section = content
            item = {"location": f"paragraph {paragraph_number}", "text": content}
            if section:
                item["section"] = section
            segments.append(item)
        return segments
    except Exception:
        raise IngestionError("unreadable_document") from None


def _text_segments(data: bytes, markdown: bool) -> list[dict]:
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise IngestionError("unreadable_document") from None
    if "\x00" in content:
        raise IngestionError("unreadable_document")
    lines = content.splitlines()
    segments: list[dict] = []
    section = None
    paragraph: list[str] = []
    start_line = 0

    def flush(end_line: int) -> None:
        nonlocal paragraph
        if not paragraph:
            return
        location = f"line {start_line}" if start_line == end_line else f"lines {start_line}-{end_line}"
        item = {"location": location, "text": "\n".join(paragraph)}
        if section:
            item["section"] = section
        segments.append(item)
        paragraph = []

    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        heading = re.match(r"^#{1,6}\s+(.+?)(?:\s+#+)?\s*$", stripped) if markdown else None
        if heading:
            flush(number - 1)
            section = heading.group(1)
            segments.append({"location": f"line {number}", "section": section, "text": stripped})
        elif not stripped:
            flush(number - 1)
        else:
            if not paragraph:
                start_line = number
            paragraph.append(line)
    flush(len(lines))
    return segments


def ingest_resume(path: Path) -> dict:
    """Return text segments and an opaque, stable source-document ID."""
    source = Path(path)
    kind = FORMATS.get(source.suffix.lower())
    if kind is None:
        raise IngestionError("unsupported_format")
    try:
        if not source.is_file():
            raise IngestionError("missing_file")
        if source.stat().st_size > MAX_FILE_BYTES:
            raise IngestionError("file_too_large")
        data = source.read_bytes()
    except IngestionError:
        raise
    except OSError:
        raise IngestionError("unreadable_file") from None
    if not data:
        raise IngestionError("empty_document")
    if len(data) > MAX_FILE_BYTES:
        raise IngestionError("file_too_large")
    if kind == "pdf":
        segments = _pdf_segments(data)
    elif kind == "docx":
        segments = _docx_segments(data)
    else:
        segments = _text_segments(data, markdown=kind == "markdown")
    if not segments:
        raise IngestionError("empty_document")
    source_id = "resume_" + sha256(data).hexdigest()[:24]
    return {
        "schema_version": "1",
        "source_document": {"id": source_id, "kind": "resume"},
        "format": kind,
        "segments": segments,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a local resume into private JSON segments")
    parser.add_argument("resume", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        extracted = ingest_resume(args.resume)
        source_id = extracted["source_document"]["id"]
        write_private_json(args.workspace, "ingested", f"{source_id}.json", extracted)
    except (IngestionError, StorageError) as error:
        parser.exit(1, f"ingestion failed: {error}\n")
    print(json.dumps({"source_document_id": source_id, "segments": len(extracted["segments"]), "output": f".jobra/ingested/{source_id}.json"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
