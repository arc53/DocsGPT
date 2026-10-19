"""States from stored message rows, and the per-agent topic lists."""

import pytest

from docsgpt.analytics import schema, states, topics
from docsgpt.analytics.config import AnalyticsConfig


def _row(position, prompt, response="An answer.", status="complete", sources=None, metadata=None, **extra):
    return {"id": f"m{position}", "position": position, "prompt": prompt, "response": response, "status": status,
            "sources": sources or [], "metadata": metadata or {}, "tool_calls": [], **extra}


@pytest.mark.unit
class TestMessages:
    def test_the_literals_match_the_answer_code(self):
        from docsgpt.api.answer.services.compression import types
        from docsgpt.api.answer.services.conversation_service import TERMINATED_RESPONSE_PLACEHOLDER

        assert states.TERMINATED_RESPONSE_PLACEHOLDER == TERMINATED_RESPONSE_PLACEHOLDER
        assert states.COMPRESSION_SUMMARY_MARKER == types.COMPRESSION_SUMMARY_MARKER
        assert states.COMPRESSION_SUMMARY_PROMPT == types.COMPRESSION_SUMMARY_PROMPT

    def test_summary_unfinished_and_empty_rows_are_not_messages(self):
        rows = [
            _row(3, "third"),
            _row(0, "first"),
            _row(1, "[Context Compression Summary]", "summary", metadata={"compression_summary": True}),
            _row(2, "[Context Compression Summary]", "legacy summary"),
            _row(4, "streaming", status="streaming"),
            _row(5, "", "no prompt"),
            _row(6, "failed one", "", status="failed"),
        ]
        msgs = states.messages(rows)
        assert [m.id for m in msgs] == ["m0", "m3", "m6"]
        # a user who types the label as a question keeps the turn
        typed = _row(7, "[Context Compression Summary]", metadata={"request_id": "r"})
        assert [m.id for m in states.messages([typed])] == ["m7"]

    def test_turns_need_a_complete_real_answer(self):
        msgs = states.messages([
            _row(0, "a"), _row(1, "b", "  "), _row(2, "c", states.TERMINATED_RESPONSE_PLACEHOLDER),
            _row(3, "d", "partial", status="failed"),
        ])
        assert [m.is_turn for m in msgs] == [True, False, False, False]
        assert [m.answer for m in msgs] == ["An answer.", "", "", ""]


@pytest.mark.unit
class TestStates:
    def test_turn_history_is_the_two_messages_before_with_their_answers(self):
        msgs = states.messages([_row(0, "q0", "a0"), _row(1, "q1", "", status="failed"), _row(2, "q2", "a2"),
                                _row(3, "q3", "a3")])
        assert states.turn(msgs, 3)["history"] == "User: q1\nAssistant: \nUser: q2\nAssistant: a2"
        assert "history" not in states.turn(msgs, 0)

    def test_the_source_title_falls_back_to_source(self):
        sources = [{"title": "Install", "text": "pip install", "source": "x"},
                   {"title": "", "source": "guides/setup.md", "text": "run setup"},
                   {"source": None, "text": "untitled"}]
        state = states.turn(states.messages([_row(0, "how?", sources=sources)]), 0)
        assert state["sources"] == [{"title": "Install", "text": "pip install"},
                                    {"title": "guides/setup.md", "text": "run setup"},
                                    {"title": "", "text": "untitled"}]
        assert state == schema.turn_state("how?", "An answer.", [
            {"title": "Install", "text": "pip install"}, {"title": "guides/setup.md", "text": "run setup"},
            {"title": "", "text": "untitled"}], [])

    def test_the_context_string_is_exact(self):
        msgs = states.messages([_row(0, "How do I install it?", "Run the installer."), _row(1, "and on Windows?"),
                                _row(2, "thanks", "")])
        assert states.message(msgs, 1) == {"message": "and on Windows?",
                                           "context": "User: How do I install it?\nAssistant: Run the installer."}
        assert states.message(msgs, 0) == {"message": "How do I install it?"}
        assert states.topic(msgs, 1) == {"message": "and on Windows?"}

    def test_the_reaction_pairs_an_answer_with_the_next_message(self):
        msgs = states.messages([_row(0, "q0", "a0"), _row(1, "q1", "", status="failed"), _row(2, "q2")])
        assert states.reaction(msgs, 1) == {"answer": "a0", "question": "q0", "reply": "q1"}
        assert states.reaction(msgs, 2) is None  # the message before has no answer
        assert states.reaction(msgs, 0) is None

    def test_the_conversation_state(self):
        msgs = states.messages([_row(0, "q0", "a0"), _row(1, "q1", "", status="failed")])
        assert states.conversation(msgs) == {"opening": "q0",
                                             "transcript": "User: q0\nAssistant: a0\nUser: q1\nAssistant:"}

    def test_retrieval_relevance_is_the_best_stored_score(self):
        msgs = states.messages([_row(0, "q", sources=[{"relevance": 0.2}, {"relevance": 0.7}, {"relevance": True}]),
                                _row(1, "q", sources=[{"text": "t"}])])
        assert states.retrieval_relevance(msgs[0]) == 0.7
        assert states.retrieval_relevance(msgs[1]) is None

    @pytest.mark.parametrize(
        "text, lang",
        [("How do I reset it?", "en"), ("¿Cómo puedo cambiar la contraseña?", "es"), ("如何重置密码", "zh"),
         ("Как сбросить пароль?", "ru"), ("パスワードをリセット", "ja"), ("비밀번호 재설정", "ko"),
         ("Comment changer le mot de passe ?", "fr"), ("Wie kann ich das Passwort ändern?", "de"),
         ("Como faço para mudar a senha?", "pt"), ("Come posso cambiare la password?", "it"),
         ("東京の会社で使えますか", "ja"), ("Is the API rate limit per user or per workspace?", "en"),
         ("Where is the Docker port set?", "en")],
    )
    def test_lang(self, text, lang):
        assert states.lang(text) == lang


