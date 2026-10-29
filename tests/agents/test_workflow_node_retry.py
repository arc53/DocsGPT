"""Workflow nodes retry transient model and sandbox failures before failing the run."""

import threading
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import httpx
import httpx2
import openai
import pytest

from docsgpt.agents.context_overflow import ContextOverflowError
from docsgpt.agents.workflows.node_agent import WorkflowNodeAgentFactory
from docsgpt.agents.workflows.retry import (
    EmptyCompletionError,
    InvalidNodeOutputError,
    SandboxInfrastructureError,
    classify_failure,
    resolve_retry_policy,
    retry_after_seconds,
    validate_retry_config,
)
from docsgpt.agents.workflows.schemas import (
    NodeType,
    Workflow,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)
from docsgpt.agents.workflows.workflow_engine import WorkflowEngine, _LoopItemCancelled
from docsgpt.api.user.workflows.routes import validate_workflow_structure
from docsgpt.core.run_budget import RunDeadlineExceeded, run_budget
from docsgpt.quotas.service import QuotaExceededError

_REQUEST = httpx2.Request("POST", "https://llm.example.com/v1/chat/completions")


def _status_error(status: int, headers: Optional[Dict[str, str]] = None) -> openai.APIStatusError:
    response = httpx2.Response(status, headers=headers or {}, request=_REQUEST)
    return openai.APIStatusError(f"Error code: {status}", response=response, body=None)


class ScriptedAgent:
    """A node agent that plays one scripted attempt per ``gen`` call.

    Each script entry is an exception to raise, or a list of events to yield
    (an exception inside the list is raised after the events before it).
    """

    def __init__(self, holder: Dict[str, Any]):
        self.holder = holder

    def gen(self, prompt):
        self.holder["prompts"].append(prompt)
        step = self.holder["script"].pop(0)
        if isinstance(step, BaseException):
            raise step
        for event in step:
            if isinstance(event, BaseException):
                raise event
            yield event


@pytest.fixture
def scripted(monkeypatch):
    """Route every agent node to a shared script; record prompts and retry waits."""
    holder: Dict[str, Any] = {"script": [], "prompts": [], "waits": []}
    monkeypatch.setattr(
        WorkflowNodeAgentFactory, "create", staticmethod(lambda **kwargs: ScriptedAgent(holder))
    )
    monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda _provider: None)
    monkeypatch.setattr(
        WorkflowEngine, "_wait_before_retry", lambda self, delay: holder["waits"].append(delay)
    )
    return holder


def _node(node_id: str, node_type: NodeType, **config) -> WorkflowNode:
    return WorkflowNode(
        id=node_id, workflow_id="wf", type=node_type, title=node_id, position={"x": 0, "y": 0}, config=config
    )


def _agent_node(**config) -> WorkflowNode:
    defaults = {"agent_type": "classic", "prompt_template": "Summarize", "stream_to_user": False}
    return _node("ask", NodeType.AGENT, **{**defaults, **config})


def _engine(node: WorkflowNode, retry_defaults: Optional[Dict[str, Any]] = None) -> WorkflowEngine:
    nodes = [_node("start", NodeType.START), node, _node("end", NodeType.END)]
    edges = [
        WorkflowEdge(id="e1", workflow_id="wf", source="start", target=node.id),
        WorkflowEdge(id="e2", workflow_id="wf", source=node.id, target="end"),
    ]
    graph = WorkflowGraph(
        workflow=Workflow(name="Retry", retry_defaults=retry_defaults), nodes=nodes, edges=edges
    )
    agent = SimpleNamespace(
        endpoint="stream",
        llm_name="openai",
        model_id="gpt-4o-mini",
        api_key="key",
        chat_history=[],
        decoded_token={"sub": "user-1"},
    )
    return WorkflowEngine(graph, agent)


def _run(engine: WorkflowEngine) -> List[Dict[str, Any]]:
    return list(engine.execute({}, "q"))


def _steps(events, node_id="ask"):
    return [e for e in events if e.get("type") == "workflow_step" and e["node_id"] == node_id]


def _node_log(engine: WorkflowEngine, node_id="ask") -> Dict[str, Any]:
    return next(log for log in engine.execution_log if log["node_id"] == node_id)


RETRY = {"max_attempts": 3, "backoff_seconds": [2, 10]}


# -- classification -----------------------------------------------------------


@pytest.mark.parametrize("status", [500, 502, 503, 504, 529, 408, 429])
def test_server_errors_and_rate_limits_are_transient(status):
    assert classify_failure(_status_error(status), "agent") == "transient"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 422])
def test_client_errors_are_never_retried(status):
    assert classify_failure(_status_error(status), "agent") is None


@pytest.mark.parametrize(
    "error",
    [
        openai.APITimeoutError(request=_REQUEST),
        openai.APIConnectionError(request=_REQUEST),
        httpx.ReadTimeout("read timed out"),
        httpx2.ConnectError("refused"),
        ConnectionResetError("reset by peer"),
    ],
)
def test_timeouts_and_dropped_connections_are_transient(error):
    assert classify_failure(error, "agent") == "transient"


def test_a_status_inside_a_wrapping_error_still_decides():
    try:
        try:
            raise _status_error(503)
        except openai.APIStatusError as inner:
            raise RuntimeError("model call failed") from inner
    except RuntimeError as outer:
        assert classify_failure(outer, "agent") == "transient"


@pytest.mark.parametrize(
    "error",
    [
        ContextOverflowError("too big", needed_tokens=10, available_tokens=5, stage="dispatch"),
        _status_error(400),
        RunDeadlineExceeded("out of time"),
        ValueError("This model's maximum context length is 8192 tokens"),
    ],
)
def test_context_length_and_budget_errors_are_never_retried(error):
    assert classify_failure(error, "agent") is None


def test_quota_errors_are_never_retried():
    quota = QuotaExceededError.__new__(QuotaExceededError)
    Exception.__init__(quota, "Usage quota reached (429)")
    assert classify_failure(quota, "agent") is None


def test_an_account_out_of_credit_is_never_retried():
    response = httpx2.Response(
        429,
        json={"error": {"message": "You exceeded your current quota", "code": "insufficient_quota"}},
        request=_REQUEST,
    )
    error = openai.OpenAI(api_key="x")._make_status_error_from_response(response)
    assert classify_failure(error, "agent") is None
    # A provider error whose code only sits in the nested body counts too.
    nested = _status_error(429)
    nested.code = None
    nested.body = {"error": {"code": "insufficient_quota"}}
    assert classify_failure(nested, "agent") is None


def test_output_errors_classify_by_kind():
    assert classify_failure(EmptyCompletionError("empty"), "agent") == "transient"
    assert classify_failure(InvalidNodeOutputError("bad json"), "agent") == "invalid_output"
    assert classify_failure(ValueError("something else"), "agent") is None


def test_code_nodes_retry_only_on_sandbox_infrastructure_errors():
    assert classify_failure(SandboxInfrastructureError("gone"), "code") == "transient"
    assert classify_failure(_status_error(503), "code") is None
    assert classify_failure(InvalidNodeOutputError("bad json"), "code") is None
    assert classify_failure(ValueError('Code node "x" failed: ZeroDivisionError'), "code") is None


def test_retry_after_reads_seconds_and_milliseconds():
    assert retry_after_seconds(_status_error(429, {"retry-after": "7"})) == 7.0
    assert retry_after_seconds(_status_error(429, {"retry-after-ms": "1500"})) == 1.5
    assert retry_after_seconds(_status_error(429)) is None


# -- policy -------------------------------------------------------------------


def _policy(node_retry=None, defaults=None):
    return resolve_retry_policy(node_retry, defaults, max_attempts=5, max_delay=300)


def test_no_retry_setting_means_one_attempt():
    assert _policy().max_attempts == 1
    assert not _policy().enabled


def test_node_fields_override_workflow_defaults_one_by_one():
    policy = _policy({"max_attempts": 4}, {"max_attempts": 2, "backoff_seconds": [1, 5], "on": ["transient"]})
    assert policy.max_attempts == 4
    assert policy.backoff_seconds == (1.0, 5.0)
    assert policy.on == frozenset({"transient"})


