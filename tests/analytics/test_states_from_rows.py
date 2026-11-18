"""States from stored message rows, and the per-agent topic lists."""

import pytest

from docsgpt.analytics import schema, states, topics
from docsgpt.analytics.config import TOPIC_NAME_CHARS, AnalyticsConfig


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

    def test_a_legacy_summary_label_with_tool_calls_is_a_message_as_the_sweep_loads_it(self):
        # ``source_messages`` loads ``has_tool_calls`` in place of the calls themselves
        label = "[Context Compression Summary]"
        rows = [{"id": "m0", "position": 0, "prompt": label, "response": "a", "status": "complete",
                 "message_metadata": {}, "sources": [], "has_tool_calls": called} for called in (True, False)]
        assert [len(states.messages([row])) for row in rows] == [1, 0]

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


def _folders(sources) -> dict:
    return {f["name"]: f["description"] for f in topics.folders(sources)}


def _source(structure) -> list[dict]:
    return [{"name": "S", "directory_structure": structure}]


@pytest.mark.unit
class TestFolders:
    def test_sections_skip_folders_and_root_files_go_to_overview(self):
        structure = {"docs": {"getting-started": {"01-install.md": _file(), "upgrade_guide.md": _file()},
                              "en": {"API_reference": {"auth.md": _file()}}},
                     "README.md": _file()}
        assert _folders(_source(structure)) == {
            "getting started": "Pages such as: Install; Upgrade guide",
            "api reference": "Pages such as: Auth",
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
        first = _folders(_source(structure))
        assert first == _folders(_source(structure))
        titles = first["guides"].removeprefix("Pages such as: ").split("; ")
        assert len(titles) == 5 and titles == sorted(titles)

    def test_descriptions_are_capped_at_150_units(self):
        structure = {"guides": {f"{'x' * 60}{i}.md": _file() for i in range(5)}, "faq": {"a.md": _file()}}
        description = _folders(_source(structure))["guides"]
        assert schema.units(description) <= 150 and description.endswith("…")

    def test_largest_first_and_capped(self):
        structure = {f"section{i:02d}": {"page.md": _file(tokens=i)} for i in range(60)}
        listed = [f["name"] for f in topics.folders(_source(structure))]
        assert listed == [f"section{i:02d}" for i in range(59, 9, -1)]

    def test_flat_sources_of_a_multi_source_agent_are_one_section_each(self):
        flat_a = {"name": "Product Docs", "directory_structure": {"intro.md": _file(), "setup.md": _file()}}
        flat_b = {"name": "API", "directory_structure": '{"auth.md": {"token_count": 3}}'}
        assert _folders([flat_a, flat_b]) == {"product docs": "Pages such as: Intro; Setup",
                                             "api": "Pages such as: Auth"}

    def test_a_long_source_name_is_cut_to_fit_a_topic_name(self):
        long_name = "Q3-2025 Vendor Due Diligence Questionnaire - Halvorsen Logistics (final, signed).pdf"
        flat = {"name": long_name, "directory_structure": {"questionnaire.pdf": _file()}}
        other = {"name": "Handbook", "directory_structure": {"intro.md": _file()}}
        names = [f["name"] for f in topics.folders([flat, other])]
        cut = next(name for name in names if name != "handbook")
        assert len(cut) <= TOPIC_NAME_CHARS and cut.endswith("…")
        # Cut on a word boundary, never mid-word.
        assert cut == "q3-2025 vendor due diligence questionnaire - halvorsen…"
        AnalyticsConfig.model_validate({"hidden_folders": names, "topics": [
            {"id": "topic0001", "name": cut}]})

    def test_a_long_folder_name_is_cut_too(self):
        structure = {"a" * 80: {"x.md": _file()}, "faq": {"q.md": _file()}}
        names = [f["name"] for f in topics.folders(_source(structure))]
        assert names[0] == "a" * (TOPIC_NAME_CHARS - 1) + "…" and len(names[0]) == TOPIC_NAME_CHARS

    def test_cut_names_stay_unique_whatever_the_order(self):
        stem = "vendor due diligence questionnaire for halvorsen logistics and partners"
        a = {"name": f"{stem} part one", "directory_structure": {"a.md": _file()}}
        b = {"name": f"{stem} part two", "directory_structure": {"b.md": _file()}}
        c = {"name": "Handbook", "directory_structure": {"c.md": _file()}}
        first = _folders([a, b, c])
        assert first == _folders([c, b, a])
        assert len(first) == 3 and all(len(name) <= TOPIC_NAME_CHARS for name in first)
        assert first["vendor due diligence questionnaire for halvorsen logistics…"] == "Pages such as: A"
        assert first["vendor due diligence questionnaire for halvorsen… 2"] == "Pages such as: B"

    def test_a_single_folder_is_still_listed(self):
        assert _folders(_source({"a.md": _file()})) == {"overview": "Pages such as: A"}
        assert topics.folders(_source(None)) == []


@pytest.mark.unit
class TestOptions:
    FOLDERS = [{"name": n, "description": f"Pages such as: {n}"} for n in ("big", "mid", "small", "tiny")]

    def _merge(self, own=(), hidden=(), max_topics=15):
        return topics.merge(list(own), self.FOLDERS, list(hidden), max_topics)

    def test_folders_alone(self):
        assert self._merge() == {f["name"]: f["description"] for f in self.FOLDERS}

    def test_own_topics_come_first_and_folders_fill_what_is_left_largest_first(self):
        own = [("Pricing", None), ("auth", "Logging in")]
        assert self._merge(own, max_topics=4) == {"auth": "Logging in", "big": "Pages such as: big",
                                                  "mid": "Pages such as: mid", "Pricing": None}

    def test_hidden_and_clashing_folders_are_skipped(self):
        assert list(self._merge([("Big", "Mine")], hidden=["MID"])) == ["Big", "small", "tiny"]

    def test_fewer_than_two_options_ask_nothing(self):
        assert self._merge(hidden=["big", "mid", "small"]) == {}
        assert self._merge([("Only", None)], hidden=["big", "mid", "small", "tiny"]) == {}
        assert self._merge([("Only", None)], hidden=["big", "mid", "small"]) == {"Only": None,
                                                                                "tiny": "Pages such as: tiny"}

    def test_options_reads_the_agent(self, monkeypatch):
        monkeypatch.setattr(topics, "agent_sources", lambda conn, agent: [{"name": "S", "directory_structure": {
            "a": {"x.md": _file()}, "b": {"y.md": _file()}}}])
        agent = {"id": "a1"}
        assert topics.options(None, agent, AnalyticsConfig()) == {"a": "Pages such as: X", "b": "Pages such as: Y"}
        config = AnalyticsConfig.model_validate({"hidden_folders": ["a"], "topics": [
            {"id": "topic0001", "name": "Pricing"},
            {"id": "topic0002", "name": "Bug report", "overlap": True}]})
        assert topics.options(None, agent, config) == {"b": "Pages such as: Y", "Pricing": None}
        assert topics.options(None, None, AnalyticsConfig()) == {}

    def test_a_workflow_offers_its_own_topics(self, monkeypatch):
        monkeypatch.setattr(topics, "agent_sources", lambda conn, agent: [])
        config = AnalyticsConfig.model_validate({"topics": [
            {"id": "topic0001", "name": "Pricing"}, {"id": "topic0002", "name": "Setup", "description": "Install"}]})
        assert topics.options(None, {"id": "w1"}, config) == {"Pricing": None, "Setup": "Install"}

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
