"""Optional live Docling extraction test, SKIPPED unless RUN_DOCLING_LIVE=1.

Default CI/dev runs never import docling (which pulls torch + models), so this is
skipped unless explicitly opted in. It runs the FIXED extraction program in-process
against a tiny generated PDF and asserts the compact result shape, exercising the
exact program string the tool ships to the sandbox.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from application.agents.tools.document_extractor import _EXTRACT_PROGRAM

RUN_LIVE = os.environ.get("RUN_DOCLING_LIVE") == "1"

pytestmark = pytest.mark.skipif(not RUN_LIVE, reason="set RUN_DOCLING_LIVE=1 to run live Docling extraction")


def _make_pdf(path: str) -> None:
    """Write a one-line PDF using reportlab (kept out of the import path unless live)."""
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(path)
    c.drawString(72, 720, "Compliance balance: 1000")
    c.showPage()
    c.save()


def test_live_docling_extracts_pdf():
    pytest.importorskip("docling")
    pytest.importorskip("reportlab")

    workdir = tempfile.mkdtemp()
    input_path = os.path.join(workdir, "inputs", "doc.pdf")
    os.makedirs(os.path.dirname(input_path), exist_ok=True)
    _make_pdf(input_path)

    params_path = os.path.join(workdir, "params.json")
    result_path = os.path.join(workdir, "result.json")
    with open(params_path, "w") as fh:
        json.dump({"input_path": input_path, "markdown_max_bytes": 8000, "max_tables": 20}, fh)

    program = _EXTRACT_PROGRAM.format(params_path=params_path, result_path=result_path)
    namespace: dict = {}
    exec(compile(program, "<extractor>", "exec"), namespace, namespace)  # noqa: S102

    with open(result_path) as fh:
        result = json.load(fh)
    assert result.get("ok") is True, result
    assert "balance" in result["markdown"].lower()
    assert isinstance(result["structured"], dict)
