from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NodeType(str, Enum):
    START = "start"
    END = "end"
    AGENT = "agent"
    NOTE = "note"
    STATE = "state"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = 0.0
    y: float = 0.0


class AgentNodeData(BaseModel):
    model_config = ConfigDict(extra="allow")
    system_prompt: str = "You are a helpful assistant."
    prompt_template: str = ""
    output_variable: Optional[str] = None
    stream_to_user: bool = True


class StateNodeData(BaseModel):
    model_config = ConfigDict(extra="allow")
    variable: Optional[str] = None
    value: Optional[str] = None
    updates: Dict[str, str] = Field(default_factory=dict)


class EndNodeData(BaseModel):
    model_config = ConfigDict(extra="allow")
    output_template: str = ""


class BaseNodeData(BaseModel):
    model_config = ConfigDict(extra="allow")
    label: str = ""


NodeData = Union[AgentNodeData, StateNodeData, EndNodeData, BaseNodeData]


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    source_id: str = Field(..., alias="source")
    target_id: str = Field(..., alias="target")
    source_handle: Optional[str] = Field(None, alias="sourceHandle")
    target_handle: Optional[str] = Field(None, alias="targetHandle")


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    type: NodeType
    title: str = "Node"
    description: Optional[str] = None
    position: Position = Field(default_factory=Position)
    data: Dict[str, Union[str, bool, int, float, Dict[str, str], None]] = Field(
        default_factory=dict
    )

    @field_validator("position", mode="before")
    @classmethod
    def parse_position(cls, v: Union[Dict[str, float], Position]) -> Position:
        if isinstance(v, dict):
            return Position(**v)
        return v


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: Optional[str] = None
    name: str = "New Workflow"
    nodes: List[WorkflowNode] = Field(default_factory=list)
    edges: List[WorkflowEdge] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

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


class NodeExecutionLog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str
    node_type: str
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    state_snapshot: Dict[str, Union[str, int, float, bool, None]] = Field(
        default_factory=dict
    )


class WorkflowRunCreate(BaseModel):
    workflow_id: str
    inputs: Dict[str, str] = Field(default_factory=dict)


class WorkflowRun(BaseModel):
    model_config = ConfigDict(extra="allow")
    workflow_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    inputs: Dict[str, str] = Field(default_factory=dict)
    outputs: Dict[str, Union[str, int, float, bool, None]] = Field(default_factory=dict)
    steps: List[NodeExecutionLog] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    def to_mongo_doc(self) -> Dict[str, Union[str, Dict, List, datetime, None]]:
        return {
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "steps": [step.model_dump() for step in self.steps],
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }
