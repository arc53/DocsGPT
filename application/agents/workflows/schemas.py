from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator


class NodeType(str, Enum):
    START = "start"
    END = "end"
    AGENT = "agent"
    NOTE = "note"
    STATE = "state"


class AgentType(str, Enum):
    CLASSIC = "classic"
    REACT = "react"


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
    chunks: str = "2"
    retriever: str = ""
    model_id: Optional[str] = None
    json_schema: Optional[Dict[str, Any]] = None


class WorkflowEdgeCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    workflow_id: str
    source_id: str = Field(..., alias="source")
    target_id: str = Field(..., alias="target")
    source_handle: Optional[str] = Field(None, alias="sourceHandle")
    target_handle: Optional[str] = Field(None, alias="targetHandle")


class WorkflowEdge(WorkflowEdgeCreate):
    mongo_id: Optional[str] = Field(None, alias="_id")

    @field_validator("mongo_id", mode="before")
    @classmethod
    def convert_objectid(cls, v: Any) -> Optional[str]:
        if isinstance(v, ObjectId):
            return str(v)
        return v

    def to_mongo_doc(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "source_handle": self.source_handle,
            "target_handle": self.target_handle,
        }


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
    mongo_id: Optional[str] = Field(None, alias="_id")

    @field_validator("mongo_id", mode="before")
    @classmethod
    def convert_objectid(cls, v: Any) -> Optional[str]:
        if isinstance(v, ObjectId):
            return str(v)
        return v

    def to_mongo_doc(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "type": self.type.value,
            "title": self.title,
            "description": self.description,
            "position": self.position.model_dump(),
            "config": self.config,
        }


class WorkflowCreate(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = "New Workflow"
    description: Optional[str] = None
    user: Optional[str] = None


class Workflow(WorkflowCreate):
    id: Optional[str] = Field(None, alias="_id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("id", mode="before")
    @classmethod
    def convert_objectid(cls, v: Any) -> Optional[str]:
        if isinstance(v, ObjectId):
            return str(v)
        return v

    def to_mongo_doc(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "user": self.user,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


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


class NodeExecutionLog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str
    node_type: str
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    state_snapshot: Dict[str, Any] = Field(default_factory=dict)


class WorkflowRunCreate(BaseModel):
    workflow_id: str
    inputs: Dict[str, str] = Field(default_factory=dict)


class WorkflowRun(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: Optional[str] = Field(None, alias="_id")
    workflow_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    inputs: Dict[str, str] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    steps: List[NodeExecutionLog] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    @field_validator("id", mode="before")
    @classmethod
    def convert_objectid(cls, v: Any) -> Optional[str]:
        if isinstance(v, ObjectId):
            return str(v)
        return v

    def to_mongo_doc(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "steps": [step.model_dump() for step in self.steps],
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }
