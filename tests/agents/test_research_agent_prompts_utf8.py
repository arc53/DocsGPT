"""``_load_prompt`` must read the research prompt files as UTF-8.

The prompts under ``docsgpt/prompts/research/`` are UTF-8 and some carry
non-ASCII characters. ``_load_prompt`` used to open them without an explicit
``encoding``, so on a machine whose default encoding is not UTF-8 (GBK on
Chinese Windows) it crashed at import time with ``UnicodeDecodeError`` or
silently decoded the prompts into mojibake. The fix passes
``encoding="utf-8"``.

These tests simulate a GBK machine on any platform (Linux CI included) by
wrapping ``builtins.open``: a text-mode call without an explicit
``encoding`` is forced to GBK before delegating to the real ``open``. A
control assertion proves the simulation genuinely breaks an encoding-less
read of the fixture file, so the test turns red if the
``encoding="utf-8"`` argument is ever dropped.
"""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest

import docsgpt.agents.research_agent as research_agent

# The last line ends with a CJK character: its 3 UTF-8 bytes are
# [lead, trail, low], where the leading pair decodes as one GBK character and
# the low trailing byte pairs with the newline (0x0A), which is not a legal
# GBK trail byte. An encoding-less read on a GBK machine is therefore
# guaranteed to raise UnicodeDecodeError rather than quietly mojibake.
PROMPT_TEXT = "You are the research agent.\nStep query: {step_query}\n请严格按照以下规范回答。\n"


def _force_gbk_default_open(monkeypatch):
    """Make a text-mode ``open`` without an explicit encoding use GBK.

    This stands in for a machine whose default encoding is GBK (e.g. Chinese
    Windows), independently of the real locale, so the tests are stable on
    every platform.

    Args:
        monkeypatch: pytest monkeypatch fixture.
    """
    real_open = builtins.open

    def gbk_default_open(file, mode="r", buffering=-1, encoding=None, *args, **kwargs):
        if encoding is None and "b" not in mode:
            encoding = "gbk"
        return real_open(file, mode, buffering, encoding, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", gbk_default_open)


@pytest.mark.unit
class TestLoadPromptUtf8:
    def test_loads_the_prompt_verbatim_on_a_gbk_default_machine(self, tmp_path, monkeypatch):
        """``_load_prompt`` returns the exact text written, GBK default or not.

        The prompt file is UTF-8 with a line ending in a CJK character, and
        ``_PROMPTS_DIR`` is pointed at it, so the real ``_load_prompt`` runs
        against a file an encoding-less read cannot decode on the simulated
        machine.
        """
        prompt_file = tmp_path / "step.txt"
        prompt_file.write_text(PROMPT_TEXT, encoding="utf-8")
        _force_gbk_default_open(monkeypatch)

        # Control: on the simulated machine, reading this file without an
        # encoding cannot succeed. Without this, the assertion below could
        # stay green with ``encoding="utf-8"`` removed if the file happened
        # to decode under GBK.
        with pytest.raises(UnicodeDecodeError):
            with open(prompt_file, "r") as fh:
                fh.read()

        monkeypatch.setattr(research_agent, "_PROMPTS_DIR", str(tmp_path))

        assert research_agent._load_prompt("step.txt") == PROMPT_TEXT

    def test_shipped_prompts_load_verbatim_on_a_gbk_machine(self, monkeypatch):
        """The real shipped prompt files survive the simulated GBK machine.

        Two of the four files (planning, step) carry non-ASCII characters, so
        without the explicit UTF-8 they come back as an exception or mojibake.
        """
        _force_gbk_default_open(monkeypatch)

        for name in ("clarification.txt", "planning.txt", "step.txt", "synthesis.txt"):
            expected = Path(research_agent._PROMPTS_DIR, name).read_text(encoding="utf-8")
            assert research_agent._load_prompt(name) == expected, name
