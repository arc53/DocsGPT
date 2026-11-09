"""The agent recipe's improve mode with Insights: the gap summary it reads, its read tools, and the proposal's gaps
and groundedness guardrail."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from docsgpt.drafter import agent_recipe
from docsgpt.drafter.agent_recipe import (
    AGENT_RECIPE,
    AgentWorkspace,
    context_data,
    INSIGHTS_READS,
    instructions,
    parse_context,
    read_tools_for,
    validate,
    WORKSPACE_READS,
)
from docsgpt.drafter.gaps import NEEDED
from docsgpt.drafter.read_tools import run_read_tool
from docsgpt.drafter.recipe import DraftRequest, ProposalInvalid
from docsgpt.drafter.runner import run_draft
from tests.drafter import insights_seed as seed
from tests.drafter.fakes import calls, FakeLLM, tool_call

SOURCE_ID = "22222222-2222-2222-2222-222222222222"
MODEL = {"id": "m", "display_name": "M", "supports_tools": True}
ROWS = [
    {"topic": "Order status", "gap_type": "needs account data", "expected": 31, "turns": 96, "previous": None},
    {"topic": "Returns & claims", "gap_type": "docs missing", "expected": 23, "turns": 160, "previous": 19},
    {"topic": "Delivery windows", "gap_type": "confidently ungrounded", "expected": 9, "turns": 120, "previous": 5},
]
SUMMARY = {"available": True, "reason": None, "conversations": 412, "needed": 10, "days": 30, "rows": ROWS}


class FakeReader:
    def __init__(self):
        self.asked = []

    def gap_examples(self, gap_type, topic=None):
        self.asked.append(("examples", gap_type, topic))
        return ["How long do I have to file a damage claim?", "Can I return a broken pallet?"]

    def conversations(self, label, topic=None):
        self.asked.append(("conversations", label, topic))
        return [{"question": "Let me talk to a person", "answer": "I can help with that."}]


def _ws(gaps=SUMMARY, **kwargs) -> AgentWorkspace:
    ws = AgentWorkspace(
        sources=[{"id": SOURCE_ID, "name": "Claims policy"}],
        prompts=[{"id": p, "name": p, "kind": "built-in"} for p in ("default", "creative", "strict")],
        guardrail_menu=["pii", "injection", "groundedness", "secrets"],
        agent={"id": "a1", "name": "Meridian Shipping Help", "status": "published", "agent_type": "classic"},
        gaps=gaps,
        insights_reader=FakeReader() if gaps and gaps.get("available") else None,
    )
    for key, value in kwargs.items():
        setattr(ws, key, value)
    return ws


def _req(context=None, *messages) -> DraftRequest:
    ctx = parse_context({"agent_id": "a1", "form": {"name": "Meridian Shipping Help"}, **(context or {})})
    user = [{"role": "user", "content": m} for m in (messages or ("Fix the Docs gap in Returns & claims",))]
    return DraftRequest("alice", "agent", user, ctx, "drafter:t")


def _validate(gaps=None, fields=None, ws=None, context=None):
    args = {"message": "Done.", "fields": fields or {}}
    if gaps is not None:
        args["gaps"] = gaps
    return validate(args, _req(context), ws or _ws())


@pytest.mark.unit
class TestContext:
    def test_the_focus_gap_and_conversation_are_read_in_improve_mode_only(self):
        ctx = parse_context({"gap": {"topic": " Returns ", "gap_type": "docs missing"}, "conversation_id": " c1 "})
        assert ctx["gap"] == {"topic": "Returns", "gap_type": "docs missing"} and ctx["conversation_id"] == "c1"
        assert parse_context({"gap": {"gap_type": "docs missing"}})["gap"] == {"topic": None,
                                                                                "gap_type": "docs missing"}
        stepped = parse_context({"step": "basics", "gap": {"gap_type": "docs missing"}, "conversation_id": "c1"})
        assert stepped["gap"] is None and stepped["conversation_id"] is None

    @pytest.mark.parametrize("gap", [{"gap_type": "other"}, {"gap_type": "nope"}, "docs missing", {"topic": "x"}])
    def test_a_gap_that_is_not_a_summary_gap_type_is_left_out(self, gap):
        assert parse_context({"gap": gap})["gap"] is None

    def test_the_reading_status_and_the_workspace_carry_the_summary(self):
        ws = _ws()
        assert ws.counts()["insights_conversations"] == 412
        assert ws.summary()["insights"] == {"days": 30, "analysed_conversations": 412, "gaps": ROWS}
        unavailable = _ws(gaps={**SUMMARY, "available": False, "reason": "not_enough", "rows": []})
        assert "insights_conversations" not in unavailable.counts() and "insights" not in unavailable.summary()

    def test_the_form_data_has_the_focus_conversation_and_guardrail(self):
        conversation = {"question": "Claim deadline?", "answer": "Not sure.", "labels": ["docs_gap"],
                        "gap_type": "docs missing"}
        ws = _ws(conversation=conversation)
        data = context_data(_req({"gap": {"topic": "Returns & claims", "gap_type": "docs missing"}}), ws)
        assert data["focus_gap"] == {"topic": "Returns & claims", "gap_type": "docs missing"}
        assert data["conversation_from_logs"] == conversation
        assert data["guardrail_from_insights"] == {"available": True, "check": "groundedness"}
        assert context_data(_req(), _ws(policy_editable=False))["guardrail_from_insights"]["why"] == "no_access"
        no_ungrounded = _ws(gaps={**SUMMARY, "rows": ROWS[:2]})
        assert context_data(_req(), no_ungrounded)["guardrail_from_insights"]["why"] == "no_ungrounded_gap"
        assert "guardrail_from_insights" not in context_data(_req(), _ws(gaps=None))


@pytest.mark.unit
class TestInstructionsAndTools:
    def test_insights_rules_and_tools_only_with_the_summary(self):
        with_summary = instructions(_req(), _ws())
        assert agent_recipe.INSIGHTS_RULES in with_summary and agent_recipe.NEVER_POLICY_INSIGHTS in with_summary
        without = instructions(_req(), _ws(gaps=None))
        assert agent_recipe.INSIGHTS_RULES not in without and agent_recipe.NEVER_POLICY in without
        assert read_tools_for(_req(), _ws()) == WORKSPACE_READS + INSIGHTS_READS
        assert read_tools_for(_req(), _ws(gaps=None)) == WORKSPACE_READS
        assert AGENT_RECIPE.offered_tools(_req(), _ws(gaps=None)) == WORKSPACE_READS
        stepped = DraftRequest("alice", "agent", [{"role": "user", "content": "x"}],
                               parse_context({"step": "basics"}), "t")
        assert read_tools_for(stepped, _ws()) == WORKSPACE_READS

    def test_a_conversation_from_logs_adds_its_rules(self):
        ws = _ws(conversation={"question": "q", "answer": "a", "labels": [], "gap_type": None})
        assert agent_recipe.CONVERSATION_RULES in instructions(_req(), ws)
        assert agent_recipe.CONVERSATION_RULES not in instructions(_req(), _ws())

    def test_the_read_tools_return_what_the_panel_shows(self):
        ws = _ws()
        result = run_read_tool("get_gap_examples", ws, {"gap_type": "docs missing", "topic": "Returns & claims"})
        assert result["questions"] == result["shown"] and len(result["questions"]) == 2
        result = run_read_tool("get_conversations", ws, {"label": "asks_human"})
        assert result == {"conversations": [{"question": "Let me talk to a person", "answer": "I can help with that."}],
                          "shown": ["Let me talk to a person"]}
        assert ws.insights_reader.asked == [("examples", "docs missing", "Returns & claims"),
                                            ("conversations", "asks_human", None)]

    def test_the_read_tools_refuse_bad_arguments_and_a_missing_reader(self):
        ws = _ws()
        assert "error" in run_read_tool("get_gap_examples", ws, {"gap_type": "other"})
        assert "error" in run_read_tool("get_conversations", ws, {"label": "tag:secret"})
        assert "error" in run_read_tool("get_gap_examples", _ws(gaps=None), {"gap_type": "docs missing"})


@pytest.mark.unit
class TestProposalGaps:
    def test_counts_come_from_the_summary_and_fields_from_the_proposal(self):
        proposal = _validate(
            gaps=[{"topic": "Order status", "gap_type": "needs account data", "expected": 999,
                   "example": "Where is shipment MRD-48213?", "fields": ["starters", "name", "name"]}],
            fields={"name": "Meridian Help"},
        )
        assert proposal["gaps"] == [{
            "topic": "Order status", "gap_type": "needs account data", "expected": 31, "turns": 96,
            "previous": None, "example": "Where is shipment MRD-48213?", "fields": ["name"], "needs": None,
            "links": []}]

    def test_a_gap_not_in_the_summary_goes_back_to_the_model(self):
        with pytest.raises(ProposalInvalid, match="not in the gap summary"):
            _validate(gaps=[{"topic": "Order status", "gap_type": "docs missing"}])

    def test_links_are_checked_and_named(self):
        links = [{"kind": "source", "id": SOURCE_ID}, {"kind": "source", "id": "not-mine"},
                 {"kind": "logs", "label": "docs_gap"}, {"kind": "logs", "label": "topic:Returns & claims"},
                 {"kind": "logs", "label": "tag:abc"}]
        [gap] = _validate(gaps=[{"topic": "Returns & claims", "gap_type": "docs missing", "links": links,
                                 "needs": "Add a page on claim deadlines, then sync the source."}])["gaps"]
        assert gap["links"] == [{"kind": "source", "id": SOURCE_ID, "name": "Claims policy"},
                                {"kind": "logs", "label": "docs_gap"},
                                {"kind": "logs", "label": "topic:Returns & claims"}]
        assert gap["needs"] == "Add a page on claim deadlines, then sync the source." and gap["previous"] == 19

    def test_at_most_three_gaps_each_once_and_none_without_the_summary(self):
        row = {"topic": "Order status", "gap_type": "needs account data"}
        many = [row, row] + [{"topic": r["topic"], "gap_type": r["gap_type"]} for r in ROWS[1:]] * 2
        assert len(_validate(gaps=many)["gaps"]) == 3
        assert _validate(gaps=[row], ws=_ws(gaps=None))["gaps"] == []
        stepped = validate({"message": "m", "fields": {}, "gaps": [row]},
                           DraftRequest("alice", "agent", [{"role": "user", "content": "x"}],
                                        parse_context({"step": "basics"}), "t"), _ws())
        assert "gaps" not in stepped

    def test_an_agent_without_topics_matches_on_gap_type(self):
        ws = _ws(gaps={**SUMMARY, "rows": [{**ROWS[1], "topic": None}]})
        [gap] = _validate(gaps=[{"topic": "Returns", "gap_type": "docs missing"}], ws=ws)["gaps"]
        assert gap["topic"] is None and gap["expected"] == 23


@pytest.mark.unit
class TestGuardrailsFromInsights:
    def test_groundedness_only_for_an_ungrounded_gap(self):
        proposal = _validate(fields={"guardrails": {"checks": ["groundedness", "pii"]},
                                     "limits": {"mode": "requests", "value": 5},
                                     "analytics": {"topics": [{"name": "X", "description": "Y"}]}})
        assert proposal["fields"] == {"guardrails": {"controls": [
            {"check": "groundedness", "stage": "output", "action": "flag"}]}}
        assert _validate(fields={"guardrails": {"checks": ["groundedness"]}},
                         ws=_ws(gaps={**SUMMARY, "rows": ROWS[:2]}))["fields"] == {}

    def test_a_caller_without_policy_access_gets_it_dropped(self):
        proposal = _validate(fields={"guardrails": {"checks": ["groundedness"]}}, ws=_ws(policy_editable=False))
        assert proposal["fields"] == {} and proposal["dropped"] == [{"field": "guardrails", "reason": "not_allowed"}]

    def test_without_the_summary_improve_mode_sets_no_guardrails(self):
        proposal = _validate(fields={"guardrails": {"checks": ["groundedness"]}}, ws=_ws(gaps=None))
        assert proposal["fields"] == {} and proposal["dropped"] == []


# ---------------------------------------------------------------------------
# Against Postgres: the load and the live reads
# ---------------------------------------------------------------------------


@pytest.fixture
def insights_on(monkeypatch):
    from docsgpt.core.settings import settings

    monkeypatch.setattr(settings, "DECISION_ANALYTICS_ENABLED", True)
    monkeypatch.setattr("docsgpt.decisions.available", lambda: True)


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.storage.db.session.db_readonly", _yield), patch.object(agent_recipe, "load_models"):
        yield


def _labelled_agent(conn):
    bot = seed.agent(conn, owner="alice")
    aid = str(bot["id"])
    for i in range(NEEDED):
        seed.turn(conn, aid, f"Claim deadline {i}?", gap={"docs missing": 0.9})
    cid, _ = seed.turn(conn, aid, "Hello")
    seed.turn(conn, aid, "Where is MRD-48213?", cid=cid, position=1, gap={"needs account data": 0.9},
              response="I can't look that up.")
    return bot, cid


def _load(conn, user, context):
    with _db(conn):
        return AGENT_RECIPE.load_workspace(user, parse_context({"form": {}, **context}))


@pytest.mark.unit
def test_improve_mode_loads_the_summary_reader_and_conversation(pg_conn, insights_on):
    bot, cid = _labelled_agent(pg_conn)
    ws = _load(pg_conn, "alice", {"agent_id": str(bot["id"]), "conversation_id": cid})
    assert ws.gaps["available"] is True and ws.gaps["conversations"] == NEEDED + 1
    assert ws.gaps["rows"][0] == {"topic": None, "gap_type": "docs missing", "expected": 9, "turns": NEEDED + 2,
                                  "previous": None}
    assert ws.insights_reader is not None and ws.insights_reader.agent_id == str(bot["id"])
    # the labelled turn of the conversation, not its greeting
    assert ws.conversation == {"question": "Where is MRD-48213?", "answer": "I can't look that up.", "labels": [],
                               "gap_type": "needs account data"}
    with _db(pg_conn):
        examples = run_read_tool("get_gap_examples", ws, {"gap_type": "needs account data"})
        turns = run_read_tool("get_conversations", ws, {"label": "docs_gap"})
    assert examples["questions"] == ["Where is MRD-48213?"]
    assert len(turns["conversations"]) == 5 and turns["shown"][0].startswith("Claim deadline")


@pytest.mark.unit
def test_a_viewer_or_a_guided_step_reads_no_insights(pg_conn, insights_on):
    import uuid

    from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
    from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
    from docsgpt.storage.db.repositories.teams import TeamsRepository

    bot, cid = _labelled_agent(pg_conn)
    team = str(TeamsRepository(pg_conn).create("Acme", f"acme-{uuid.uuid4().hex[:8]}", "alice")["id"])
    TeamMembersRepository(pg_conn).add_member(team, "vic")
    TeamResourceGrantsRepository(pg_conn).grant(team, "agent", str(bot["id"]), "alice", "alice",
                                                access_level="viewer")
    viewer = _load(pg_conn, "vic", {"agent_id": str(bot["id"]), "conversation_id": cid})
    assert viewer.gaps is None and viewer.insights_reader is None and viewer.conversation is None
    stepped = _load(pg_conn, "alice", {"agent_id": str(bot["id"]), "step": "basics"})
    assert stepped.gaps is None and stepped.insights_reader is None


@pytest.mark.unit
def test_a_conversation_of_another_agent_is_not_read(pg_conn, insights_on):
    bot, _ = _labelled_agent(pg_conn)
    other = seed.agent(pg_conn, owner="alice")
    foreign, _ = seed.turn(pg_conn, str(other["id"]), "Someone else's question")
    ws = _load(pg_conn, "alice", {"agent_id": str(bot["id"]), "conversation_id": foreign})
    assert ws.conversation is None
    assert _load(pg_conn, "alice", {"agent_id": str(bot["id"]), "conversation_id": "not-a-uuid"}).conversation \
        is None


@pytest.mark.unit
def test_a_turn_reads_insights_and_shows_the_questions_it_read(pg_conn, insights_on):
    bot, _ = _labelled_agent(pg_conn)
    ctx = parse_context({"agent_id": str(bot["id"]), "form": {"name": "Shipping help"},
                         "gap": {"topic": None, "gap_type": "docs missing"}})
    with _db(pg_conn):
        ws = AGENT_RECIPE.load_workspace("alice", ctx)
    req = DraftRequest("alice", "agent", [{"role": "user", "content": "Fix: Docs gap"}], ctx, "drafter:t")
    proposal = {"message": "The docs miss claim deadlines.", "fields": {},
                "gaps": [{"gap_type": "docs missing", "example": "Claim deadline 1?",
                          "needs": "Add a page on claim deadlines.", "links": [{"kind": "logs", "label": "docs_gap"}]}]}
    fake = FakeLLM(calls(tool_call("get_gap_examples", {"gap_type": "docs missing"})),
                   calls(tool_call("submit_proposal", proposal)))
    with _db(pg_conn):
        events = list(run_draft(req, AGENT_RECIPE, ws, MODEL, llm_factory=fake.factory))
    assert events[0] == {"type": "status", "step": "reading", "counts": {**ws.counts(),
                                                                         "insights_conversations": NEEDED + 1}}
    [read] = [e for e in events if e["type"] == "read"]
    assert read["kind"] == "questions" and len(read["items"]) == 5
    offered = [t["function"]["name"] for t in fake.calls[0]["tools"]]
    assert "get_gap_examples" in offered and "get_conversations" in offered
    system, first = fake.calls[0]["messages"][0]["content"], fake.calls[0]["messages"][1]["content"]
    assert agent_recipe.INSIGHTS_RULES in system and '"focus_gap"' in first and '"analysed_conversations"' in first
    [gap] = events[-1]["proposal"]["gaps"]
    assert (gap["gap_type"], gap["expected"], gap["links"]) == ("docs missing", 9, [{"kind": "logs",
                                                                                     "label": "docs_gap"}])
