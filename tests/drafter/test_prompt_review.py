"""The prompt recipe's review: a checklist run by the model, the server's own checks, and the agents using it."""

from __future__ import annotations

import uuid

import pytest

from docsgpt.agents.default_tools import default_tool_id
from docsgpt.drafter.composer_ref import persona_frame
from docsgpt.drafter.prompt_recipe import (
    context_data,
    instructions,
    load_workspace,
    parse_context,
    PROMPT_RECIPE,
    validate,
)
from docsgpt.drafter.prompt_review import MAX_FINDINGS, PromptWorkspace, read_agents, REVIEW_CHECKS
from docsgpt.drafter.recipe import BadDraftRequest, DraftRequest, ProposalInvalid
from docsgpt.drafter.runner import build_messages, run_draft
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from tests.drafter.fakes import calls, FakeLLM, tool_call

PERSONA = (
    "You are the support assistant for Meridian Freight Group.\n"
    "Today's date is shown above; always mention it when you talk about deadlines.\n"
    "If the documents don't cover a question, answer from your general knowledge freely.\n"
    "For anything you can't help with, tell them to email us at [support email].\n"
    "Keep answers short and friendly."
)
FLEET = {"id": "a1", "name": "Fleet Desk", "agent_type": "classic", "sources": 0, "tools": []}
QUOTES = {"id": "a2", "name": "Quote Bot", "agent_type": "agentic", "sources": 2, "tools": ["Memory"]}
MODEL = {"id": "m", "display_name": "M", "supports_tools": True}


def _req(content=PERSONA, prompt_id="p1", message="Review it") -> DraftRequest:
    context = parse_context({"mode": "review", "prompt": {"id": prompt_id, "name": "Meridian support",
                                                          "content": content}})
    return DraftRequest("alice", "prompt", [{"role": "user", "content": message}], context, "drafter:t")


def _ws(*agents) -> PromptWorkspace:
    return PromptWorkspace(agents=[dict(a) for a in agents])


def _edit(find, replace, reason="Because."):
    return {"find": find, "replace": replace, "reason": reason}


def _finding(check, severity="fix", title="Title", detail="Detail.", **extra):
    return {"check": check, "severity": severity, "title": title, "detail": detail, **extra}


DATE_EDIT = _edit("Today's date is shown above; always mention it when you talk about deadlines.\n", "",
                  "DocsGPT already adds the date.")
FREE_EDIT = _edit("answer from your general knowledge freely", "say so, then answer from general knowledge",
                  "DocsGPT answers from the knowledge first.")


def _review(edits=(), findings=(), content=PERSONA, ws=None, **extra):
    args = {"message": "3 things to fix.", "edits": list(edits), "findings": list(findings), **extra}
    return validate(args, _req(content), ws or _ws())


def _model_findings(proposal):
    return [f for f in proposal["findings"] if f["source"] == "model"]


def _server_findings(proposal):
    return [f for f in proposal["findings"] if f["source"] == "server"]


@pytest.mark.unit
class TestContext:
    def test_review_is_a_mode(self):
        ctx = parse_context({"mode": "review", "prompt": {"id": "p1", "name": "N", "content": "You help."},
                             "starter": "website", "skip_questions": True})
        assert ctx == {"mode": "review", "prompt": {"id": "p1", "name": "N", "content": "You help."},
                       "starter": None, "skip_questions": False}

    def test_it_needs_text(self):
        with pytest.raises(BadDraftRequest):
            parse_context({"mode": "review", "prompt": {"id": "p1", "content": " "}})

    def test_it_never_asks(self):
        req = _req()
        assert PROMPT_RECIPE.asks(req) is False
        system = build_messages(req, PROMPT_RECIPE, _ws(), tool_mode=True, allow_questions=False)[0]
        assert "ask_user" not in system["content"]

    def test_the_model_reads_the_servers_checks(self):
        data = context_data(_req(), _ws())
        assert data["mode"] == "review"
        assert data["prompt"]["kind"] == "persona"
        assert {"code": "placeholder", "text": "[support email]", "line": 4} in data["server_checks"]
        assert {"code": "repeats_builtin", "topic": "date", "line": 2} in data["server_checks"]

    def test_improve_and_write_read_no_server_checks(self):
        req = DraftRequest("alice", "prompt", [{"role": "user", "content": "x"}],
                           parse_context({"mode": "improve", "prompt": {"content": PERSONA}}), "t")
        assert "server_checks" not in context_data(req, _ws())

    def test_the_workspace_shows_the_agents_using_it(self):
        assert _ws(FLEET).summary() == {"agents_using_this_prompt": [FLEET]}
        assert _ws().summary() == {"agents_using_this_prompt": []}

    def test_it_reads_no_workspace_status(self):
        assert PROMPT_RECIPE.reads_workspace is False