def test_backoff_uses_the_last_delay_past_the_list():
    policy = _policy({"max_attempts": 5, "backoff_seconds": [2, 10]})
    assert [policy.delay_before(n) for n in (2, 3, 4, 5)] == [2.0, 10.0, 10.0, 10.0]


def test_out_of_range_values_are_clamped_at_run_time():
    policy = _policy({"max_attempts": 50, "backoff_seconds": [-1, 9000], "on": ["transient", "bogus"]})
    assert policy.max_attempts == 5
    assert policy.backoff_seconds == (0.0, 300.0)
    assert policy.on == frozenset({"transient"})


@pytest.mark.parametrize(
    "raw, problem",
    [
        ({"max_attempts": 0}, "max_attempts"),
        ({"max_attempts": 9}, "max_attempts"),
        ({"max_attempts": True}, "max_attempts"),
        ({"backoff_seconds": "2,10"}, "backoff_seconds"),
        ({"backoff_seconds": [400]}, "backoff_seconds"),
        ({"on": ["everything"]}, "on"),
        ({"tries": 3}, "unknown"),
        ("3", "object"),
    ],
)
def test_invalid_retry_settings_are_named(raw, problem):
    assert problem in validate_retry_config(raw, max_attempts=5, max_delay=300)


def test_valid_retry_settings_pass():
    assert validate_retry_config(None, max_attempts=5, max_delay=300) is None
    assert validate_retry_config(
        {"max_attempts": 3, "backoff_seconds": [2, 10, 30], "on": ["transient", "invalid_output"]},
        max_attempts=5,
        max_delay=300,
    ) is None


def test_save_rejects_a_bad_node_retry():
    nodes = [
        {"id": "start", "type": "start", "data": {}},
        {"id": "ask", "type": "agent", "title": "Ask", "data": {"retry": {"max_attempts": 0}}},
        {"id": "end", "type": "end", "data": {}},
    ]
    edges = [{"id": "e1", "source": "start", "target": "ask"}, {"id": "e2", "source": "ask", "target": "end"}]
    errors = validate_workflow_structure(nodes, edges)
    assert any("Agent node 'Ask' retry max_attempts" in error for error in errors)


# -- agent nodes --------------------------------------------------------------


def test_a_5xx_then_success_completes_the_node_after_two_attempts(scripted):
    scripted["script"] = [_status_error(503), [{"answer": "done"}]]
    engine = _engine(_agent_node(retry=RETRY, output_variable="summary"))

    events = _run(engine)

    assert engine.state["summary"] == "done"
    assert not [e for e in events if e.get("type") == "error"]
    log = _node_log(engine)
    assert log["status"] == "completed"
    assert [(a["attempt"], a["status"], a["reason"]) for a in log["attempts"]] == [
        (1, "failed", "transient"),
        (2, "completed", None),
    ]
    assert scripted["waits"] == [2.0]
    steps = _steps(events)
    assert [s["status"] for s in steps] == ["running", "running", "completed"]
    retry_event = steps[1]
    assert retry_event["attempt"] == 2
    assert retry_event["max_attempts"] == 3
    assert retry_event["retry_delay_seconds"] == 2.0
    assert retry_event["retry_reason"] == "transient"
    assert "temporarily unavailable" in retry_event["retry_error"]
    assert steps[-1]["attempts"] == 2


def test_the_summary_carries_each_attempt(scripted):
    scripted["script"] = [_status_error(500), [{"answer": "done"}]]
    engine = _engine(_agent_node(retry=RETRY))
    _run(engine)

    summary = next(step for step in engine.get_execution_summary() if step.node_id == "ask")
    assert [a.status.value for a in summary.attempts] == ["failed", "completed"]
    assert summary.model_dump(mode="json")["attempts"][0]["reason"] == "transient"


def test_a_400_fails_at_once(scripted):
    scripted["script"] = [_status_error(400)]
    engine = _engine(_agent_node(retry=RETRY))

    events = _run(engine)

    assert len(scripted["prompts"]) == 1
    assert scripted["waits"] == []
    assert [e for e in events if e.get("type") == "error"]
    log = _node_log(engine)
    assert log["status"] == "failed"
    assert "attempts" not in log


