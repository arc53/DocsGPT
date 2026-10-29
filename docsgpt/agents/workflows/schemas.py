from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NodeType(str, Enum):
    START = "start"
    END = "end"
    AGENT = "agent"
    NOTE = "note"
    STATE = "state"
    CONDITION = "condition"
    CODE = "code"
    LOOP = "loop"


# Key in a node's config naming the loop whose body the node belongs to. Body
# nodes are stored as ordinary graph nodes so every per-node scan (tool and
# source checks, export, adoption) sees them; only the walk treats them apart.
PARENT_ID_KEY = "parent_id"

# Node types a loop body may hold.
LOOP_BODY_NODE_TYPES = frozenset({"agent", "code", "state", "condition", "note"})

# Names a loop's item variable may not take: template namespaces and the
# run's own inputs, which the item would shadow.
LOOP_RESERVED_VARIABLES = frozenset(
    {"agent", "artifacts", "system", "source", "tools", "passthrough", "query", "chat_history", "input_documents"}
)


def parent_id_of(config: Any) -> Optional[str]:
    """The loop a node's config places it in, or None for a top-level node."""
    if not isinstance(config, dict):
        return None
    value = config.get(PARENT_ID_KEY)
    return value if isinstance(value, str) and value.strip() else None


class AgentType(str, Enum):
    CLASSIC = "classic"
    REACT = "react"
    AGENTIC = "agentic"
    RESEARCH = "research"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = 0.0
    y: float = 0.0


class AgentNodeConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    agent_type: AgentType = AgentType.CLASSIC
    llm_name: Optional[str] = None
    system_prompt: str = "You are a helpful assistant."
    prompt_template: str = ""
    output_variable: Optional[str] = None
    stream_to_user: bool = True
    tools: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    chunks: str = "6"
    retriever: str = ""
    model_id: Optional[str] = None
    json_schema: Optional[Dict[str, Any]] = None
    # Run-scoped documents fed to this node's LLM. Entries are state-var names
    # holding artifact refs (single dict or a list of dicts), raw artifact ids,
    # short refs (``A1``), or the ``"*"``/``"input_documents"`` token meaning
    # "every ref in ``state['input_documents']``".
    input_documents: List[str] = Field(default_factory=list)
    # How selected documents reach the model: ``auto`` (native when the model
    # accepts the mime, else extract to text), ``native`` (force native; raise
    # on an unsupported mime), or ``extract`` (always inline extracted text).
    file_passing: Literal["auto", "native", "extract"] = "auto"


class CodeNodeConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    code: str = ""
    inputs: List[str] = Field(default_factory=list)
    output_variable: Optional[str] = None
    timeout: Optional[int] = None
    json_schema: Optional[Dict[str, Any]] = None


class LoopNodeConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    # State path to the list, e.g. ``extracted.items``.
    items: str = ""
    item_variable: str = "item"
    concurrency: int = Field(default=4, ge=1)
    max_items: int = Field(default=50, ge=1)
    on_item_error: Literal["fail", "skip", "collect"] = "fail"
    output_variable: Optional[str] = None
    # Item state key whose value is the item's result; unset takes the output
    # of the last body node that wrote one.
    result_variable: Optional[str] = None


class ConditionCase(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    name: Optional[str] = None
    expression: str = ""
    source_handle: str = Field(..., alias="sourceHandle")


class ConditionNodeConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    mode: Literal["simple", "advanced"] = "simple"
    cases: List[ConditionCase] = Field(default_factory=list)


class StateOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expression: str = ""
    target_variable: str = ""


class WorkflowEdgeCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    workflow_id: str
    source_id: str = Field(..., alias="source")
    target_id: str = Field(..., alias="target")
    source_handle: Optional[str] = Field(None, alias="sourceHandle")
    target_handle: Optional[str] = Field(None, alias="targetHandle")


class WorkflowEdge(WorkflowEdgeCreate):
    pass


class WorkflowNodeCreate(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    workflow_id: str
    type: NodeType
    title: str = "Node"
    description: Optional[str] = None
    position: Position = Field(default_factory=Position)
    config: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("position", mode="before")
    @classmethod
    def parse_position(cls, v: Union[Dict[str, float], Position]) -> Position:
        if isinstance(v, dict):
            return Position(**v)
        return v


class WorkflowNode(WorkflowNodeCreate):
    pass


class WorkflowCreate(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = "New Workflow"
    description: Optional[str] = None
    user: Optional[str] = None


class Workflow(WorkflowCreate):
    id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkflowGraph(BaseModel):
    workflow: Workflow
    nodes: List[WorkflowNode] = Field(default_factory=list)
    edges: List[WorkflowEdge] = Field(default_factory=list)

    def get_node_by_id(self, node_id: str) -> Optional[WorkflowNode]:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_start_node(self) -> Optional[WorkflowNode]:
        for node in self.nodes:
            if node.type == NodeType.START:
                return node
        return None

    def get_outgoing_edges(self, node_id: str) -> List[WorkflowEdge]:
        return [edge for edge in self.edges if edge.source_id == node_id]

    def get_body_nodes(self, loop_id: str) -> List[WorkflowNode]:
        """The nodes inside a loop's body."""
        return [node for node in self.nodes if parent_id_of(node.config) == loop_id]

    def get_body_entry(self, loop_id: str) -> Optional[WorkflowNode]:
        """The body node an item starts at: the one no other body node leads to.

        Returns:
            The entry node, or None when the body is empty or has no single entry.
        """
        body = [node for node in self.get_body_nodes(loop_id) if node.type != NodeType.NOTE]
        body_ids = {node.id for node in body}
        targets = {edge.target_id for edge in self.edges if edge.source_id in body_ids}
        entries = [node for node in body if node.id not in targets]
        return entries[0] if len(entries) == 1 else None

    def linear_step_count(self, count_end: bool = True) -> Optional[int]:
        """How many steps a run takes when the graph has one path.

        Follows the path the engine takes from the start node (the first
        outgoing edge of each node). Start and note nodes are not steps.

        Args:
            count_end: Whether the end node counts as a step.

        Returns:
            The step count, or None when the path meets a condition (the
            count depends on the branch taken), loops, or there is no start.
        """
        node = self.get_start_node()
        if node is None:
            return None
        seen: set = set()
        count = 0
        while node is not None:
            if node.id in seen or node.type == NodeType.CONDITION:
                return None
            seen.add(node.id)
            if node.type not in (NodeType.START, NodeType.NOTE) and (count_end or node.type != NodeType.END):
                count += 1
            if node.type == NodeType.END:
                break
            edges = self.get_outgoing_edges(node.id)
            node = self.get_node_by_id(edges[0].target_id) if edges else None
        return count or None


class LoopItemLog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_index: int
    status: ExecutionStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    steps: List["NodeExecutionLog"] = Field(default_factory=list)


class NodeExecutionLog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str
    node_type: str
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    # The node's state DELTA (keys it added or changed), not the full state:
    # point-in-time state is the merge of deltas up to this step. Runs
    # persisted before the rename carry this as ``state_snapshot``.
    state_delta: Dict[str, Any] = Field(default_factory=dict)
    # Compact per-node tool-call summary: [{tool_name, action_name, status}].
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    # A loop node's per-item runs, in item order.
    items: List[LoopItemLog] = Field(default_factory=list)


LoopItemLog.model_rebuild()


class WorkflowRunCreate(BaseModel):
    workflow_id: str
    inputs: Dict[str, str] = Field(default_factory=dict)


class WorkflowRun(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: Optional[str] = None
    workflow_id: str
    user: Optional[str] = None
    status: ExecutionStatus = ExecutionStatus.PENDING
    inputs: Dict[str, str] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    steps: List[NodeExecutionLog] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
