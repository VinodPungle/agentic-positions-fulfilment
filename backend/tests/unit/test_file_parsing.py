"""Unit tests for parse_file_bytes — specifically the exception-handling branches
added in the logging pass: malformed files must degrade to a clean HTTPException,
not an unhandled 500, and must not be silently swallowed (each has a log line).
"""
import io
import logging
import pytest
from docx import Document
from fastapi import HTTPException

import server


def test_parse_text_file_decodes_utf8_sig():
    # 'utf-8-sig' encoding adds the BOM prefix itself — plain text in, BOM-prefixed
    # bytes out, and parse_file_bytes must strip that BOM back off on the way in.
    data = 'Hello world'.encode('utf-8-sig')
    assert server.parse_file_bytes('notes.txt', data) == 'Hello world'

    text = server.parse_file_bytes('notes.txt', 'plain ascii'.encode())
    assert text == 'plain ascii'


def test_parse_docx_extracts_paragraph_text():
    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph('Candidate summary line')
    doc.save(buf)
    text = server.parse_file_bytes('cv.docx', buf.getvalue())
    assert text == 'Candidate summary line'


def test_parse_malformed_pdf_raises_clean_400_and_logs(caplog):
    with caplog.at_level(logging.WARNING):
        with pytest.raises(HTTPException) as exc_info:
            server.parse_file_bytes('broken.pdf', b'not a real pdf')
    assert exc_info.value.status_code == 400
    assert any('Failed to parse PDF' in r.message for r in caplog.records)


def test_parse_malformed_docx_raises_clean_400_and_logs(caplog):
    with caplog.at_level(logging.WARNING):
        with pytest.raises(HTTPException) as exc_info:
            server.parse_file_bytes('broken.docx', b'not a real docx')
    assert exc_info.value.status_code == 400
    assert any('Failed to parse DOCX' in r.message for r in caplog.records)


def test_parse_legacy_doc_rejected_with_clear_message():
    with pytest.raises(HTTPException) as exc_info:
        server.parse_file_bytes('resume.doc', b'anything')
    assert exc_info.value.status_code == 400
    assert 'legacy .doc' in exc_info.value.detail
