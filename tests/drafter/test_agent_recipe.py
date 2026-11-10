"""The agent recipe: its instructions, and the server-side check of an agent proposal."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from docsgpt.drafter import agent_recipe
from docsgpt.drafter.agent_recipe import (
    AGENT_RECIPE,
    AgentWorkspace,
    context_data,
    guardrail_menu,
    instructions,
    NAME_MAX,
    parse_context,
    validate,
)
from docsgpt.drafter.catalog import Workspace
from docsgpt.drafter.recipe import BadDraftRequest, DraftRequest, ProposalInvalid
from docsgpt.drafter.runner import build_messages
from tests.drafter.fakes import QUESTIONS

TOOL_ID = "11111111-1111-1111-1111-111111111111"
SOURCE_ID = "22222222-2222-2222-2222-222222222222"
PROMPT_ID = "33333333-3333-3333-3333-333333333333"
MENU = ["pii", "injection", "groundedness", "secrets"]
FOLDERS = [{"name": n, "description": f"Pages such as: {n}"}
           for n in ("deploying", "overview", "sources", "extensions", "tools", "agents")]


def _ws(**kwargs) -> AgentWorkspace:
    ws = AgentWorkspace(
        sources=[{"id": SOURCE_ID, "name": "Help Center"}],
        tools=[{"id": TOOL_ID, "name": "Tracking", "kind": "api_tool", "actions": []}],
        prompts=[{"id": p, "name": p, "kind": "built-in"} for p in ("default", "creative", "strict")]
        + [{"id": PROMPT_ID, "name": "Support", "kind": "own"}],
        prompt_texts={"default": "You are DocsGPT {{ system.date }}", PROMPT_ID: "You help customers."},
        guardrail_menu=list(MENU),
        insights=True,
        max_topics=15,
    )
    for key, value in kwargs.items():
        setattr(ws, key, value)
    return ws


def _on(check: str, stage: str) -> dict:
    """A control the form runs, as the context sends it."""
    return {"check": check, "stage": stage}


def _added(*checks: str) -> dict:
    """The guardrails field a proposal adding these menu checks carries: every control of each."""
    return {"controls": [{"check": check, "stage": stage, "action": action}
                         for check in checks for stage, action in agent_recipe.GUARDRAIL_MENU[check]]}


class _OneConn:
    """Counts the read-only transactions a load opens; each yields the same stand-in connection."""

    def __init__(self) -> None:
        self.conn = object()
        self.opened = 0


@pytest.fixture
def one_conn():
    from contextlib import contextmanager

    tracker = _OneConn()

    @contextmanager
    def _readonly():
        tracker.opened += 1
        yield tracker.conn

    with patch("docsgpt.storage.db.session.db_readonly", _readonly), patch.object(agent_recipe, "load_models"):
        yield tracker


def _req(form=None, *user_messages, step=None, earlier=None, asked=False) -> DraftRequest:
    messages = [{"role": "user", "content": m} for m in (user_messages or ("Build me a support agent",))]
    if asked:
        messages = [messages[0], {"role": "assistant", "content": json.dumps(QUESTIONS)},
                    {"role": "user", "content": "Recommended limits, PII, yes to the topics"}]
    context = parse_context({"form": form or {}, "step": step, "earlier": earlier or []})
    return DraftRequest("alice", "agent", messages, context, "drafter:t")


def _validate(fields, form=None, ws=None, messages=(), step=None, asked=False, **extra):
    args = {"message": "Done.", "fields": fields, **extra}
    return validate(args, _req(form, *messages, step=step, asked=asked), ws or _ws())


@pytest.mark.unit
class TestContext:
    def test_values_are_cleaned_and_capped(self):
        ctx = parse_context({
            "agent_id": " a1 ",
            "step": "knowledge",
            "earlier": ["Build a help desk", "", 5] + ["x" * 2500] + [f"m{i}" for i in range(20)],
            "form": {"name": "N\x00ame", "sources": ["s1", "s1", 3, ""], "tools": "nope",
                     "prompt_id": "strict", "prompt_draft": {"name": "P", "content": "x"},
                     "pending_prompt": {"name": "Old", "content": "y"},
                     "starters": ["Hi", "", 5], "models": ["gpt"]},
        })
        assert ctx["agent_id"] == "a1" and ctx["step"] == "knowledge"
        assert len(ctx["earlier"]) == 12 and ctx["earlier"][0] == "Build a help desk"
        assert len(ctx["earlier"][1]) <= 2000
        form = ctx["form"]
        assert form["name"] == "Name" and form["sources"] == ["s1"] and form["tools"] == []
        assert form["prompt_draft"] == {"name": "P", "content": "x"} and form["starters"] == ["Hi"]
        assert "models" not in form and "pending_prompt" not in form

    def test_policy_values_get_defaults_and_wrong_values_are_left_out(self):
        form = parse_context({"form": {}})["form"]
        assert form["limits"] == {"mode": "none", "value": None}
        assert form["guardrails"] == {"enabled": False, "mode": "monitor_only", "controls": []}
        assert form["analytics"] == {"enabled": True, "topics": [], "overlapping": [], "hidden_folders": []}
        form = parse_context({"form": {
            "limits": {"mode": "tokens", "value": 50000},
            "guardrails": {"enabled": True, "mode": "scan_all", "controls": [
                {"check": "PII", "stage": "input"}, {"check": "pii", "stage": "input"}, {"check": "pii"}, 3,
            ]},
            "analytics": {"enabled": False, "topics": ["Billing", "", 4]},
        }})["form"]
        assert form["limits"] == {"mode": "tokens", "value": 50000}
        assert form["guardrails"] == {"enabled": True, "mode": "scan_all", "controls": [_on("pii", "input")]}
        assert form["analytics"] == {"enabled": False, "topics": ["Billing"], "overlapping": [], "hidden_folders": []}
        form = parse_context({"form": {"limits": {"mode": "forever", "value": True}}})["form"]
        assert form["limits"] == {"mode": "none", "value": None}

    def test_an_older_clients_checks_count_as_on_at_every_menu_stage(self):
        guardrails = parse_context({"form": {"guardrails": {"enabled": True, "checks": ["PII", 3]}}})["form"][
            "guardrails"]
        assert guardrails["controls"] == [_on("pii", "input"), _on("pii", "output")]

    def test_topics_may_say_whether_they_overlap_and_folders_may_be_hidden(self):
        analytics = parse_context({"form": {"analytics": {
            "topics": ["Billing", {"name": "Asks for a person", "overlap": True}, {"name": " "}, {"overlap": True}],
            "hidden_folders": ["overview", "", 3],
        }}})["form"]["analytics"]
        assert analytics == {"enabled": True, "topics": ["Billing", "Asks for a person"],
                             "overlapping": ["Asks for a person"], "hidden_folders": ["overview"]}

    @pytest.mark.parametrize("raw", [{"form": ["x"]}, {"step": "publish"}, {"step": 3}])
    def test_a_bad_form_or_step_is_refused(self, raw):
        with pytest.raises(BadDraftRequest):
            parse_context(raw)

    def test_the_prompt_views_unsaved_text_is_kept_whole_up_to_the_read_cap(self):
        from docsgpt.drafter.prompt_recipe import READ_MAX

        long = "You help.\n" + "y" * 30000
        draft = parse_context({"form": {"prompt_draft": {"name": "P", "content": long}}})["form"]["prompt_draft"]
        assert draft["content"] == long
        with pytest.raises(BadDraftRequest, match="too long"):
            parse_context({"form": {"prompt_draft": {"name": "P", "content": "y" * (READ_MAX + 1)}}})

    def test_ids_equal_once_cut_are_kept_once(self):
        long = "s" * 150
        assert parse_context({"form": {"sources": [long + "a", long + "b"]}})["form"]["sources"] == [long[:100]]

    def test_a_starter_is_kept_and_an_unknown_one_dropped(self):
        assert parse_context({"step": "basics", "starter": "website"})["starter"] == "website"
        assert parse_context({"step": "basics", "starter": "pirate"})["starter"] is None
        assert parse_context({})["starter"] is None

    @pytest.mark.parametrize("bad", [["website"], {"website": 1}])
    def test_values_of_the_wrong_type_are_left_out_not_raised(self, bad):
        keys = ("agent_id", "starter", "earlier")
        form_keys = ("name", "description", "agent_type", "sources", "tools", "prompt_id", "prompt_draft",
                     "starters", "limits", "guardrails", "analytics")
        ctx = parse_context({**{key: bad for key in keys}, "step": "basics", "form": {key: bad for key in form_keys}})
        assert ctx["starter"] is None and ctx["agent_id"] is None
        nested = {"limits": {"mode": bad, "value": bad}, "guardrails": {"mode": bad, "checks": bad},
                  "analytics": {"topics": [bad], "hidden_folders": [bad]}}
        assert parse_context({"form": nested})["form"]["limits"] == {"mode": "none", "value": None}

    def test_no_step_is_improve_mode(self):
        assert parse_context({"step": None})["step"] is None
        assert parse_context({})["step"] is None

    def test_the_model_reads_a_custom_prompts_text_and_its_mode(self):
        data = context_data(_req({"prompt_id": PROMPT_ID}), _ws())
        assert data["prompt"] == {"kind": "existing", "id": PROMPT_ID, "content": "You help customers.",
                                  "mode": "persona", "editable": True}
        data = context_data(_req({}), _ws())
        assert data["prompt"] == {"kind": "existing", "id": "default", "mode": "template"}
        assert data["agent_type"] == "classic"

    def test_the_prompt_views_unsaved_text_is_the_current_prompt(self):
        data = context_data(_req({"prompt_id": PROMPT_ID, "prompt_draft": {"name": "D", "content": "Be kind."}}),
                            _ws())
        assert data["prompt"]["content"] == "Be kind." and data["prompt"]["name"] == "D"
        assert data["prompt"]["mode"] == "persona" and "not saved" in data["prompt"]["kind"]

    def test_the_agents_own_prompt_is_marked_editable(self):
        data = context_data(_req({"prompt_id": PROMPT_ID}), _ws())
        assert data["prompt"]["editable"] is True
        # A built-in prompt, and a new prompt not saved yet, are rewritten instead.
        assert "editable" not in context_data(_req({}), _ws())["prompt"]
        new = {"prompt_id": PROMPT_ID, "prompt_draft": {"name": "D", "content": "Be kind."}}
        assert "editable" not in context_data(_req(new), _ws())["prompt"]

    def test_unsaved_changes_to_a_saved_prompt_are_that_prompt(self):
        form = {"prompt_id": "default", "prompt_draft": {"id": PROMPT_ID, "name": "Support", "content": "Be kind."}}
        assert parse_context({"form": form})["form"]["prompt_draft"]["id"] == PROMPT_ID
        data = context_data(_req(form), _ws())
        assert data["prompt"]["id"] == PROMPT_ID and data["prompt"]["content"] == "Be kind."
        assert data["prompt"]["editable"] is True and "changed in the prompt view" in data["prompt"]["kind"]

    def test_the_step_and_earlier_messages_are_given(self):
        data = context_data(_req({}, step="knowledge", earlier=["A help desk for parcels"]), _ws())
        assert data["step"] == "knowledge"
        assert data["users_earlier_messages"] == ["A help desk for parcels"]
        assert "limits" not in data and "safety_options" not in data
        assert "users_earlier_messages" not in context_data(_req({}), _ws())

    def test_the_safety_step_says_what_is_available(self):
        data = context_data(_req({"analytics": {"enabled": True, "topics": ["Billing"]}}, step="safety"), _ws())
        options = data["safety_options"]
        assert options["limits"]["available"] is True
        assert options["limits"]["recommended"] == {"requests": 500, "tokens": 50000}
        assert [c["id"] for c in options["guardrails"]["checks"]] == MENU
        assert options["insights_topics"] == {"available": True, "room": 14}
        assert data["limits"] == {"mode": "none", "value": None}

    def test_the_safety_step_counts_the_source_folders_as_topics(self):
        ws = _ws(folders=FOLDERS)
        form = {"analytics": {"topics": ["Billing", {"name": "Asks for a person", "overlap": True}],
                              "hidden_folders": ["overview"]}}
        data = context_data(_req(form, step="safety"), ws)
        topics = data["safety_options"]["insights_topics"]
        # 15 options: Billing and the five folders not hidden leave 9; the overlapping topic takes none.
        assert topics == {"available": True, "room": 9, "room_pushing_folders_out": 5,
                          "source_folders": ["deploying", "sources", "extensions", "tools", "agents"]}
        assert data["analytics"] == {"enabled": True, "topics": ["Billing", "Asks for a person"]}

    def test_past_the_free_room_topics_push_folders_out(self):
        form = {"analytics": {"topics": [f"T{i}" for i in range(12)]}}
        topics = context_data(_req(form, step="safety"), _ws(folders=FOLDERS))["safety_options"]["insights_topics"]
        assert topics == {"available": True, "room": 0, "room_pushing_folders_out": 3,
                          "source_folders": ["deploying", "overview", "sources"]}
        full = {"analytics": {"topics": [f"T{i}" for i in range(15)]}}
        options = context_data(_req(full, step="safety"), _ws(folders=FOLDERS))["safety_options"]
        assert options["insights_topics"] == {"available": False, "why": "no_room"}

    def test_the_model_reads_which_stages_a_check_runs_at(self):
        form = {"guardrails": {"enabled": True, "controls": [_on("pii", "input"), _on("injection", "input"),
                                                              _on("moderation", "output")]}}
        data = context_data(_req(form, step="safety"), _ws())
        assert data["guardrails"] == {"enabled": True, "mode": "monitor_only",
                                      "checks": ["pii (input only)", "injection", "moderation"]}
        assert "(input only)" in instructions(_req(form, step="safety"), _ws())

    def test_a_saved_agent_with_enough_conversations_gets_topics_from_them(self):
        ws = _ws(topics_from_conversations=True)
        topics = context_data(_req({}, step="safety"), ws)["safety_options"]["insights_topics"]
        assert topics == {"available": False, "why": "suggest_from_conversations"}
        proposal = _validate({"analytics": {"topics": [{"name": "Billing", "description": "Invoices"}]}},
                             ws=ws, step="safety", asked=True)
        assert proposal["fields"] == {}

    def test_without_policy_access_or_insights_the_parts_are_unavailable(self):
        ws = _ws(policy_editable=False, insights=False)
        options = context_data(_req({}, step="safety"), ws)["safety_options"]
        assert options["limits"] == {"available": False, "why": "no_access"}
        assert options["guardrails"] == {"available": False, "why": "no_access"}
        assert options["insights_topics"]["available"] is False
        off = context_data(_req({"analytics": {"enabled": False}}, step="safety"), _ws())["safety_options"]
        assert off["insights_topics"]["available"] is False


@pytest.mark.unit
class TestAvailability:
    def test_the_menu_holds_the_checks_the_instance_allows(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", True)
        monkeypatch.setattr(settings, "GUARDRAILS_CHECKS_ENABLED", [])
        assert guardrail_menu() == MENU
        monkeypatch.setattr(settings, "GUARDRAILS_CHECKS_ENABLED", ["pii", "secrets"])
        assert guardrail_menu() == ["pii", "secrets"]
        monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", False)
        assert guardrail_menu() == []

    def test_the_workspace_carries_the_instance_flags(self, monkeypatch, one_conn):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", True)
        monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", True)
        monkeypatch.setattr(settings, "GUARDRAILS_CHECKS_ENABLED", [])
        loaded = Workspace(sources=[{"id": SOURCE_ID, "name": "Help"}], policy_editable=False)
        with patch.object(agent_recipe, "read_workspace", return_value=loaded), patch(
            "docsgpt.decisions.available", return_value=True
        ):
            ws = AGENT_RECIPE.load_workspace("alice", {"agent_id": None})
        assert isinstance(ws, AgentWorkspace) and ws.sources == loaded.sources
        assert ws.policy_editable is False and ws.insights is True and ws.guardrail_menu == MENU
        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", False)
        with patch.object(agent_recipe, "read_workspace", return_value=Workspace()), patch(
            "docsgpt.decisions.available", return_value=True
        ):
            assert AGENT_RECIPE.load_workspace("alice", {"agent_id": None}).insights is False

    def test_both_recipes_read_the_instances_insights_switch_from_one_check(self, monkeypatch, one_conn):
        from docsgpt.core.settings import settings
        from docsgpt.drafter import topics_recipe

        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", True)
        with patch("docsgpt.decisions.available", side_effect=RuntimeError("down")):
            assert topics_recipe.insights_on_here() is False
        with patch("docsgpt.decisions.available", return_value=True):
            assert topics_recipe.insights_on_here() is True
        with patch.object(topics_recipe, "insights_on_here", return_value=False), patch.object(
            agent_recipe, "read_workspace", return_value=Workspace()
        ):
            assert AGENT_RECIPE.load_workspace("alice", {"agent_id": None}).insights is False
            assert topics_recipe.insights_off({}) == "off_on_this_instance"

    def test_the_safety_step_reads_everything_through_one_connection(self, monkeypatch, one_conn):
        from docsgpt.core.settings import settings
        from docsgpt.drafter import topics_recipe

        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", True)
        loaded = _ws()
        saved = Workspace(**{k: getattr(loaded, k) for k in ("sources", "tools", "prompts", "prompt_texts")},
                          agent={"id": "a1", "name": "Docs"})
        context = {"agent_id": "a1", "step": "safety", "form": {"prompt_id": PROMPT_ID, "sources": [SOURCE_ID]}}
        row = {"id": "a1", "config": {}}
        with patch.object(agent_recipe, "read_workspace", return_value=saved) as read_ws, patch(
            "docsgpt.decisions.available", return_value=True
        ), patch.object(topics_recipe, "editable_agent", return_value=row) as agent, patch.object(
            topics_recipe, "status_of", return_value={"available": True}
        ) as status, patch.object(agent_recipe, "saved_source_ids", return_value=set()) as sources, patch.object(
            agent_recipe, "source_folders", return_value=FOLDERS
        ) as folders, patch.object(agent_recipe, "saved_prompt_text", return_value="Whole.") as prompt:
            ws = AGENT_RECIPE.load_workspace("alice", context)
        assert one_conn.opened == 1
        read_ws.assert_called_once_with(one_conn.conn, "alice", "a1")
        prompt.assert_called_once_with(one_conn.conn, "alice", PROMPT_ID)
        # The agent row is read once, and the saved sources and the conversations count reuse it.
        agent.assert_called_once_with(one_conn.conn, "alice", "a1")
        sources.assert_called_once_with(one_conn.conn, row)
        folders.assert_called_once_with(one_conn.conn, [SOURCE_ID])
        status.assert_called_once_with(one_conn.conn, row)
        assert ws.folders == FOLDERS and ws.topics_from_conversations is True and ws.editable_prompt_text == "Whole."

    def test_the_safety_step_asks_whether_a_saved_agent_has_enough_conversations(self, monkeypatch, one_conn):
        from docsgpt.api.user.resource_access import AccessDenied
        from docsgpt.core.settings import settings
        from docsgpt.drafter import topics_recipe

        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", True)
        saved = Workspace(agent={"id": "a1", "name": "Docs"})
        context = {"agent_id": "a1", "step": "safety", "form": {}}
        with patch.object(agent_recipe, "read_workspace", return_value=saved), patch(
            "docsgpt.decisions.available", return_value=True
        ), patch.object(topics_recipe, "editable_agent", return_value={"id": "a1"}) as agent, patch.object(
            topics_recipe, "status_of", return_value={"available": True}
        ) as status, patch.object(agent_recipe, "saved_source_ids", return_value=set()):
            assert AGENT_RECIPE.load_workspace("alice", context).topics_from_conversations is True
            status.side_effect = RuntimeError("count failed")
            assert AGENT_RECIPE.load_workspace("alice", context).topics_from_conversations is False
            # A caller who may only view the agent gets no count.
            status.reset_mock()
            agent.side_effect = AccessDenied(403, "no")
            assert AGENT_RECIPE.load_workspace("alice", context).topics_from_conversations is False
            status.assert_not_called()
            agent.side_effect = None
            AGENT_RECIPE.load_workspace("alice", {**context, "step": "prompt"})
            status.assert_not_called()
        with patch.object(agent_recipe, "read_workspace", return_value=Workspace()), patch(
            "docsgpt.decisions.available", return_value=True
        ), patch.object(topics_recipe, "status_of") as status:
            AGENT_RECIPE.load_workspace("alice", {"agent_id": None, "step": "safety", "form": {}})
            status.assert_not_called()

    def test_the_safety_step_reads_the_folders_of_the_sources_the_caller_may_attach(self, monkeypatch, one_conn):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", True)
        loaded = Workspace(sources=[{"id": SOURCE_ID, "name": "Help"}])
        context = {"agent_id": None, "step": "safety", "form": {"sources": [SOURCE_ID, "not-mine"]}}
        with patch.object(agent_recipe, "read_workspace", return_value=loaded), patch(
            "docsgpt.decisions.available", return_value=True
        ), patch.object(agent_recipe, "source_folders", return_value=FOLDERS) as read:
            ws = AGENT_RECIPE.load_workspace("alice", context)
            assert ws.folders == FOLDERS
            read.assert_called_once_with(one_conn.conn, [SOURCE_ID])
            read.reset_mock()
            AGENT_RECIPE.load_workspace("alice", {**context, "step": "knowledge"})
            read.assert_not_called()

    def test_a_saved_agents_own_sources_give_their_folders_too(self, monkeypatch, one_conn):
        # An editor building the owner's agent: the owner's private source is on the agent, not attachable.
        from docsgpt.core.settings import settings
        from docsgpt.drafter import topics_recipe

        monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", True)
        saved = Workspace(sources=[{"id": SOURCE_ID, "name": "Help"}], agent={"id": "a1", "name": "Docs"})
        form = {"sources": [SOURCE_ID, "owners-private", "not-on-it"]}
        context = {"agent_id": "a1", "step": "safety", "form": form}
        row = {"id": "a1"}
        with patch.object(agent_recipe, "read_workspace", return_value=saved), patch(
            "docsgpt.decisions.available", return_value=True
        ), patch.object(topics_recipe, "editable_agent", return_value=row), patch.object(
            topics_recipe, "status_of", return_value={"available": False}
        ), patch.object(
            agent_recipe, "saved_source_ids", return_value={"owners-private"}
        ) as saved_ids, patch.object(agent_recipe, "source_folders", return_value=FOLDERS) as read:
            AGENT_RECIPE.load_workspace("bob", context)
            saved_ids.assert_called_once_with(one_conn.conn, row)
            read.assert_called_once_with(one_conn.conn, [SOURCE_ID, "owners-private"])

    def test_the_agents_own_saved_prompt_is_read_whole(self, monkeypatch, one_conn):
        loaded = _ws()
        context = {"agent_id": None, "step": "prompt", "form": {"prompt_id": PROMPT_ID}}
        with patch.object(agent_recipe, "read_workspace", return_value=Workspace(**{
            k: getattr(loaded, k) for k in ("sources", "tools", "prompts", "prompt_texts")
        })), patch.object(agent_recipe, "saved_prompt_text", return_value="The whole text.") as read:
            assert AGENT_RECIPE.load_workspace("alice", context).editable_prompt_text == "The whole text."
            read.assert_called_once_with(one_conn.conn, "alice", PROMPT_ID)
            read.reset_mock()
            # Unsaved text in the prompt view is the text edits fit; a built-in has nothing to read.
            draft = {**context["form"], "prompt_draft": {"id": PROMPT_ID, "name": "S", "content": "Unsaved."}}
            assert AGENT_RECIPE.load_workspace("alice", {**context, "form": draft}).editable_prompt_text is None
            AGENT_RECIPE.load_workspace("alice", {**context, "form": {"prompt_id": "strict"}})
            read.assert_not_called()


@pytest.mark.unit
class TestEditablePromptText:
    def _load(self, saved_text: str, form=None):
        from docsgpt.drafter.catalog import PROMPT_CHARS

        loaded = Workspace(prompts=[{"id": PROMPT_ID, "name": "Support", "kind": "own"}],
                           prompt_texts={PROMPT_ID: saved_text[:PROMPT_CHARS - 1] + "…"})
        context = {"agent_id": None, "step": "prompt", "form": form or {"prompt_id": PROMPT_ID}}
        with patch.object(agent_recipe, "read_workspace", return_value=loaded), patch.object(
            agent_recipe, "saved_prompt_text", return_value=saved_text
        ):
            return AGENT_RECIPE.load_workspace("alice", context)

    def test_the_agents_own_prompt_is_shown_to_the_model_whole(self, one_conn):
        from docsgpt.drafter.read_tools import run_read_tool

        whole = "You help customers.\n" + "x" * 15000 + "\nThe end."
        ws = self._load(whole)
        assert context_data(_req({"prompt_id": PROMPT_ID}), ws)["prompt"]["content"] == whole
        assert run_read_tool("get_prompt", ws, {"prompt_id": PROMPT_ID})["content"] == whole
        # So the model can change its end, which a cut copy hid.
        end = {"find": "The end.", "replace": "Goodbye.", "reason": "r"}
        proposal = validate({"message": "m", "fields": {"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [end]}}},
                            _req({"prompt_id": PROMPT_ID}, step="prompt"), ws)
        assert proposal["fields"]["prompt"]["edits"][0]["find"] == "The end."

    def test_a_saved_prompt_over_the_read_cap_is_not_edited(self, one_conn):
        from docsgpt.drafter.prompt_recipe import READ_MAX

        ws = self._load("You help customers.\n" + "x" * READ_MAX)
        assert ws.editable_prompt_text is None
        data = context_data(_req({"prompt_id": PROMPT_ID}), ws)["prompt"]
        assert "editable" not in data and "too long" in data["note"]
        with pytest.raises(ProposalInvalid, match="own prompt"):
            validate({"message": "m", "fields": {"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [EDIT]}}},
                     _req({"prompt_id": PROMPT_ID}, step="prompt"), ws)


def test_saved_source_ids_are_the_agents(pg_conn):
    from docsgpt.storage.db.repositories.agents import AgentsRepository
    from docsgpt.storage.db.repositories.sources import SourcesRepository

    first = SourcesRepository(pg_conn).create("Docs", user_id="alice")
    second = SourcesRepository(pg_conn).create("Wiki", user_id="alice")
    agent = AgentsRepository(pg_conn).create("alice", "Bot", "published", key="k-saved-sources",
                                             source_id=str(first["id"]), extra_source_ids=[str(second["id"])])
    assert agent_recipe.saved_source_ids(pg_conn, agent) == {str(first["id"]), str(second["id"])}


def test_the_safety_step_reads_a_saved_agent_for_someone_who_can_edit_it(pg_conn, monkeypatch):
    from contextlib import contextmanager

    from docsgpt.core.settings import settings
    from docsgpt.storage.db.repositories.agents import AgentsRepository
    from docsgpt.storage.db.repositories.sources import SourcesRepository

    monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", True)
    source = SourcesRepository(pg_conn).create("Docs", user_id="alice")
    agent = AgentsRepository(pg_conn).create("alice", "Bot", "published", key="k-one-conn",
                                             source_id=str(source["id"]))
    context = {"agent_id": str(agent["id"]), "step": "safety", "form": {"sources": [str(source["id"])]}}

    @contextmanager
    def _same():
        yield pg_conn

    with patch("docsgpt.storage.db.session.db_readonly", _same), patch(
        "docsgpt.decisions.available", return_value=True
    ), patch.object(agent_recipe, "load_models"), patch.object(
        agent_recipe, "source_folders", return_value=FOLDERS
    ) as folders:
        ws = AGENT_RECIPE.load_workspace("alice", context)
        assert ws.agent["id"] == str(agent["id"]) and ws.folders == FOLDERS
        assert ws.topics_from_conversations is False
        folders.assert_called_once_with(pg_conn, [str(source["id"])])
        # Someone who can't edit the agent reads none of its own sources.
        folders.reset_mock()
        AGENT_RECIPE.load_workspace("mallory", context)
        folders.assert_called_once_with(pg_conn, [])


def test_saved_prompt_text_reads_the_callers_prompt_uncut(pg_conn):
    from docsgpt.storage.db.repositories.prompts import PromptsRepository

    long = "You help.\n" + "y" * 30000
    prompt = PromptsRepository(pg_conn).create("alice", "Long", long)
    assert agent_recipe.saved_prompt_text(pg_conn, "alice", str(prompt["id"])) == long
    assert agent_recipe.saved_prompt_text(pg_conn, "mallory", str(prompt["id"])) is None


@pytest.mark.unit
class TestInstructions:
    def test_key_rules_are_stated(self):
        text = instructions(_req(), _ws())
        for rule in (
            '"classic"', '"research"', "at most 200 characters", "up to 4",
            "Never set or mention changing models, guardrails",
            "looks internal", "no tool supports", "off-topic",
            "plain text with no {{ }} variables", "today's date", "reply in the user's language",
            "Never add {{ tools... }} variables unless the user asks",
            "keep its sections and {% if %} blocks",
            "change only what the user asked for",
            "The form is empty",
        ):
            assert rule in text, rule
        assert "{{ source.citation_rules }}" not in text
        assert "The current step" not in text

    def test_internal_looking_tools_are_asked_about_too(self):
        text = instructions(_req(), _ws())
        assert "a source or tool looks internal" in text

    def test_a_filled_form_is_a_change_request(self):
        assert "change request" in instructions(_req({"name": "Shipping help"}), _ws())
        assert "change request" in instructions(_req(), _ws(agent={"id": "a"}))
        assert "change request" in instructions(_req({"prompt_draft": {"name": "P", "content": "x"}}), _ws())

    @pytest.mark.parametrize("step,own", [
        ("basics", "name, description"),
        ("knowledge", "sources, tools, agent_type"),
        ("prompt", "prompt, starters"),
        ("safety", "limits, guardrails, analytics"),
    ])
    def test_each_step_sets_only_its_own_fields(self, step, own):
        text = instructions(_req({}, step=step), _ws())
        assert f"The current step is {step}" in text
        assert f"In this step set only: {own}" in text
        assert "Fast path" in text and "plain approval" in text and "users_earlier_messages" in text

    def test_the_prompt_step_writes_from_the_attached_knowledge(self):
        text = instructions(_req({}, step="prompt"), _ws())
        assert "from the sources and tools already on the form" in text

    @pytest.mark.parametrize("starter,marker", [
        ("website", 'started from "Website chat for customers"'),
        ("helpdesk", 'started from "Internal helpdesk"'),
        ("research", 'started from "Research assistant"'),
    ])
    def test_a_starter_brings_its_brief_to_every_step(self, starter, marker):
        for step in ("basics", "knowledge", "prompt", "safety"):
            req = DraftRequest("alice", "agent", [{"role": "user", "content": "x"}],
                               parse_context({"step": step, "starter": starter}), "drafter:t")
            text = instructions(req, _ws())
            assert marker in text and "Use the part for the current step" in text, step
        assert marker not in instructions(_req({}, step="basics"), _ws())

    def test_proposals_stay_lean(self):
        text = instructions(_req(), _ws())
        for rule in ("one reason per field", "what you left out in a few words", "at most 3",
                     "Never describe the next step"):
            assert rule in text, rule

    def test_basics_asks_who_uses_it_unless_the_user_said(self):
        text = instructions(_req({}, step="basics"), _ws())
        for rule in ("Who uses the agent decides", "unless the user's words say or clearly imply it",
                     "Customers on our public website", "Our own staff", "say in the description who it serves"):
            assert rule in text, rule

    def test_the_prompt_step_asks_about_the_hand_off_first(self):
        text = instructions(_req({}, step="prompt"), _ws())
        for rule in ("Before writing a new prompt, ask", "where it sends people it can't help",
                     "a person (live chat or phone)", "the tone", "a detail only the user knows",
                     "only for what the user picked", "Never leave placeholders"):
            assert rule in text, rule
        assert "Before writing a new prompt, ask" not in instructions(_req({}, step="basics"), _ws())

    @pytest.mark.parametrize("step", [None, "prompt"])
    def test_a_drafted_hand_off_never_promises_a_transfer(self, step):
        text = instructions(_req({}, step=step), _ws())
        assert "can't transfer the chat to a person" in text
        assert "never \"I'll connect you\"" in text
        assert "unless the agent has a tool for it" in text

    def test_only_the_safety_step_may_talk_about_policy(self):
        for step in ("basics", "knowledge", "prompt"):
            text = instructions(_req({}, step=step), _ws())
            assert "Limits, guardrails and Insights topics are the safety step's" in text
            assert "don't mention them" in text
        text = instructions(_req({}, step="safety"), _ws())
        assert "Limits, guardrails and Insights topics are the safety step's" not in text
        for rule in ("Ask first", "recommended", "500 requests", "50,000 tokens", "last 24 hours",
                     "either a request limit or a token limit", "starting topics", "Set only what the user said or picked"):
            assert rule in text, rule

    @pytest.mark.parametrize("step", ["basics", "knowledge", "prompt", "safety"])
    def test_no_step_says_the_policy_stays_as_it_is(self, step):
        # The safety step sets limits and guardrails: an earlier step's note saying they "stay as they are" is wrong.
        assert "stay as they are" not in instructions(_req({}, step=step), _ws())

    def test_the_safety_step_asks_only_what_the_users_words_leave_open(self):
        text = instructions(_req({}, step="safety"), _ws())
        for rule in ("only about the parts the user's words leave open", "users_earlier_messages",
                     "set it as they said", "propose without asking",
                     "never offer the recommended value against what they said"):
            assert rule in text, rule

    def test_the_guardrail_question_offers_one_check_per_option(self):
        text = instructions(_req({}, step="safety"), _ws())
        for rule in ("one option per check", "never a combination", '"All four"',
                     '{"label": "No extra checks", "exclusive": true}'):
            assert rule in text, rule

    def test_topics_are_subjects_and_none_is_an_exclusive_option(self):
        text = instructions(_req({}, step="safety"), _ws())
        for rule in ("a subject users ask about", "never an outcome or how it is handled", "Complaints & hand-offs",
                     "never mark a topic recommended", '{"label": "No topics", "exclusive": true}'):
            assert rule in text, rule
        assert 'a last option "No topics"' not in text

    def test_the_safety_step_suggests_only_what_the_source_folders_miss(self):
        text = instructions(_req({}, step="safety"), _ws())
        for rule in ("source_folders", "never suggest a topic a folder already covers",
                     "room_pushing_folders_out"):
            assert rule in text, rule

    def test_the_topics_are_offered_one_by_one(self):
        text = instructions(_req({}, step="safety"), _ws())
        for rule in ("pick-any question (multi true)", "one option per topic, its label the topic's name",
                     "set only the topics the user ticks"):
            assert rule in text, rule

    def test_a_saved_agent_with_conversations_is_pointed_to_suggest_from_conversations(self):
        text = instructions(_req({}, step="safety"), _ws())
        assert "suggest_from_conversations" in text and "Suggest from conversations" in text

    def test_system_prompt_carries_the_recipe_and_the_tool_protocol(self):
        messages = build_messages(_req(), AGENT_RECIPE, _ws(), tool_mode=True, allow_questions=True)
        system = messages[0]["content"]
        assert "DocsGPT drafter" in system and "drafting an AI agent" in system
        assert "submit_proposal" in system and "never save" in system


@pytest.mark.unit
class TestValidate:
    def test_ids_the_caller_cannot_attach_are_dropped_and_reported(self):
        proposal = _validate({"sources": [SOURCE_ID, "foreign"], "tools": ["x", TOOL_ID],
                              "prompt": {"kind": "existing", "id": "someone-elses"}})
        assert proposal["fields"] == {"sources": [SOURCE_ID], "tools": [TOOL_ID]}
        assert proposal["dropped"] == [
            {"field": "sources", "id": "foreign", "reason": "not_found"},
            {"field": "tools", "id": "x", "reason": "not_found"},
            {"field": "prompt", "id": "someone-elses", "reason": "not_found"},
        ]

    def test_a_list_whose_every_id_is_dropped_leaves_the_forms_list_alone(self):
        # A name in place of an id isn't a request to clear the form's knowledge.
        proposal = _validate({"name": "Help desk", "sources": ["Help Center"], "tools": ["Tracking"]},
                             form={"sources": [SOURCE_ID], "tools": [TOOL_ID]}, step="basics")
        assert proposal["fields"] == {"name": "Help desk"}
        assert [d["id"] for d in proposal["dropped"]] == ["Help Center", "Tracking"]
        assert proposal["steps"] == ["basics"] and proposal["next_step"] == "knowledge"
        # An empty list is still a request to clear it.
        assert _validate({"sources": []}, form={"sources": [SOURCE_ID]})["fields"] == {"sources": []}

    def test_ids_already_on_the_form_are_kept(self):
        proposal = _validate({"tools": ["owners-tool", TOOL_ID]}, form={"tools": ["owners-tool"]})
        assert proposal["fields"]["tools"] == ["owners-tool", TOOL_ID] and proposal["dropped"] == []

    def test_the_attach_cap_counts_only_what_the_proposal_adds(self):
        many = [f"src-{n}" for n in range(agent_recipe.MAX_REFS + 5)]
        assert _validate({"sources": many}, form={"sources": many})["fields"] == {}
        assert _validate({"sources": many[1:]}, form={"sources": many})["fields"] == {"sources": many[1:]}
        ws = _ws(sources=[{"id": ref, "name": ref} for ref in many])
        with pytest.raises(ProposalInvalid, match="at most"):
            _validate({"sources": many}, ws=ws)

    def test_unknown_fields_never_reach_the_form(self):
        proposal = _validate({"name": "Help", "models": ["gpt"], "json_schema": {}})
        assert proposal["fields"] == {"name": "Help"}

    def test_unchanged_fields_are_left_out(self):
        form = {"name": "Help", "agent_type": "classic", "prompt_id": PROMPT_ID, "starters": ["Hi"]}
        proposal = _validate({"name": "Help", "agent_type": "classic", "starters": ["Hi"],
                              "prompt": {"kind": "existing", "id": PROMPT_ID}, "description": "New"},
                             form=form, reasons=[{"field": "name", "summary": "kept"},
                                                 {"field": "description", "summary": "Says what it does"}])
        assert proposal["fields"] == {"description": "New"}
        assert proposal["reasons"] == [{"field": "description", "summary": "Says what it does"}]

    def test_a_field_keeps_its_first_reason_only(self):
        proposal = _validate({"sources": [SOURCE_ID]}, reasons=[
            {"field": "sources", "summary": "Help Center · left out the wiki"},
            {"field": "sources", "summary": "Left out: internal wiki"},
        ])
        assert proposal["reasons"] == [{"field": "sources", "summary": "Help Center · left out the wiki"}]

    def test_a_reason_is_its_summary_only(self):
        # The panel shows only summaries: the model isn't asked for a detail, and one it still sends is dropped.
        proposal = _validate({"name": "Help"}, reasons=[{"field": "name", "summary": "Short", "detail": "Why"}])
        assert proposal["reasons"] == [{"field": "name", "summary": "Short"}]
        reason = agent_recipe.PROPOSAL_SCHEMA["properties"]["reasons"]["items"]
        assert set(reason["properties"]) == {"field", "summary"}
        assert "a detail saying why" not in instructions(_req({}), _ws())

    def test_notes_are_capped_at_three(self):
        proposal = _validate({"name": "Help"}, notes=[f"Note {i}" for i in range(6)])
        assert proposal["notes"] == ["Note 0", "Note 1", "Note 2"]

    def test_the_unsaved_prompt_redrafted_the_same_is_left_out(self):
        draft = {"name": "P", "content": "You help."}
        proposal = _validate({"prompt": {"kind": "new", **draft}}, form={"prompt_draft": draft}, step="prompt")
        assert proposal["fields"] == {}

    def test_starters_are_normalised(self):
        proposal = _validate({"starters": [" Where is my parcel? ", "where is my parcel?", ""]})
        assert proposal["fields"]["starters"] == ["Where is my parcel?"]

    @pytest.mark.parametrize("fields", [
        {"starters": ["a", "b", "c", "d", "e"]},
        {"starters": ["x" * 201]},
        {"name": "x" * (NAME_MAX + 1)},
        {"name": "  "},
        {"description": "x" * 501},
        {"prompt": {"kind": "new", "name": "P", "content": ""}},
        {"prompt": {"kind": "new", "name": "P", "content": "Hello {{ broken }} {% if x %}"}},
    ])
    def test_fixable_problems_go_back_to_the_model(self, fields):
        with pytest.raises(ProposalInvalid):
            _validate(fields)

    def test_a_new_plain_prompt_is_kept_as_a_persona(self):
        content = "You answer shipping questions for Meridian.\n- Refunds: point to support@meridian.example."
        proposal = _validate({"prompt": {"kind": "new", "name": "Shipping help", "content": content}})
        assert proposal["fields"]["prompt"] == {"kind": "new", "name": "Shipping help", "content": content,
                                                "checks": []}
        assert proposal["notes"] == []

    def test_switching_to_a_template_is_checked(self):
        proposal = _validate({"prompt": {"kind": "new", "name": "P", "content": "Today is {{ system.date }}."}},
                             form={"prompt_id": PROMPT_ID})
        assert proposal["fields"]["prompt"]["checks"] == ["to_template"] and proposal["notes"] == []

    def test_plain_text_replacing_a_saved_template_is_checked_but_not_a_built_in(self):
        ws = _ws(prompt_texts={**_ws().prompt_texts, PROMPT_ID: "Hi {{ system.date }}"})
        new = {"prompt": {"kind": "new", "name": "P", "content": "You help."}}
        assert _validate(new, form={"prompt_id": PROMPT_ID}, ws=ws)["fields"]["prompt"]["checks"] == ["to_persona"]
        assert _validate(new, form={"prompt_id": "default"}, ws=ws)["fields"]["prompt"]["checks"] == []

    def test_a_rewrite_that_drops_the_citation_rules_or_boundaries_is_checked(self):
        template = "{{ system.date }} You help.\n{{ source.citation_rules }}\n## Boundaries\nStay on topic."
        ws = _ws(prompt_texts={**_ws().prompt_texts, PROMPT_ID: template})
        proposal = _validate({"prompt": {"kind": "new", "name": "Copy", "content": "{{ system.date }} You help."}},
                             form={"prompt_id": PROMPT_ID}, ws=ws, step="prompt")
        assert proposal["fields"]["prompt"]["checks"] == ["boundaries_removed", "citations_removed"]

    def test_tool_variables_need_the_users_ask(self):
        fields = {"prompt": {"kind": "new", "name": "P", "content": "Memory: {{ tools.memory.memory_view }}"}}
        with pytest.raises(ProposalInvalid, match="tools"):
            _validate(fields)
        asked = _validate(fields, messages=("Put {{ tools.memory.memory_view }} in the prompt",))
        assert asked["fields"]["prompt"]["content"].startswith("Memory:")

    @pytest.mark.parametrize("text", ["Explain Liquid tags such as {% for %}.", "Say {# hi #}.", "Write {{ alone."])
    def test_plain_text_with_braces_is_not_parsed_as_a_template(self, text):
        proposal = _validate({"prompt": {"kind": "new", "name": "Liquid", "content": text}})
        assert proposal["fields"]["prompt"]["content"] == text
        edit = {"find": "You help customers.", "replace": text, "reason": "Asked."}
        edited = _validate({"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [edit]}}, form={"prompt_id": PROMPT_ID})
        assert edited["fields"]["prompt"]["edits"][0]["replace"] == text

    def test_a_template_that_does_not_parse_goes_back_to_the_model(self):
        with pytest.raises(ProposalInvalid, match="parse"):
            _validate({"prompt": {"kind": "new", "name": "P", "content": "{{ system.date }} {% for %}"}})

    def test_a_tool_variable_asked_for_in_an_earlier_step_counts(self):
        # The guided build moves the finished steps' messages to context.earlier and starts a new conversation.
        fields = {"prompt": {"kind": "new", "name": "P", "content": "Memory: {{ tools.memory.memory_view }}"}}
        earlier = ["A help desk that reads {{ tools.memory.memory_view }} in its prompt"]
        proposal = validate({"message": "Done.", "fields": fields},
                            _req({}, "Write the prompt", step="prompt", earlier=earlier), _ws())
        assert proposal["fields"]["prompt"]["content"].startswith("Memory:")
        edit = {"find": "You help customers.", "replace": "Memory: {{ tools.memory.memory_view }}", "reason": "r"}
        edited = validate({"message": "Done.", "fields": {"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [edit]}}},
                          _req({"prompt_id": PROMPT_ID}, "Edit it", step="prompt", earlier=earlier), _ws())
        assert edited["fields"]["prompt"]["kind"] == "edit"

    def test_tool_variables_already_in_the_template_are_kept(self):
        template = "Hi {% if tools.memory.memory_view %}{{ tools.memory.memory_view }}{% endif %}"
        ws = _ws(prompt_texts={"default": template})
        proposal = _validate({"prompt": {"kind": "new", "name": "Copy", "content": template + " Be brief."}},
                             ws=ws)
        assert proposal["fields"]["prompt"]["name"] == "Copy"


EDIT = {"find": "You help customers.", "replace": "You help customers of Meridian.", "reason": "Names the company."}


@pytest.mark.unit
class TestPromptEdits:
    def test_the_agents_own_prompt_is_changed_with_edits(self):
        proposal = _validate({"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [EDIT]}},
                             form={"prompt_id": PROMPT_ID})
        assert proposal["fields"]["prompt"] == {
            "kind": "edit", "id": PROMPT_ID, "edits": [{"id": "e1", **EDIT}], "checks": [],
        }

    def test_edits_fit_the_text_open_in_the_prompt_view(self):
        form = {"prompt_id": PROMPT_ID,
                "prompt_draft": {"id": PROMPT_ID, "name": "Support", "content": "You help customers. Be brief."}}
        proposal = _validate({"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [EDIT]}}, form=form)
        assert proposal["fields"]["prompt"]["edits"] == [{"id": "e1", **EDIT}]
        # An edit only the saved text has doesn't fit the view's.
        gone = {"find": "Be kind.", "replace": "Be warm.", "reason": "r"}
        with pytest.raises(ProposalInvalid, match="not found"):
            _validate({"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [gone]}}, form=form)

    def test_an_own_prompt_over_the_workspace_cap_still_takes_edits(self):
        newer = "44444444-4444-4444-4444-444444444444"
        ws = _ws(own_prompts={PROMPT_ID, newer}, prompt_texts={newer: "You help customers."})
        proposal = _validate({"prompt": {"kind": "edit", "id": newer, "edits": [EDIT]}},
                             form={"prompt_id": newer}, ws=ws)
        assert proposal["fields"]["prompt"]["id"] == newer

    @pytest.mark.parametrize("form,prompt_id", [
        ({}, "default"),
        ({"prompt_id": PROMPT_ID}, "someone-elses"),
        ({"prompt_id": PROMPT_ID, "prompt_draft": {"name": "New", "content": "You help customers."}}, PROMPT_ID),
    ])
    def test_only_the_editable_prompt_takes_edits(self, form, prompt_id):
        with pytest.raises(ProposalInvalid, match="write a new prompt"):
            _validate({"prompt": {"kind": "edit", "id": prompt_id, "edits": [EDIT]}}, form=form)

    @pytest.mark.parametrize("edit", [
        {"find": "not in the prompt", "replace": "x", "reason": "r"},
        {"find": "You help customers.", "replace": "Hi {{ broken }} {% if x %}", "reason": "r"},
        {"find": "You help customers.", "replace": "x", "reason": ""},
    ])
    def test_edits_follow_the_prompt_recipes_rules(self, edit):
        with pytest.raises(ProposalInvalid):
            _validate({"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [edit]}}, form={"prompt_id": PROMPT_ID})

    def test_the_agents_own_prompt_over_the_cap_still_takes_edits(self):
        # The prompt routes store any length; the drafter's cap is for what it writes, not what is there.
        long = "You help customers. " + "x" * 20100
        ws = _ws()
        ws.editable_prompt_text = long
        edit = {"find": "You help customers. ", "replace": "", "reason": "Shorter."}
        proposal = _validate({"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [edit]}},
                             form={"prompt_id": PROMPT_ID}, ws=ws)
        assert proposal["fields"]["prompt"]["edits"][0]["find"] == "You help customers. "

    def test_no_change_leaves_the_prompt_out(self):
        same = {**EDIT, "replace": EDIT["find"]}
        proposal = _validate({"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [same]}},
                             form={"prompt_id": PROMPT_ID})
        assert "prompt" not in proposal["fields"]

    def test_a_switch_to_a_template_is_checked(self):
        edit = {**EDIT, "replace": "You help customers. Today is {{ system.date }}."}
        proposal = _validate({"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [edit]}},
                             form={"prompt_id": PROMPT_ID})
        assert proposal["fields"]["prompt"]["checks"] == ["to_template"]

    @pytest.mark.parametrize("step", ["basics", "safety"])
    def test_edits_outside_the_prompt_step_are_dropped(self, step):
        proposal = _validate({"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [EDIT]}},
                             form={"prompt_id": PROMPT_ID}, step=step, asked=True)
        assert "prompt" not in proposal["fields"]

    def test_edits_are_checked_against_the_whole_saved_prompt(self):
        from docsgpt.drafter.catalog import PROMPT_CHARS

        whole = ("{{ system.date }} You help customers.\n" + "x" * PROMPT_CHARS
                 + "\nYou help customers.\n## Boundaries\nStay on topic.")
        ws = _ws(prompt_texts={PROMPT_ID: whole[:PROMPT_CHARS - 1] + "…"}, editable_prompt_text=whole)
        form = {"prompt_id": PROMPT_ID}
        # The find is there twice once the part past the model's copy counts.
        with pytest.raises(ProposalInvalid, match="occurs 2 times"):
            _validate({"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [EDIT]}}, form=form, ws=ws)
        # The cut marker isn't in the saved text.
        cut = {"find": "xx…", "replace": "x", "reason": "r"}
        with pytest.raises(ProposalInvalid, match="not found"):
            _validate({"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [cut]}}, form=form, ws=ws)
        # Checks see what lies past the cut.
        drop = {"find": "## Boundaries\nStay on topic.", "replace": "", "reason": "r"}
        proposal = _validate({"prompt": {"kind": "edit", "id": PROMPT_ID, "edits": [drop]}}, form=form, ws=ws)
        assert proposal["fields"]["prompt"]["checks"] == ["boundaries_removed"]

    def test_the_model_is_told_to_edit_the_editable_prompt(self):
        text = instructions(_req({"prompt_id": PROMPT_ID}), _ws())
        for rule in ('kind "edit"', "prompt.editable", "find: an exact passage", "never a new prompt"):
            assert rule in text, rule


NEW_PROMPT = {"kind": "new", "name": "Help desk", "content": "You answer parcel questions."}


@pytest.mark.unit
class TestSteps:
    def test_a_step_fills_itself_and_points_at_the_next(self):
        proposal = _validate({"name": "Help desk", "description": "Answers parcels."}, step="basics")
        assert proposal["steps"] == ["basics"] and proposal["next_step"] == "knowledge"

    def test_the_fast_path_fills_later_steps(self):
        proposal = _validate({"name": "Help desk", "sources": [SOURCE_ID], "starters": ["Where is my parcel?"],
                              "prompt": {"kind": "existing", "id": "strict"}}, step="basics")
        assert proposal["steps"] == ["basics", "knowledge", "prompt"] and proposal["next_step"] == "safety"

    def test_a_later_step_counts_only_when_its_main_part_is_drafted(self):
        # A type alone leaves the sources and tools to pick; a prompt without starters leaves them to write.
        proposal = _validate({"name": "Help desk", "agent_type": "research",
                              "prompt": {"kind": "existing", "id": "strict"}}, step="basics")
        assert proposal["steps"] == ["basics"] and proposal["next_step"] == "knowledge"
        proposal = _validate({"tools": [TOOL_ID], "prompt": {"kind": "existing", "id": "strict"}}, step="basics")
        assert proposal["steps"] == ["basics", "knowledge"] and proposal["next_step"] == "prompt"

    def test_a_prompt_picked_ahead_fills_its_step_when_the_form_has_starters(self):
        proposal = _validate({"prompt": {"kind": "existing", "id": "strict"}}, form={"starters": ["Hi?"]},
                             step="knowledge")
        assert proposal["steps"] == ["knowledge", "prompt"] and proposal["next_step"] == "safety"

    def test_starters_alone_leave_the_prompt_step_to_run(self):
        proposal = _validate({"name": "Help desk", "starters": ["Where is my parcel?"]}, step="basics")
        assert proposal["fields"]["starters"] == ["Where is my parcel?"]
        assert proposal["steps"] == ["basics"] and proposal["next_step"] == "knowledge"

    @pytest.mark.parametrize("step", ["basics", "knowledge", "safety"])
    def test_a_new_prompt_outside_the_prompt_step_is_dropped(self, step):
        proposal = _validate({"agent_type": "research", "prompt": NEW_PROMPT}, step=step, asked=True)
        assert "prompt" not in proposal["fields"]
        assert "prompt" not in proposal["steps"]
        # Drafted ahead, the prompt step writes it later; past it, the user hears why it didn't change.
        assert proposal["dropped"] == ([{"field": "prompt", "reason": "other_step", "step": "prompt"}]
                                       if step == "safety" else [])

    def test_the_model_is_told_not_to_claim_what_a_passed_step_sets(self):
        text = instructions(_req({}, step="safety"), _ws())
        assert "don't say it changed" in text

    @pytest.mark.parametrize("step", ["prompt", None])
    def test_a_new_prompt_is_kept_in_the_prompt_step_and_improve_mode(self, step):
        assert _validate({"prompt": NEW_PROMPT}, step=step)["fields"]["prompt"] == {**NEW_PROMPT, "checks": []}

    @pytest.mark.parametrize("step", ["basics", "prompt", None])
    def test_policy_fields_outside_the_safety_step_are_dropped(self, step):
        proposal = _validate({"name": "Help desk", "limits": {"mode": "requests", "value": 500},
                              "guardrails": {"checks": ["pii"]},
                              "analytics": {"topics": [{"name": "Billing", "description": "Invoices"}]}},
                             step=step, asked=True)
        assert proposal["fields"] == {"name": "Help desk"} and proposal["dropped"] == []

    @pytest.mark.parametrize("step,next_step", [("basics", "knowledge"), ("prompt", "safety"), ("safety", None)])
    def test_a_plain_approval_is_an_empty_proposal(self, step, next_step):
        proposal = _validate({}, step=step)
        assert proposal["fields"] == {} and proposal["steps"] == [step] and proposal["next_step"] == next_step

    def test_unchanged_later_fields_do_not_fill_their_step(self):
        proposal = _validate({"name": "Help", "agent_type": "classic"}, step="basics")
        assert proposal["steps"] == ["basics"]

    def test_improve_mode_has_no_steps(self):
        proposal = _validate({"name": "Help desk"})
        assert proposal["steps"] == [] and proposal["next_step"] is None


@pytest.mark.unit
class TestSafety:
    def test_policy_needs_a_questions_round_first(self):
        with pytest.raises(ProposalInvalid, match="Ask the user first"):
            _validate({"limits": {"mode": "requests", "value": 500}}, step="safety")
        assert _validate({}, step="safety")["fields"] == {}

    STATED = ("Build a public support bot. Limit it to 1,000 requests a day, with PII and injection guardrails, "
              "no Insights topics.")

    def _stated(self, fields, *, earlier=(STATED,), message="Continue with Limits and safety.", skip=False):
        context = parse_context({"form": {}, "step": "safety", "earlier": list(earlier), "skip_questions": skip})
        req = DraftRequest("alice", "agent", [{"role": "user", "content": message}], context, "drafter:t")
        return validate({"message": "Set as you said.", "fields": fields}, req, _ws())

    def test_what_the_users_words_settle_is_set_without_asking(self):
        proposal = self._stated({"limits": {"mode": "requests", "value": 1000}, "guardrails": {"checks": ["pii",
                                                                                                         "injection"]}})
        assert proposal["fields"] == {"limits": {"mode": "requests", "value": 1000},
                                      "guardrails": _added("pii", "injection")}
        topics = [{"name": "Customs paperwork", "description": "Documents, duties"}]
        proposal = self._stated({"analytics": {"topics": topics}},
                                earlier=["Track a topic for customs paperwork questions."])
        assert proposal["fields"] == {"analytics": {"topics": topics}}

    @pytest.mark.parametrize("written", ["1000 requests", "1.000 Anfragen", "1 000 requests", "1k requests a day"])
    def test_a_stated_limit_is_read_however_the_number_is_written(self, written):
        proposal = self._stated({"limits": {"mode": "requests", "value": 1000}}, earlier=[f"Limit: {written}"])
        assert proposal["fields"] == {"limits": {"mode": "requests", "value": 1000}}

    @pytest.mark.parametrize("fields,part", [
        ({"limits": {"mode": "requests", "value": 500}}, "limits"),
        ({"limits": {"mode": "requests", "value": 1000}, "guardrails": {"checks": ["pii", "secrets"]}},
         "guardrails"),
        ({"analytics": {"topics": [{"name": "Billing", "description": "Invoices"}]}}, "topics"),
    ])
    def test_a_part_the_user_left_open_is_asked_about_first(self, fields, part):
        with pytest.raises(ProposalInvalid, match="Ask the user first") as raised:
            self._stated(fields)
        assert part in str(raised.value) and "their words leave open" in str(raised.value)

    def test_limits_are_either_or(self):
        proposal = _validate({"limits": {"mode": "requests", "value": 500}}, step="safety", asked=True,
                             reasons=[{"field": "limits", "summary": "500 requests a day"}])
        assert proposal["fields"] == {"limits": {"mode": "requests", "value": 500}}
        assert proposal["reasons"] == [{"field": "limits", "summary": "500 requests a day"}]
        proposal = _validate({"limits": {"mode": "none", "value": 7}}, form={"limits": {"mode": "tokens",
                             "value": 50000}}, step="safety", asked=True)
        assert proposal["fields"] == {"limits": {"mode": "none"}}

    @pytest.mark.parametrize("limits", [{"mode": "tokens"}, {"mode": "requests", "value": 0},
                                        {"mode": "requests", "value": 2.5}, {"mode": "tokens", "value": 10 ** 12}])
    def test_a_limit_needs_a_sensible_number(self, limits):
        with pytest.raises(ProposalInvalid):
            _validate({"limits": limits}, step="safety", asked=True)

    def test_unchanged_limits_are_left_out(self):
        proposal = _validate({"limits": {"mode": "tokens", "value": 50000}},
                             form={"limits": {"mode": "tokens", "value": 50000}}, step="safety", asked=True)
        assert proposal["fields"] == {} and proposal["steps"] == ["safety"]

    def test_guardrails_add_menu_checks_the_agent_lacks(self):
        proposal = _validate({"guardrails": {"checks": ["pii", "pii", "secrets", "moderation", "injection"]}},
                             form={"guardrails": {"enabled": True, "controls": [_on("secrets", "output")]}},
                             ws=_ws(guardrail_menu=["pii", "injection", "secrets"]), step="safety", asked=True)
        assert proposal["fields"] == {"guardrails": _added("pii", "injection")}
        assert proposal["fields"]["guardrails"]["controls"][:2] == [
            {"check": "pii", "stage": "input", "action": "redact"},
            {"check": "pii", "stage": "output", "action": "redact"},
        ]

    def test_a_check_on_at_one_stage_only_can_still_get_its_other_stage(self):
        partial = {"guardrails": {"enabled": True, "controls": [_on("pii", "input")]}}
        proposal = _validate({"guardrails": {"checks": ["pii"]}}, form=partial, step="safety", asked=True)
        assert proposal["fields"] == {"guardrails": _added("pii")}
        whole = {"guardrails": {"enabled": True, "controls": [_on("pii", "input"), _on("pii", "output")]}}
        assert _validate({"guardrails": {"checks": ["pii"]}}, form=whole, step="safety", asked=True)["fields"] == {}

    def test_a_check_the_agent_has_switched_off_is_proposed_again(self):
        proposal = _validate({"guardrails": {"checks": ["pii"]}},
                             form={"guardrails": {"enabled": False, "controls": [_on("pii", "input"),
                                                                                 _on("pii", "output")]}},
                             step="safety", asked=True)
        assert proposal["fields"] == {"guardrails": _added("pii")}

    def test_guardrails_off_on_the_instance_are_left_out(self):
        proposal = _validate({"guardrails": {"checks": ["pii"]}}, ws=_ws(guardrail_menu=[]),
                             step="safety", asked=True)
        assert proposal["fields"] == {} and proposal["dropped"] == []

    def test_without_edit_policy_limits_and_guardrails_are_dropped(self):
        topics = [{"name": "Billing", "description": "Invoices, refunds and failed payments"}]
        proposal = _validate({"limits": {"mode": "requests", "value": 500}, "guardrails": {"checks": ["pii"]},
                              "analytics": {"topics": topics}},
                             ws=_ws(policy_editable=False), step="safety", asked=True)
        assert proposal["fields"] == {"analytics": {"topics": topics}}
        assert proposal["dropped"] == [{"field": "limits", "reason": "not_allowed"},
                                       {"field": "guardrails", "reason": "not_allowed"}]

    def test_topics_are_added_without_duplicates(self):
        proposal = _validate({"analytics": {"topics": [
            {"name": " Billing ", "description": "Invoices"},
            {"name": "billing", "description": "Again"},
            {"name": "Shipping", "description": "Late parcels"},
        ]}}, form={"analytics": {"enabled": True, "topics": ["Shipping"]}}, step="safety", asked=True)
        assert proposal["fields"] == {"analytics": {"topics": [{"name": "Billing", "description": "Invoices"}]}}

    def test_a_topic_a_source_folder_already_is_is_left_out(self):
        proposal = _validate({"analytics": {"topics": [
            {"name": "Deploying", "description": "Docker, Kubernetes"},
            {"name": "Billing", "description": "Invoices"},
        ]}}, ws=_ws(folders=FOLDERS), step="safety", asked=True)
        assert proposal["fields"] == {"analytics": {"topics": [{"name": "Billing", "description": "Invoices"}]}}
        assert proposal["notes"] == []

    def test_the_notes_cap_leaves_room_for_the_servers_own(self):
        form = {"analytics": {"topics": [f"T{i}" for i in range(8)]}}
        two = [{"name": "A", "description": "a"}, {"name": "B", "description": "b"}]
        proposal = _validate({"analytics": {"topics": two}}, form=form, ws=_ws(folders=FOLDERS), step="safety",
                             asked=True, notes=["One", "Two", "Three"])
        assert len(proposal["notes"]) == agent_recipe.MAX_NOTES
        assert proposal["notes"][:2] == ["One", "Two"] and "leave out the folder agents" in proposal["notes"][-1]

    def test_a_hidden_folders_name_can_come_back_as_a_topic(self):
        form = {"analytics": {"hidden_folders": ["deploying"]}}
        topic = {"name": "Deploying", "description": "Docker, Kubernetes"}
        proposal = _validate({"analytics": {"topics": [topic]}}, form=form, ws=_ws(folders=FOLDERS),
                             step="safety", asked=True)
        assert proposal["fields"] == {"analytics": {"topics": [topic]}}

    def test_topics_past_the_free_room_say_which_folders_they_push_out(self):
        form = {"analytics": {"topics": [f"T{i}" for i in range(8)]}}
        two = [{"name": "A", "description": "a"}, {"name": "B", "description": "b"}]
        proposal = _validate({"analytics": {"topics": two}}, form=form, ws=_ws(folders=FOLDERS),
                             step="safety", asked=True)
        assert proposal["fields"]["analytics"]["topics"] == two
        # 8 topics and 6 folders leave one free option: the second topic pushes out the smallest folder.
        assert proposal["notes"] == [
            "Insights offers 15 topics, source folders included: these leave out the folder agents."
        ]

    @pytest.mark.parametrize("ws,form", [
        (_ws(insights=False), {}),
        (_ws(), {"analytics": {"enabled": False}}),
    ])
    def test_topics_need_insights_on(self, ws, form):
        proposal = _validate({"analytics": {"topics": [{"name": "Billing", "description": "Invoices"}]}},
                             form=form, ws=ws, step="safety", asked=True)
        assert proposal["fields"] == {}

    @pytest.mark.parametrize("topics", [
        [{"name": f"T{i}", "description": "d"} for i in range(5)],
        [{"name": "x" * 61, "description": "d"}],
        [{"name": "Billing", "description": "x" * 151}],
        [{"name": "Billing", "description": "账" * 51}],
        [{"name": "None of these", "description": "d"}],
        [{"name": "Billing", "description": ""}],
    ])
    def test_topics_follow_the_analytics_rules(self, topics):
        with pytest.raises(ProposalInvalid):
            _validate({"analytics": {"topics": topics}}, step="safety", asked=True)

    def test_topics_fit_the_room_left(self):
        form = {"analytics": {"enabled": True, "topics": [f"T{i}" for i in range(14)]}}
        two = [{"name": "A", "description": "a"}, {"name": "B", "description": "b"}]
        with pytest.raises(ProposalInvalid, match="room for 1"):
            _validate({"analytics": {"topics": two}}, form=form, step="safety", asked=True)


@pytest.mark.unit
def test_the_loop_sends_an_unasked_policy_proposal_back_to_ask():
    from docsgpt.drafter.runner import run_draft
    from tests.drafter.fakes import calls, FakeLLM, tool_call

    fake = FakeLLM(
        calls(tool_call("submit_proposal", {"message": "Set.", "fields": {"limits": {"mode": "requests",
                                                                                     "value": 500}}})),
        calls(tool_call("ask_user", QUESTIONS)),
    )
    events = list(run_draft(_req({}, "Continue with Limits and safety.", step="safety"), AGENT_RECIPE, _ws(),
                            {"id": "m", "display_name": "M", "supports_tools": True}, llm_factory=fake.factory))
    assert [e["type"] for e in events][-1] == "questions"
    assert "Ask the user first" in fake.calls[1]["messages"][-1]["content"]