def _file(tokens=10):
    return {"type": "text/markdown", "size_bytes": 1, "token_count": tokens}


@pytest.mark.unit
class TestAutoTopics:
    def test_sections_skip_folders_and_root_files_go_to_overview(self):
        structure = {"docs": {"getting-started": {"01-install.md": _file(), "upgrade_guide.md": _file()},
                              "en": {"API_reference": {"auth.md": _file()}}},
                     "README.md": _file()}
        assert topics.auto_topics([{"name": "S", "directory_structure": structure}], 15) == {
            "api reference": "Pages such as: Auth",
            "getting started": "Pages such as: Install; Upgrade guide",
            "overview": "Pages such as: Readme",
        }

    def test_the_rule_is_arc_decides(self):
        import json
        from pathlib import Path

        golden = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "analytics_schema.json")
                            .read_text(encoding="utf-8"))
        for path, section, title in golden["sections"]:
            assert (topics.section(path), topics.page_title(path)) == (section, title), path

    def test_five_titles_are_sampled_with_a_fixed_seed(self):
        structure = {"guides": {f"page-{i:02d}.md": _file() for i in range(12)}, "faq": {"a.md": _file()}}
        first = topics.auto_topics([{"name": "S", "directory_structure": structure}], 15)
        again = topics.auto_topics([{"name": "S", "directory_structure": structure}], 15)
        assert first == again
        titles = first["guides"].removeprefix("Pages such as: ").split("; ")
        assert len(titles) == 5 and titles == sorted(titles)

    def test_descriptions_are_capped_at_150_units(self):
        structure = {"guides": {f"{'x' * 60}{i}.md": _file() for i in range(5)}, "faq": {"a.md": _file()}}
        description = topics.auto_topics([{"name": "S", "directory_structure": structure}], 15)["guides"]
        assert schema.units(description) <= 150 and description.endswith("…")

    def test_more_sections_than_the_cap_keep_the_largest(self):
        structure = {f"section{i:02d}": {"page.md": _file(tokens=i)} for i in range(20)}
        kept = topics.auto_topics([{"name": "S", "directory_structure": structure}], 15)
        assert list(kept) == sorted(f"section{i:02d}" for i in range(5, 20))

    def test_flat_sources_of_a_multi_source_agent_are_one_section_each(self):
        flat_a = {"name": "Product Docs", "directory_structure": {"intro.md": _file(), "setup.md": _file()}}
        flat_b = {"name": "API", "directory_structure": '{"auth.md": {"token_count": 3}}'}
        assert topics.auto_topics([flat_a, flat_b], 15) == {"api": "Pages such as: Auth",
                                                            "product docs": "Pages such as: Intro; Setup"}

    def test_fewer_than_two_sections_ask_no_topic(self):
        assert topics.auto_topics([{"name": "S", "directory_structure": {"a.md": _file()}}], 15) == {}
        assert topics.auto_topics([{"name": "S", "directory_structure": None}], 15) == {}

    def test_modes(self, monkeypatch):
        monkeypatch.setattr(topics, "agent_sources", lambda conn, agent: [{"name": "S", "directory_structure": {
            "a": {"x.md": _file()}, "b": {"y.md": _file()}}}])
        agent = {"id": "a1"}
        assert topics.options(None, agent, AnalyticsConfig()) == {"a": "Pages such as: X", "b": "Pages such as: Y"}
        off = AnalyticsConfig.model_validate({"topics": {"mode": "off"}})
        assert topics.options(None, agent, off) == {}
        custom = AnalyticsConfig.model_validate({"topics": {"mode": "custom", "items": [
            {"name": "Pricing"}, {"name": "auth", "description": "Logging in"}]}})
        assert topics.options(None, agent, custom) == {"auth": "Logging in", "Pricing": None}
        assert topics.options(None, None, AnalyticsConfig()) == {}

    def test_options_hash_follows_order_and_text(self):
        assert topics.options_hash({"a": "x", "b": "y"}) == topics.options_hash({"a": "x", "b": "y"})
        assert topics.options_hash({"a": "x", "b": "y"}) != topics.options_hash({"b": "y", "a": "x"})
        assert len(topics.options_hash(["Tag", "Description"])) == 12


@pytest.mark.unit
class TestEffectiveTopic:
    A = {"install": 0.9, "auth": 0.1}
    B = {"install": 0.2, "auth": 0.8}

    def test_a_follow_up_takes_its_openers_topic_in_proportion(self):
        out = topics.effective_topics([(self.A, "h", None), (self.B, "h", {"follow-up": 0.6, "new question": 0.4})])
        assert out[0] == self.A
        assert out[1] == pytest.approx({"install": 0.6 * 0.9 + 0.4 * 0.2, "auth": 0.6 * 0.1 + 0.4 * 0.8})

    def test_a_new_question_is_its_own_opener(self):
        out = topics.effective_topics([
            (self.A, "h", None), (self.B, "h", {"new question": 0.9, "re-ask": 0.1}), (self.A, "h", {"re-ask": 1.0}),
        ])
        assert out[1] == self.B
        assert out[2] == pytest.approx(self.B)

    def test_no_topic_or_other_options_keep_their_own(self):
        out = topics.effective_topics([(None, None, None), (self.B, "h", {"follow-up": 1.0})])
        assert out == [None, self.B]
        out = topics.effective_topics([(self.A, "old", None), (self.B, "h", {"follow-up": 1.0})])
        assert out[1] == self.B