@pytest.mark.unit
class TestInstructions:
    def test_the_checklist_is_stated(self):
        text = instructions(_req(), _ws(FLEET))
        for code in REVIEW_CHECKS:
            assert f"{code}:" in text, code
        assert "can't transfer the chat to a person" in text
        assert "change only what the user asked for" not in text

    def test_agents_fit_is_only_offered_with_agents(self):
        assert "agents_fit:" not in instructions(_req(), _ws())

    def test_docsgpts_own_instructions_are_the_real_frame(self):
        assert persona_frame("classic") in instructions(_req(), _ws())
        assert persona_frame("agentic") not in instructions(_req(), _ws())
        both = instructions(_req(), _ws(FLEET, QUOTES))
        assert persona_frame("classic") in both and persona_frame("agentic") in both

    def test_one_frame_for_types_that_share_it(self):
        research = dict(QUOTES, id="a3", agent_type="research")
        text = instructions(_req(), _ws(QUOTES, research))
        assert text.count(persona_frame("agentic")) == 1
        assert persona_frame("classic") not in text


@pytest.mark.unit
class TestFindings:
    def test_findings_point_at_edits_renumbered_in_text_order(self):
        proposal = _review(
            edits=[FREE_EDIT, DATE_EDIT],
            findings=[_finding("builtin_rules", edit=1), _finding("builtin_lines", edit=2),
                      _finding("placeholders", ask={"label": "Add the address", "prefill": "The support email is "})],
        )
        assert [e["id"] for e in proposal["edits"]] == ["e1", "e2"]
        assert proposal["edits"][0]["find"].startswith("Today's date")
        found = {f["check"]: f for f in proposal["findings"]}
        assert found["builtin_rules"]["edit"] == "e2"
        assert found["builtin_lines"]["edit"] == "e1"
        assert found["placeholders"]["edit"] is None
        assert found["placeholders"]["ask"] == {"label": "Add the address", "prefill": "The support email is "}
        assert [f["id"] for f in proposal["findings"]] == ["f1", "f2", "f3"]
        assert all(f["source"] == "model" and f["code"] is None and f["text"] is None for f in proposal["findings"])

    def test_the_proposal_shape(self):
        proposal = _review(edits=[DATE_EDIT], findings=[
            _finding("builtin_lines", edit=1), _finding("placeholders", ask={"label": "Add", "prefill": "It is "})])
        assert set(proposal) == {"mode", "message", "edits", "findings", "passed", "warnings", "checks",
                                 "suggestions"}
        assert proposal["mode"] == "review" and proposal["suggestions"] == []
        assert set(proposal["findings"][0]) == {"id", "check", "severity", "title", "detail", "edit", "ask",
                                                "agent", "source", "code", "text"}

    @pytest.mark.parametrize("findings", [
        [],
        [_finding("builtin_lines")],
    ])
    def test_an_edit_without_a_finding_goes_back(self, findings):
        with pytest.raises(ProposalInvalid, match="belong"):
            _review(edits=[DATE_EDIT], findings=findings)

    def test_an_edit_two_findings_claim_goes_back(self):
        with pytest.raises(ProposalInvalid, match="one finding"):
            _review(edits=[DATE_EDIT], findings=[_finding("builtin_lines", edit=1), _finding("tone", edit=1)])

    def test_a_finding_pointing_past_the_edits_goes_back(self):
        with pytest.raises(ProposalInvalid, match="edit 3"):
            _review(edits=[DATE_EDIT], findings=[_finding("builtin_lines", edit=1), _finding("tone", edit=3)])

    def test_a_finding_on_a_no_op_edit_has_no_edit(self):
        same = _edit("Keep answers short and friendly.", "Keep answers short and friendly.")
        proposal = _review(edits=[same], findings=[_finding("tone", "look", edit=1)])
        assert proposal["edits"] == [] and _model_findings(proposal)[0]["edit"] is None

    def test_bad_edits_go_back_as_in_improve(self):
        with pytest.raises(ProposalInvalid, match="not found"):
            _review(edits=[_edit("Nope", "Yes")], findings=[_finding("tone", edit=1)])

    def test_tool_variables_need_the_users_ask(self):
        add = _edit("Keep answers short and friendly.", "Keep answers short. {{ tools.memory.memory_view }}")
        with pytest.raises(ProposalInvalid, match="tools"):
            _review(edits=[add], findings=[_finding("tone", edit=1)])

    def test_an_unknown_check_goes_back(self):
        with pytest.raises(ProposalInvalid, match="check"):
            _review(findings=[_finding("spelling")])

    def test_agents_fit_needs_agents(self):
        with pytest.raises(ProposalInvalid, match="agents_fit"):
            _review(findings=[_finding("agents_fit")])
        assert _model_findings(_review(findings=[_finding("agents_fit", "look")], ws=_ws(FLEET)))[0]["check"] \
            == "agents_fit"

    def test_a_finding_needs_a_title(self):
        with pytest.raises(ProposalInvalid, match="title"):
            _review(findings=[_finding("tone", title="  ")])

    def test_an_agent_must_be_one_loaded(self):
        proposal = _review(findings=[_finding("agents_fit", "look", agent="A1 "), _finding("scope", agent="zz")],
                           ws=_ws(FLEET, QUOTES))
        found = {f["check"]: f for f in _model_findings(proposal)}
        assert found["agents_fit"]["agent"] == {"id": "a1", "name": "Fleet Desk"}
        assert found["scope"]["agent"] is None

    def test_an_ask_is_kept_on_a_fix_or_a_look_without_an_edit(self):
        ask = {"label": "Add the address", "prefill": "The support email is "}
        proposal = _review(edits=[DATE_EDIT], findings=[
            _finding("builtin_lines", edit=1, ask=ask), _finding("tone", "look", ask=ask),
            _finding("hand_off", ask=ask), _finding("placeholders", ask={"label": " ", "prefill": "x"})])
        asks = {f["check"]: f["ask"] for f in _model_findings(proposal)}
        assert asks == {"builtin_lines": None, "tone": ask, "hand_off": ask, "placeholders": None}
        assert "ask: when a fix or a look needs a detail only the user knows" in instructions(_req(), _ws())

    def test_a_hand_off_finding_with_neither_edit_nor_ask_goes_back_once(self):
        # prompt_review_docs_r1: a "look" about a missing contact came back with no way to add one.
        finding = _finding("hand_off", "look", title="No real contact for questions the docs don't cover")
        with pytest.raises(ProposalInvalid, match="hand_off") as raised:
            _review(findings=[finding])
        assert "ask" in str(raised.value)
        req = _req()
        req.can_correct = False
        proposal = validate({"message": "1 to look at.", "edits": [], "findings": [finding]}, req, _ws())
        assert _model_findings(proposal)[0]["ask"] is None
        assert "always has an ask" in instructions(_req(), _ws())

    def test_check_codes_are_kept_out_of_what_the_user_reads(self):
        proposal = _review(findings=[_finding(
            "builtin_rules", title="Missing Boundaries section (server check: boundaries_missing)",
            detail="The template lacks it (boundaries_missing). Add it (see notes).")],
            message="1 to fix (check: builtin_rules).")
        finding = _model_findings(proposal)[0]
        assert finding["title"] == "Missing Boundaries section"
        assert finding["detail"] == "The template lacks it. Add it (see notes)."
        assert proposal["message"] == "1 to fix."
        assert "never name a check code" in instructions(_req(), _ws())

    def test_an_edit_that_adds_a_placeholder_goes_back_to_the_model(self):
        with pytest.raises(ProposalInvalid, match=r"\[phone number\]"):
            _review(edits=[_edit("Keep answers short and friendly.", "Keep answers short. Call [phone number].")],
                    findings=[_finding("hand_off", edit=1)])

    def test_unknown_severity_is_a_look(self):
        assert _model_findings(_review(findings=[_finding("tone", "urgent")]))[0]["severity"] == "look"

    def test_fixes_come_before_looks(self):
        proposal = _review(findings=[_finding("tone", "look"), _finding("scope"), _finding("audience", "look")],
                           content=PERSONA.replace("[support email]", "help@meridian.example"))
        assert [(f["id"], f["check"], f["source"]) for f in proposal["findings"]] == [
            ("f1", "scope", "model"), ("f2", "builtin_lines", "server"), ("f3", "tone", "model"),
            ("f4", "audience", "model")]

    def test_texts_are_capped(self):
        proposal = _review(findings=[_finding("tone", title="t" * 500, detail="d" * 2000,
                                              ask={"label": "l" * 200, "prefill": "p" * 900})])
        finding = _model_findings(proposal)[0]
        assert len(finding["title"]) <= 120 and len(finding["detail"]) <= 400
        assert len(finding["ask"]["label"]) <= 60 and len(finding["ask"]["prefill"]) <= 200

    def test_too_many_findings_go_back(self):
        with pytest.raises(ProposalInvalid, match=str(MAX_FINDINGS)):
            _review(findings=[_finding("tone", "look", title=f"T{i}") for i in range(MAX_FINDINGS + 1)])

    def test_mode_checks_come_with_the_edits(self):
        add = _edit("Keep answers short and friendly.", "Keep answers short. Say {{ system.date }}.")
        proposal = _review(edits=[add], findings=[_finding("tone", edit=1)])
        assert proposal["checks"] == ["to_template"]

    def test_malformed_findings_are_skipped(self):
        proposal = _review(findings=["x", 5, _finding("tone", "look")])
        assert [f["check"] for f in _model_findings(proposal)] == ["tone"]


@pytest.mark.unit
class TestServerFindings:
    def test_checks_the_model_left_out_are_added(self):
        proposal = _review(findings=[_finding("tone", "look")])
        assert [(f["check"], f["severity"], f["code"], f["text"]) for f in _server_findings(proposal)] == [
            ("placeholders", "fix", "placeholder", "[support email]"),
            ("builtin_lines", "fix", "repeats_builtin", "date"),
        ]
        server = _server_findings(proposal)[0]
        assert (server["title"], server["detail"], server["edit"], server["ask"], server["agent"]) == \
            ("", "", None, None, None)

    def test_a_check_the_model_reported_is_not_added_twice(self):
        proposal = _review(edits=[DATE_EDIT], findings=[_finding("builtin_lines", edit=1), _finding("placeholders")])
        assert _server_findings(proposal) == []

    def test_template_checks_map_to_builtin_rules(self):
        content = "You help {{ passthrough.company }}. {{ tools.crm.lookup }}"
        proposal = _review(content=content)
        assert [(f["check"], f["severity"], f["code"], f["text"]) for f in proposal["findings"]] == [
            ("builtin_rules", "fix", "boundaries_missing", None),
            ("builtin_rules", "fix", "citations_missing", None),
            ("builtin_rules", "look", "tool_variables", "{{ tools.crm.lookup }}"),
        ]

    def test_an_invalid_template_maps_to_builtin_rules(self):
        proposal = _review(content="You help {{ x }} {% if y %}")
        assert proposal["findings"][0]["code"] == "template_invalid"
        assert proposal["findings"][0]["check"] == "builtin_rules"

    def test_server_findings_fill_up_to_the_cap(self):
        content = PERSONA + "\n" + "\n".join(f"Ask [blank {i}]." for i in range(20))
        proposal = _review(content=content, findings=[_finding("tone", "look", title=f"T{i}") for i in range(10)])
        assert len(proposal["findings"]) == MAX_FINDINGS
        assert len(_model_findings(proposal)) == 10
        assert [f["id"] for f in proposal["findings"]] == [f"f{i}" for i in range(1, MAX_FINDINGS + 1)]


