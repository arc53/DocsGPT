"""Tests for the README translation script (.github/readme/translate.py)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / ".github" / "readme" / "translate.py"
_spec = importlib.util.spec_from_file_location("readme_translate", SCRIPT_PATH)
translate = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = translate
_spec.loader.exec_module(translate)

SHA_OLD = "a" * 40
SHA_NEW = "b" * 40

SOURCE = """<h1 align="center">DocsGPT</h1>

<!-- languages:start -->
old bar
<!-- languages:end -->

See [the guide](CONTRIBUTING.md) and <img src="docs/public/poster.png" alt="Poster">.

## Install

> ```bash
> curl -fsSL https://docs.ac/install | bash
> ```

Visit [the site](https://docs.docsgpt.cloud/) or [jump](#install) or [mail](mailto:hi@example.com).
"""

TRANSLATION = """<h1 align="center">DocsGPT</h1>

<!-- languages -->

Siehe [die Anleitung](CONTRIBUTING.md) und <img src="docs/public/poster.png" alt="Poster">.

## Installieren

> ```bash
> curl -fsSL https://docs.ac/install | bash
> ```

Besuche [die Seite](https://docs.docsgpt.cloud/) oder [springe](#install) oder [Mail](mailto:hi@example.com).
"""


class TestLanguageBar:
    def test_readme_bar_links_every_translation_and_marks_english(self):
        bar = translate.language_bar("en")
        assert bar.startswith(translate.BAR_START) and bar.endswith(translate.BAR_END)
        assert "<strong>English</strong>" in bar
        for code in translate.LANGUAGES:
            assert f'href=".github/readme/README.{code}.md"' in bar

    def test_translation_bar_links_back_to_the_readme_and_its_siblings(self):
        bar = translate.language_bar("de")
        assert 'href="../../README.md">English</a>' in bar
        assert f"<strong>{translate.LANGUAGES['de'].label}</strong>" in bar
        assert 'href="README.ja.md"' in bar
        assert "README.de.md" not in bar

    def test_strip_bar_leaves_a_placeholder(self):
        stripped = translate.strip_bar(SOURCE)
        assert "old bar" not in stripped
        assert stripped.count(translate.PLACEHOLDER) == 1

    def test_insert_bar_replaces_the_placeholder(self):
        filled = translate.insert_bar(TRANSLATION, "de")
        assert translate.PLACEHOLDER not in filled
        assert translate.language_bar("de") in filled

    def test_set_readme_bar_rewrites_only_the_bar(self):
        updated = translate.set_readme_bar(SOURCE)
        assert "old bar" not in updated
        assert translate.language_bar("en") in updated
        assert updated.replace(translate.language_bar("en"), "") == SOURCE.replace(
            f"{translate.BAR_START}\nold bar\n{translate.BAR_END}", ""
        )


class TestLinks:
    def test_relative_targets_get_the_prefix(self):
        out = translate.rewrite_links(TRANSLATION)
        assert "](../../CONTRIBUTING.md)" in out
        assert 'src="../../docs/public/poster.png"' in out

    def test_absolute_anchor_and_mail_targets_are_left_alone(self):
        out = translate.rewrite_links(TRANSLATION)
        assert "](https://docs.docsgpt.cloud/)" in out
        assert "](#install)" in out
        assert "](mailto:hi@example.com)" in out

    def test_code_blocks_are_left_alone(self):
        text = "```md\n[a](CONTRIBUTING.md)\n```\n[b](LICENSE)\n"
        assert translate.rewrite_links(text) == "```md\n[a](CONTRIBUTING.md)\n```\n[b](../../LICENSE)\n"

    def test_unrewrite_reverses_rewrite(self):
        assert translate.unrewrite_links(translate.rewrite_links(TRANSLATION)) == TRANSLATION

    def test_relative_targets_lists_only_local_paths(self):
        assert translate.relative_targets(SOURCE) == ["CONTRIBUTING.md", "docs/public/poster.png"]


class TestEmphasis:
    """CommonMark does not close ``**`` between punctuation and a letter, which CJK text hits often."""

    def test_punctuation_moves_outside_a_closing_marker_before_a_letter(self):
        assert translate.fix_emphasis("- **安全护栏：**标记 PII") == "- **安全护栏**：标记 PII"
        assert translate.fix_emphasis("> **Hacktoberfest 2026：**整个十月") == "> **Hacktoberfest 2026**：整个十月"

    def test_rendering_markers_are_left_alone(self):
        for text in ["**Agents:** text", "**エージェント：** 独自", "**Agents**: text", "a **b** c：**d**"]:
            assert translate.fix_emphasis(text) == text

    def test_code_blocks_are_left_alone(self):
        text = "```\n**x：**y\n```\n"
        assert translate.fix_emphasis(text) == text

    def test_render_applies_it(self):
        assert "**安装**：运行" in translate.render("zh-CN", "**安装：**运行\n", SHA_NEW)


class TestMarker:
    def test_round_trip(self):
        marked = translate.with_marker("body\n", SHA_NEW)
        assert marked.endswith("body\n")
        assert translate.parse_marker(marked) == SHA_NEW
        assert translate.strip_marker(marked) == "body\n"

    def test_missing_marker(self):
        assert translate.parse_marker("no marker here") is None
        assert translate.strip_marker("no marker here") == "no marker here"


class TestValidate:
    def test_faithful_translation_passes(self):
        assert translate.validate(translate.strip_bar(SOURCE), TRANSLATION) == []

    def test_missing_placeholder(self):
        errors = translate.validate(translate.strip_bar(SOURCE), TRANSLATION.replace(translate.PLACEHOLDER, ""))
        assert any("placeholder" in error for error in errors)

    def test_changed_url(self):
        broken = TRANSLATION.replace("https://docs.docsgpt.cloud/", "https://docs.docsgpt.de/")
        errors = translate.validate(translate.strip_bar(SOURCE), broken)
        assert any("https://docs.docsgpt.cloud/" in error for error in errors)

    def test_dropped_code_fence(self):
        broken = TRANSLATION.replace("> ```\n", "", 1)
        assert any("code fence" in error for error in translate.validate(translate.strip_bar(SOURCE), broken))

    def test_dropped_heading(self):
        broken = TRANSLATION.replace("## Installieren", "Installieren")
        assert any("heading" in error for error in translate.validate(translate.strip_bar(SOURCE), broken))

    def test_changed_relative_link(self):
        broken = TRANSLATION.replace("](CONTRIBUTING.md)", "](CONTRIBUTING.de.md)")
        assert any("CONTRIBUTING.md" in error for error in translate.validate(translate.strip_bar(SOURCE), broken))


class TestParseReply:
    def test_plain_json_gets_a_trailing_newline(self):
        assert translate.parse_reply(json.dumps({"markdown": "x", "notes": " n "})) == ("x\n", "n")

    def test_fenced_json(self):
        assert translate.parse_reply('```json\n{"markdown": "x"}\n```') == ("x\n", "")

    @pytest.mark.parametrize("content", ["not json", "[]", '{"notes": "no markdown"}', '{"markdown": ""}'])
    def test_rejects_bad_replies(self, content):
        with pytest.raises(translate.TranslationError):
            translate.parse_reply(content)


class _Agent:
    """Records each message and answers with the queued replies in order."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.messages: list[str] = []

    def __call__(self, message: str) -> str:
        self.messages.append(message)
        return self.replies.pop(0)


def _reply(markdown: str, notes: str = "") -> str:
    return json.dumps({"markdown": markdown, "notes": notes})


class TestTranslateLanguage:
    def test_new_language_gets_a_full_translation(self):
        agent = _Agent(_reply(TRANSLATION, "Kept 'agent' in English."))
        result = translate.translate_language("de", SOURCE, SHA_NEW, None, lambda sha: None, agent)
        assert result.changed
        assert result.notes == "Kept 'agent' in English."
        assert translate.parse_marker(result.text) == SHA_NEW
        assert "](../../CONTRIBUTING.md)" in result.text
        assert translate.language_bar("de") in result.text
        assert "Mode: full" in agent.messages[0]
        assert "German" in agent.messages[0]

    def test_up_to_date_translation_is_not_sent(self):
        current = translate.render("de", TRANSLATION, SHA_NEW)
        agent = _Agent()
        result = translate.translate_language("de", SOURCE, SHA_NEW, current, lambda sha: None, agent)
        assert not result.changed
        assert agent.messages == []

    def test_bar_only_change_moves_the_marker_without_calling_the_agent(self):
        current = translate.render("de", TRANSLATION, SHA_OLD)
        old_source = SOURCE.replace("old bar", "older bar")
        agent = _Agent()
        result = translate.translate_language("de", SOURCE, SHA_NEW, current, {SHA_OLD: old_source}.get, agent)
        assert result.changed
        assert agent.messages == []
        assert translate.parse_marker(result.text) == SHA_NEW

    def test_changed_source_sends_the_diff_and_current_translation(self):
        current = translate.render("de", TRANSLATION, SHA_OLD)
        old_source = SOURCE.replace("## Install", "## Setup")
        agent = _Agent(_reply(TRANSLATION))
        result = translate.translate_language("de", SOURCE, SHA_NEW, current, {SHA_OLD: old_source}.get, agent)
        message = agent.messages[0]
        assert "Mode: update" in message
        assert "-## Setup" in message and "+## Install" in message
        assert "Siehe [die Anleitung](CONTRIBUTING.md)" in message  # links un-rewritten for the agent
        assert "../../" not in message
        assert translate.parse_marker(result.text) == SHA_NEW

    def test_unknown_marker_falls_back_to_a_full_translation(self):
        current = translate.render("de", TRANSLATION, SHA_OLD)
        agent = _Agent(_reply(TRANSLATION))
        translate.translate_language("de", SOURCE, SHA_NEW, current, lambda sha: None, agent)
        assert "Mode: full" in agent.messages[0]

    def test_full_mode_retranslates_an_up_to_date_file(self):
        current = translate.render("de", TRANSLATION, SHA_NEW)
        agent = _Agent(_reply(TRANSLATION))
        translate.translate_language("de", SOURCE, SHA_NEW, current, lambda sha: None, agent, full=True)
        assert "Mode: full" in agent.messages[0]

    def test_invalid_reply_is_retried_with_the_problems(self):
        agent = _Agent(_reply(TRANSLATION.replace(translate.PLACEHOLDER, "")), _reply(TRANSLATION))
        result = translate.translate_language("de", SOURCE, SHA_NEW, None, lambda sha: None, agent)
        assert result.changed
        assert len(agent.messages) == 2
        assert "placeholder" in agent.messages[1]

    def test_gives_up_after_the_retry(self):
        bad = _reply(TRANSLATION.replace(translate.PLACEHOLDER, ""))
        agent = _Agent(bad, bad)
        with pytest.raises(translate.TranslationError):
            translate.translate_language("de", SOURCE, SHA_NEW, None, lambda sha: None, agent)


class TestRepoLayout:
    def test_readme_bar_is_current(self):
        readme = (SCRIPT_PATH.parents[2] / "README.md").read_text(encoding="utf-8")
        assert translate.language_bar("en") in readme

    def test_rewritten_readme_links_resolve_from_the_translation_folder(self):
        repo = SCRIPT_PATH.parents[2]
        readme = (repo / "README.md").read_text(encoding="utf-8")
        folder = repo / ".github" / "readme"
        for target in translate.relative_targets(translate.rewrite_links(translate.strip_bar(readme))):
            assert (folder / target.split("#")[0]).resolve().exists(), target


class TestMakeAgent:
    def test_sends_the_key_and_its_own_user_agent(self, monkeypatch):
        sent = {}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "answer"}}]}).encode()

        def fake_urlopen(request, timeout):
            sent["url"] = request.full_url
            sent["headers"] = dict(request.header_items())
            sent["body"] = json.loads(request.data)
            return _Response()

        monkeypatch.setattr(translate.urllib.request, "urlopen", fake_urlopen)
        assert translate.make_agent("https://cloud.example/", "key-1")("hello") == "answer"
        assert sent["url"] == "https://cloud.example/v1/chat/completions"
        assert sent["headers"]["Authorization"] == "Bearer key-1"
        # The cloud's firewall answers 403 to urllib's default User-Agent.
        assert not sent["headers"]["User-agent"].startswith("Python-urllib")
        assert sent["body"]["messages"] == [{"role": "user", "content": "hello"}]

    def test_missing_key(self):
        with pytest.raises(translate.TranslationError, match=translate.KEY_ENV):
            translate.make_agent("https://cloud.example", None)("hello")