def test_failures_past_max_attempts_fail_the_run(scripted):
    scripted["script"] = [_status_error(503), _status_error(503), _status_error(503)]
    engine = _engine(_agent_node(retry=RETRY))

    events = _run(engine)

    assert len(scripted["prompts"]) == 3
    assert scripted["waits"] == [2.0, 10.0]
    assert [e for e in events if e.get("type") == "error"]
    assert _steps(events)[-1]["attempts"] == 3
    assert [a["status"] for a in _node_log(engine)["attempts"]] == ["failed"] * 3


def test_max_attempts_1_behaves_as_without_retry(scripted):
    scripted["script"] = [_status_error(503)]
    engine = _engine(_agent_node(retry={"max_attempts": 1}))

    events = _run(engine)

    assert len(scripted["prompts"]) == 1
    steps = _steps(events)
    assert [s["status"] for s in steps] == ["running", "failed"]
    assert "attempts" not in steps[-1]
    assert "attempts" not in _node_log(engine)


def test_workflow_defaults_apply_to_nodes_without_their_own(scripted):
    scripted["script"] = [_status_error(502), [{"answer": "ok"}]]
    engine = _engine(_agent_node(), retry_defaults={"max_attempts": 2, "backoff_seconds": [0]})

    _run(engine)

    assert len(scripted["prompts"]) == 2
    assert scripted["waits"] == [0.0]


def test_a_node_can_opt_out_of_workflow_defaults(scripted):
    scripted["script"] = [_status_error(502)]
    engine = _engine(_agent_node(retry={"max_attempts": 1}), retry_defaults={"max_attempts": 3})

    _run(engine)

    assert len(scripted["prompts"]) == 1


def test_a_reason_left_out_of_on_is_not_retried(scripted):
    scripted["script"] = [_status_error(503)]
    engine = _engine(_agent_node(retry={"max_attempts": 3, "on": ["invalid_output"]}))

    _run(engine)

    assert len(scripted["prompts"]) == 1


def test_retry_after_on_a_429_wins_over_the_backoff(scripted):
    scripted["script"] = [_status_error(429, {"retry-after": "7"}), [{"answer": "ok"}]]
    engine = _engine(_agent_node(retry=RETRY))

    events = _run(engine)

    assert scripted["waits"] == [7.0]
    assert _steps(events)[1]["retry_delay_seconds"] == 7.0


def test_a_retry_after_past_the_cap_fails_now(scripted, monkeypatch):
    monkeypatch.setattr("docsgpt.core.settings.settings.WORKFLOW_RETRY_MAX_DELAY_SECONDS", 60)
    scripted["script"] = [_status_error(429, {"retry-after": "3600"})]
    engine = _engine(_agent_node(retry=RETRY))

    _run(engine)

    assert len(scripted["prompts"]) == 1
    assert scripted["waits"] == []


def test_a_wait_past_the_runs_time_limit_fails_now(scripted):
    scripted["script"] = [_status_error(503)]
    engine = _engine(_agent_node(retry={"max_attempts": 3, "backoff_seconds": [30]}))

    with run_budget(40, margin=20):
        _run(engine)

    assert len(scripted["prompts"]) == 1
    assert scripted["waits"] == []


def test_malformed_json_is_retried_with_the_error_in_the_prompt(scripted):
    schema = {"type": "object", "properties": {"score": {"type": "integer"}}, "required": ["score"]}
    scripted["script"] = [[{"answer": "{score: 3"}], [{"answer": '{"score": 3}'}]]
    engine = _engine(
        _agent_node(json_schema=schema, output_variable="rating", retry={"max_attempts": 2, "on": ["invalid_output"]})
    )

    events = _run(engine)

    assert engine.state["rating"] == {"score": 3}
    assert len(scripted["prompts"]) == 2
    assert "not valid JSON" not in scripted["prompts"][0]
    assert "Structured output was expected but response was not valid JSON" in scripted["prompts"][1]
    assert scripted["prompts"][1].startswith("Summarize")
    assert _steps(events)[1]["retry_reason"] == "invalid_output"