@pytest.mark.unit
class TestPassed:
    def test_every_check_without_a_finding_passes(self):
        proposal = _review(content="You help Meridian Freight customers.")
        assert proposal["findings"] == []
        assert proposal["passed"] == ["audience", "scope", "hand_off", "unknowns", "tone", "placeholders",
                                      "builtin_rules", "builtin_lines"]

    def test_agents_fit_counts_with_agents(self):
        proposal = _review(content="You help Meridian Freight customers.", ws=_ws(FLEET))
        assert len(proposal["passed"]) == 9 and proposal["passed"][-1] == "agents_fit"

    def test_checks_with_findings_do_not_pass(self):
        proposal = _review(findings=[_finding("tone", "look")])
        assert proposal["passed"] == ["audience", "scope", "hand_off", "unknowns", "builtin_rules"]

    def test_a_server_finding_cut_by_the_cap_still_fails_its_check(self):
        content = "You help.\n" + "\n".join(f"Ask [blank {i}]." for i in range(20))
        proposal = _review(content=content, findings=[_finding("tone", "look", title=f"T{i}") for i in range(12)])
        assert _server_findings(proposal) == []
        assert "placeholders" not in proposal["passed"]


@pytest.mark.unit
class TestTurn:
    def test_a_review_turn_ends_in_a_review_proposal(self):
        fake = FakeLLM(calls(tool_call("submit_proposal", {
            "message": "1 thing to fix.", "edits": [DATE_EDIT],
            "findings": [_finding("builtin_lines", edit=1)]})))
        events = list(run_draft(_req(), PROMPT_RECIPE, _ws(FLEET), MODEL, llm_factory=fake.factory))
        assert [t["function"]["name"] for t in fake.calls[0]["tools"]] == ["submit_proposal"]
        assert not any(e.get("step") == "reading" for e in events)
        proposal = events[-1]["proposal"]
        assert proposal["mode"] == "review"
        assert proposal["findings"][0]["edit"] == "e1"
        assert "Fleet Desk" in fake.calls[0]["messages"][-1]["content"]
        assert "[support email]" in fake.calls[0]["messages"][-1]["content"]


# ---------------------------------------------------------------------------
# The agents using the prompt (Postgres)
# ---------------------------------------------------------------------------

ALICE, BOB = "alice", "bob"


def _share_agent(conn, agent_id, owner, member):
    team = TeamsRepository(conn).create("Acme", f"t-{uuid.uuid4().hex[:8]}", owner)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(str(team["id"]), "agent", str(agent_id), owner, owner,
                                             access_level="viewer")


class TestAgentsUsingThePrompt:
    def test_the_agents_the_caller_can_see(self, pg_conn):
        prompt = PromptsRepository(pg_conn).create(ALICE, "Support", "You help.")
        pid = str(prompt["id"])
        s1 = SourcesRepository(pg_conn).create("Docs", user_id=ALICE)
        s2 = SourcesRepository(pg_conn).create("Policies", user_id=ALICE)
        crm = UserToolsRepository(pg_conn).create(ALICE, "api_tool", custom_name="Fleet CRM")
        agents = AgentsRepository(pg_conn)
        mine = agents.create(ALICE, "Fleet Desk", "published", prompt_id=pid, source_id=str(s1["id"]),
                             extra_source_ids=[str(s2["id"])],
                             tools=[str(crm["id"]), default_tool_id("memory"), str(uuid.uuid4())])
        shared = agents.create(BOB, "Bob's desk", "published", prompt_id=pid, agent_type="agentic")
        _share_agent(pg_conn, shared["id"], BOB, ALICE)
        agents.create(BOB, "Bob private", "published", prompt_id=pid)
        agents.create(ALICE, "Other prompt", "published")

        rows = read_agents(pg_conn, ALICE, pid)
        assert [r["name"] for r in rows] == ["Bob's desk", "Fleet Desk"]
        fleet = rows[1]
        assert fleet["id"] == str(mine["id"]) and fleet["agent_type"] == "classic" and fleet["sources"] == 2
        assert fleet["tools"][0] == "Fleet CRM" and len(fleet["tools"]) == 2
        assert rows[0] == {"id": str(shared["id"]), "name": "Bob's desk", "agent_type": "agentic", "sources": 0,
                           "tools": []}

    def test_at_most_twenty(self, pg_conn):
        prompt = PromptsRepository(pg_conn).create(ALICE, "Support", "You help.")
        for i in range(25):
            AgentsRepository(pg_conn).create(ALICE, f"Agent {i:02d}", "published", prompt_id=str(prompt["id"]))
        assert len(read_agents(pg_conn, ALICE, str(prompt["id"]))) == 20

    def test_a_built_in_prompt_lists_its_agents(self, pg_conn):
        AgentsRepository(pg_conn).create(ALICE, "Plain", "published")
        assert [r["name"] for r in read_agents(pg_conn, ALICE, "default")] == ["Plain"]


@pytest.mark.unit
def test_an_unsaved_prompt_reads_no_agents():
    ws = load_workspace("alice", parse_context({"mode": "review", "prompt": {"id": None, "content": "You help."}}))
    assert ws.agents == []


@pytest.mark.unit
def test_improve_and_write_read_no_agents():
    ws = load_workspace("alice", parse_context({"mode": "improve", "prompt": {"id": "p1", "content": "You help."}}))
    assert getattr(ws, "agents", []) == []


@pytest.mark.unit
@pytest.mark.parametrize("edit", ["1", 1.5, float("nan"), True, None])
def test_an_edit_that_is_not_a_whole_number_is_no_edit(edit):
    proposal = _review(findings=[_finding("tone", "look", edit=edit)])
    assert _model_findings(proposal)[0]["edit"] is None


@pytest.mark.unit
def test_an_edit_given_as_a_whole_float_counts():
    proposal = _review(edits=[DATE_EDIT], findings=[_finding("builtin_lines", edit=1.0)])
    assert _model_findings(proposal)[0]["edit"] == "e1"