def test_a_schema_mismatch_is_retried_with_the_validation_error(scripted):
    schema = {"type": "object", "properties": {"score": {"type": "integer"}}, "required": ["score"]}
    scripted["script"] = [[{"answer": '{"rank": 1}'}], [{"answer": '{"score": 1}'}]]
    engine = _engine(_agent_node(json_schema=schema, retry={"max_attempts": 2}))

    _run(engine)

    assert "'score' is a required property" in scripted["prompts"][1]
    assert engine.state["node_ask_output"] == {"score": 1}


def test_the_quoted_validation_error_is_bounded(scripted):
    schema = {"type": "object", "properties": {"text": {"type": "integer"}}}
    huge = '{"text": "' + "x" * 50_000 + '"}'
    scripted["script"] = [[{"answer": huge}], [{"answer": '{"text": 1}'}]]
    engine = _engine(_agent_node(json_schema=schema, retry={"max_attempts": 2}))

    _run(engine)

    assert len(scripted["prompts"][1]) < 2_000


def test_invalid_output_is_not_retried_without_invalid_output_in_on(scripted):
    scripted["script"] = [[{"answer": "not json"}]]
    engine = _engine(_agent_node(json_schema={"type": "object"}, retry={"max_attempts": 3, "on": ["transient"]}))

    events = _run(engine)

    assert len(scripted["prompts"]) == 1
    assert [e for e in events if e.get("type") == "error"]


def test_a_held_schema_reply_reaches_the_user_once_it_validates(scripted):
    scripted["script"] = [
        [{"answer": "oops", "structured": True}],
        [{"answer": '{"ok": true}', "structured": True}],
    ]
    engine = _engine(
        _agent_node(json_schema={"type": "object"}, stream_to_user=True, retry={"max_attempts": 2})
    )

    events = _run(engine)

    answers = [e["answer"] for e in events if "answer" in e]
    assert answers == ['{"ok": true}']


def test_an_attempt_that_streamed_text_is_not_retried(scripted):
    scripted["script"] = [[{"answer": "Half an ans"}, _status_error(503)]]
    engine = _engine(_agent_node(stream_to_user=True, retry=RETRY))

    events = _run(engine)

    assert len(scripted["prompts"]) == 1
    assert [e["answer"] for e in events if "answer" in e] == ["Half an ans"]
    assert [e for e in events if e.get("type") == "error"]


def test_an_error_before_any_streamed_text_is_retried(scripted):
    scripted["script"] = [_status_error(503), [{"answer": "Full answer"}]]
    engine = _engine(_agent_node(stream_to_user=True, retry=RETRY))

    events = _run(engine)

    assert [e["answer"] for e in events if "answer" in e] == ["Full answer"]


def test_an_empty_reply_is_retried_and_the_last_one_is_kept(scripted):
    scripted["script"] = [[{"answer": "  "}], [], [{"answer": ""}]]
    engine = _engine(_agent_node(retry={"max_attempts": 3, "backoff_seconds": [0]}))

    events = _run(engine)

    assert len(scripted["prompts"]) == 3
    assert not [e for e in events if e.get("type") == "error"]
    assert engine.state["node_ask_output"] == ""
    assert [a["reason"] for a in _node_log(engine)["attempts"]] == ["transient", "transient", None]


def test_an_empty_reply_without_retries_is_kept_as_before(scripted):
    scripted["script"] = [[]]
    engine = _engine(_agent_node())

    events = _run(engine)

    assert not [e for e in events if e.get("type") == "error"]
    assert engine.state["node_ask_output"] == ""


def test_a_loop_items_node_retries_on_its_own(scripted):
    loop = _node("each", NodeType.LOOP, items="names", output_variable="results")
    body = _node(
        "ask",
        NodeType.AGENT,
        agent_type="classic",
        prompt_template="{{ item }}",
        stream_to_user=False,
        parent_id="each",
        retry={"max_attempts": 2, "backoff_seconds": [0]},
    )
    scripted["script"] = [_status_error(503), [{"answer": "A"}]]
    engine = _engine(loop)
    engine.graph.nodes.append(body)

    events = list(engine.execute({"names": ["a"]}, "q"))

    assert engine.state["results"] == ["A"]
    retry = [e for e in _steps(events) if e.get("attempt") == 2]
    assert retry and retry[0]["parent_node_id"] == "each"


# -- waiting ------------------------------------------------------------------


def test_the_wait_ends_when_the_loop_is_stopped():
    engine = _engine(_agent_node())
    engine._loop_cancel = threading.Event()
    threading.Timer(0.05, engine._loop_cancel.set).start()

    with pytest.raises(_LoopItemCancelled):
        engine._wait_before_retry(30)


# -- code nodes ---------------------------------------------------------------


class _Result:
    def __init__(self, ok=True, stdout="", error_name=None, error_value=None, sandbox_error=False):
        self.status = "ok" if ok else "error"
        self.stdout = stdout
        self.stderr = ""
        self.error_name = error_name
        self.error_value = error_value
        self.runtime_invalidated = False
        self.sandbox_error = sandbox_error

    @property
    def ok(self):
        return self.status == "ok"


class _Manager:
    def __init__(self, results):
        self.results = list(results)
        self.runs = 0

    def open(self, session_id, ttl=None):
        if isinstance(self.results[0], BaseException):
            raise self.results.pop(0)
        return session_id

    def put_file(self, session_id, dest_path, data):
        pass

    def exec(self, session_id, code, timeout=None):
        self.runs += 1
        return self.results.pop(0)

    def close(self, session_id):
        pass


@pytest.fixture
def sandbox(monkeypatch):
    holder: Dict[str, Any] = {"waits": []}

    def get_manager():
        return holder["manager"]

    monkeypatch.setattr("docsgpt.sandbox.sandbox_creator.SandboxCreator.get_manager", get_manager)
    monkeypatch.setattr("docsgpt.sandbox.sandbox_creator.SandboxCreator.peek_manager", lambda: None)
    monkeypatch.setattr("docsgpt.sandbox.artifacts_capture.snapshot_signatures", lambda *a, **k: {})
    monkeypatch.setattr("docsgpt.sandbox.artifacts_capture.capture_artifacts", lambda *a, **k: [])
    monkeypatch.setattr(
        WorkflowEngine, "_wait_before_retry", lambda self, delay: holder["waits"].append(delay)
    )
    return holder


def _code_engine(**config) -> WorkflowEngine:
    node = _node("run", NodeType.CODE, code="print(1)", **config)
    return _engine(node)


def test_a_code_node_retries_when_the_sandbox_drops(sandbox):
    sandbox["manager"] = _Manager(
        [
            _Result(ok=False, error_name="KernelDiedError", error_value="channel closed", sandbox_error=True),
            _Result(ok=True, stdout="1"),
        ]
    )
    engine = _code_engine(retry=RETRY)

    events = _run(engine)

    assert not [e for e in events if e.get("type") == "error"]
    assert sandbox["manager"].runs == 2
    assert [a["status"] for a in _node_log(engine, "run")["attempts"]] == ["failed", "completed"]


def test_a_code_node_retries_when_the_sandbox_is_gone(sandbox):
    from docsgpt.sandbox.base import SandboxGoneError

    sandbox["manager"] = _Manager([SandboxGoneError("deleted"), _Result(ok=True, stdout="1")])
    engine = _code_engine(retry=RETRY)

    events = _run(engine)

    assert not [e for e in events if e.get("type") == "error"]
    assert sandbox["waits"] == [2.0]


def test_a_code_error_is_not_retried(sandbox):
    sandbox["manager"] = _Manager(
        [_Result(ok=False, error_name="ZeroDivisionError", error_value="division by zero")]
    )
    engine = _code_engine(retry=RETRY)

    events = _run(engine)

    assert sandbox["manager"].runs == 1
    assert [e for e in events if e.get("type") == "error"]


def test_a_code_nodes_bad_json_is_not_retried(sandbox):
    sandbox["manager"] = _Manager([_Result(ok=True, stdout="not json")])
    engine = _code_engine(retry=RETRY, json_schema={"type": "object"})

    _run(engine)

    assert sandbox["manager"].runs == 1
