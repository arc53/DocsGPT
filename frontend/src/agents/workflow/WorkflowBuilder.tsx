import 'reactflow/dist/style.css';

import {
  AlertCircle,
  ChartColumn,
  Bot,
  Database,
  Flag,
  GitBranch,
  Loader2,
  Link,
  Pencil,
  Play,
  Plus,
  Settings2,
  StickyNote,
  Trash2,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSelector } from 'react-redux';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import ReactFlow, {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  Connection,
  Controls,
  Edge,
  EdgeChange,
  Node,
  NodeChange,
  NodeTypes,
  ReactFlowProvider,
  useReactFlow,
} from 'reactflow';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { MultiSelect } from '@/components/ui/multi-select';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Sheet, SheetContent } from '@/components/ui/sheet';

import modelService from '../../api/services/modelService';
import userService from '../../api/services/userService';
import ArrowLeft from '../../assets/arrow-left.svg';
import { FileUpload } from '../../components/FileUpload';
import AgentDetailsModal from '../../modals/AgentDetailsModal';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { ActiveState } from '../../models/misc';
import { selectToken } from '../../preferences/preferenceSlice';
import { Agent } from '../types';
import { ConditionCase, WorkflowNode } from '../types/workflow';
import MobileBlocker from './components/MobileBlocker';
import PromptTextArea from './components/PromptTextArea';
import {
  AgentNode,
  ConditionNode,
  EndNode,
  NoteNode,
  SetStateNode,
  StartNode,
} from './nodes';
import WorkflowPreview from './WorkflowPreview';

import type { Model } from '../../models/types';

const PRIMARY_ACTION_SPINNER_DELAY_MS = 180;

interface AgentNodeConfig {
  agent_type: 'classic' | 'react';
  llm_name?: string;
  model_id?: string;
  system_prompt: string;
  prompt_template: string;
  output_variable?: string;
  stream_to_user: boolean;
  sources: string[];
  tools: string[];
  chunks?: string;
  retriever?: string;
  json_schema?: Record<string, unknown>;
}

interface UserTool {
  id: string;
  name: string;
  displayName: string;
}

function validateJsonSchemaConfig(schema: unknown): string | null {
  if (schema === undefined || schema === null) return null;
  if (typeof schema !== 'object' || Array.isArray(schema)) {
    return 'must be a valid JSON object';
  }

  const schemaObject = schema as Record<string, unknown>;
  if (!('schema' in schemaObject) && !('type' in schemaObject)) {
    return 'must include either a "type" or "schema" field';
  }

  return null;
}

function createEmptyWorkflowAgent(): Agent {
  return {
    id: '',
    name: '',
    description: '',
    image: '',
    source: '',
    chunks: '2',
    retriever: '',
    prompt_id: '',
    tools: [],
    agent_type: 'workflow',
    status: 'published',
  };
}

function canReachEnd(
  nodeId: string,
  edges: Edge[],
  nodeIds: Set<string>,
  endIds: Set<string>,
  visited: Set<string> = new Set(),
): boolean {
  if (endIds.has(nodeId)) return true;
  if (visited.has(nodeId) || !nodeIds.has(nodeId)) return false;
  visited.add(nodeId);
  return edges
    .filter((e) => e.source === nodeId)
    .some((e) => canReachEnd(e.target, edges, nodeIds, endIds, visited));
}

function parseSimpleCel(expression: string): {
  variable: string;
  operator: string;
  value: string;
} {
  const trimmedExpression = expression.trim();

  let match = trimmedExpression.match(
    /^(\w+)\.(contains|startsWith)\(["'](.*)["']\)$/,
  );
  if (match) return { variable: match[1], operator: match[2], value: match[3] };

  match = trimmedExpression.match(/^(\w+)\.(contains|startsWith)\((.*)\)$/);
  if (match) {
    const rawValue = match[3].trim();
    const unquotedValue = rawValue.replace(/^["'](.*)["']$/, '$1');
    return {
      variable: match[1],
      operator: match[2],
      value: unquotedValue,
    };
  }

  match = trimmedExpression.match(/^(contains|startsWith)\(["'](.*)["']\)$/);
  if (match) return { variable: '', operator: match[1], value: match[2] };

  match = trimmedExpression.match(/^(contains|startsWith)\((.*)\)$/);
  if (match) {
    const rawValue = match[2].trim();
    const unquotedValue = rawValue.replace(/^["'](.*)["']$/, '$1');
    return { variable: '', operator: match[1], value: unquotedValue };
  }

  match = trimmedExpression.match(/^(\w+)\s*(==|!=|>=|<=|>|<)\s*["'](.*)["']$/);
  if (match) return { variable: match[1], operator: match[2], value: match[3] };

  match = trimmedExpression.match(/^(==|!=|>=|<=|>|<)\s*["'](.*)["']$/);
  if (match) return { variable: '', operator: match[1], value: match[2] };

  match = trimmedExpression.match(/^(\w+)\s*(==|!=|>=|<=|>|<)\s*(.*)$/);
  if (match) return { variable: match[1], operator: match[2], value: match[3] };

  match = trimmedExpression.match(/^(==|!=|>=|<=|>|<)\s*(.*)$/);
  if (match) return { variable: '', operator: match[1], value: match[2] };

  return { variable: '', operator: '==', value: '' };
}

function buildSimpleCel(
  variable: string,
  operator: string,
  value: string,
): string {
  const trimmedValue = value.trim();
  const isNumeric = trimmedValue !== '' && !isNaN(Number(trimmedValue));
  const isBool = trimmedValue === 'true' || trimmedValue === 'false';
  const literalValue =
    isNumeric || isBool ? trimmedValue : JSON.stringify(value);
  const stringValue = JSON.stringify(value);
  if (operator === 'contains') {
    return variable
      ? `${variable}.contains(${stringValue})`
      : `contains(${stringValue})`;
  }
  if (operator === 'startsWith') {
    return variable
      ? `${variable}.startsWith(${stringValue})`
      : `startsWith(${stringValue})`;
  }
  if (!variable) return `${operator} ${literalValue}`;
  return `${variable} ${operator} ${literalValue}`;
}

function normalizeConditionCases(cases: ConditionCase[]): ConditionCase[] {
  const usedHandles = new Set<string>();
  let nextIndex = 0;

  return cases.map((conditionCase) => {
    const candidate = (conditionCase.sourceHandle || '').trim();
    if (candidate && !usedHandles.has(candidate)) {
      usedHandles.add(candidate);
      const match = candidate.match(/^case_(\d+)$/);
      if (match) {
        nextIndex = Math.max(nextIndex, Number(match[1]) + 1);
      }
      return conditionCase;
    }

    while (usedHandles.has(`case_${nextIndex}`)) {
      nextIndex += 1;
    }
    const generatedHandle = `case_${nextIndex}`;
    usedHandles.add(generatedHandle);
    nextIndex += 1;

    return {
      ...conditionCase,
      sourceHandle: generatedHandle,
    };
  });
}

function getNextConditionHandle(cases: ConditionCase[]): string {
  const usedHandles = new Set(
    cases.map((conditionCase) => conditionCase.sourceHandle).filter(Boolean),
  );
  const usedIndices = Array.from(usedHandles)
    .map((handle) => handle.match(/^case_(\d+)$/))
    .filter((match): match is RegExpMatchArray => Boolean(match))
    .map((match) => Number(match[1]));

  let nextIndex = usedIndices.length > 0 ? Math.max(...usedIndices) + 1 : 0;
  while (usedHandles.has(`case_${nextIndex}`)) {
    nextIndex += 1;
  }

  return `case_${nextIndex}`;
}

function createWorkflowPayload(
  name: string,
  description: string,
  workflowNodes: Node[],
  workflowEdges: Edge[],
) {
  return {
    name,
    description,
    nodes: workflowNodes.map((node) => ({
      id: node.id,
      type: node.type as
        | 'start'
        | 'end'
        | 'agent'
        | 'note'
        | 'state'
        | 'condition',
      title: node.data.title || node.data.label || node.type,
      position: node.position,
      data:
        node.type === 'agent' ||
        node.type === 'condition' ||
        node.type === 'state'
          ? node.data.config
          : node.data,
    })),
    edges: workflowEdges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle || undefined,
      targetHandle: edge.targetHandle || undefined,
    })),
  };
}

function WorkflowBuilderInner() {
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const { agentId } = useParams<{ agentId?: string }>();
  const [searchParams] = useSearchParams();
  const folderId = searchParams.get('folder_id');
  const [workflowId, setWorkflowId] = useState<string | null>(
    searchParams.get('workflow_id'),
  );
  const reactFlowInstance = useReactFlow();
  const [currentAgentId, setCurrentAgentId] = useState<string | null>(
    agentId || null,
  );

  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [workflowName, setWorkflowName] = useState('New Workflow');
  const [workflowDescription, setWorkflowDescription] = useState('');
  const [showWorkflowSettings, setShowWorkflowSettings] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [showPrimaryActionSpinner, setShowPrimaryActionSpinner] =
    useState(false);
  const [publishErrors, setPublishErrors] = useState<string[]>([]);
  const [errorContext, setErrorContext] = useState<'preview' | 'publish'>(
    'publish',
  );
  const [showNodeConfig, setShowNodeConfig] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');
  const [agentDetails, setAgentDetails] = useState<ActiveState>('INACTIVE');
  const [isDeletingAgent, setIsDeletingAgent] = useState(false);
  const [currentAgent, setCurrentAgent] = useState<Agent>(
    createEmptyWorkflowAgent(),
  );
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [savedWorkflowSignature, setSavedWorkflowSignature] = useState<
    string | null
  >(null);
  const workflowSettingsRef = useRef<HTMLDivElement>(null);
  const [availableModels, setAvailableModels] = useState<Model[]>([]);
  const [defaultAgentModelId, setDefaultAgentModelId] = useState('');
  const [availableTools, setAvailableTools] = useState<UserTool[]>([]);
  const [agentJsonSchemaDrafts, setAgentJsonSchemaDrafts] = useState<
    Record<string, string>
  >({});
  const [agentJsonSchemaErrors, setAgentJsonSchemaErrors] = useState<
    Record<string, string | null>
  >({});

  const nodeTypes = useMemo<NodeTypes>(
    () => ({
      start: StartNode,
      agent: AgentNode,
      end: EndNode,
      note: NoteNode,
      state: SetStateNode,
      condition: ConditionNode,
    }),
    [],
  );

  const initialNodes: Node[] = useMemo(
    () => [
      {
        id: 'start',
        type: 'start',
        data: { label: 'Start' },
        position: { x: 250, y: 50 },
      },
    ],
    [],
  );

  const [nodes, setNodes] = useState<Node[]>(initialNodes);
  const [edges, setEdges] = useState<Edge[]>([]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) =>
      setNodes((nds) => applyNodeChanges(changes, nds)),
    [],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) =>
      setEdges((eds) => applyEdgeChanges(changes, eds)),
    [],
  );

  const onConnect = useCallback((params: Connection) => {
    setEdges((eds) => {
      const exists = eds.some(
        (e) =>
          e.source === params.source &&
          e.sourceHandle === params.sourceHandle &&
          e.target === params.target &&
          e.targetHandle === params.targetHandle,
      );
      if (exists) return eds;

      const filtered = eds.filter(
        (e) =>
          !(
            e.source === params.source &&
            e.sourceHandle === (params.sourceHandle ?? null)
          ) &&
          !(
            e.target === params.target &&
            e.targetHandle === (params.targetHandle ?? null)
          ),
      );
      return addEdge(params, filtered);
    });
  }, []);

  const onEdgeClick = useCallback((_event: React.MouseEvent, edge: Edge) => {
    setEdges((eds) => eds.filter((e) => e.id !== edge.id));
  }, []);

  const handleNodeDragStart = useCallback(
    (e: React.DragEvent, nodeType: string) => {
      e.dataTransfer.setData('application/reactflow', nodeType);
      e.dataTransfer.effectAllowed = 'move';
      const el = e.currentTarget as HTMLElement;
      const clone = el.cloneNode(true) as HTMLElement;
      clone.style.position = 'absolute';
      clone.style.top = '-9999px';
      clone.style.width = `${el.offsetWidth}px`;
      clone.style.borderRadius = '9999px';
      clone.style.overflow = 'hidden';
      document.body.appendChild(clone);
      e.dataTransfer.setDragImage(
        clone,
        clone.offsetWidth / 2,
        clone.offsetHeight / 2,
      );
      requestAnimationFrame(() => document.body.removeChild(clone));
    },
    [],
  );

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const type = event.dataTransfer.getData('application/reactflow');
      if (!type) return;

      const position = reactFlowInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      const baseNode: Node = {
        id: `${type}_${Date.now()}`,
        type,
        position,
        data: {
          title: `${type} node`,
          label: `${type} node`,
        },
      };

      if (type === 'agent') {
        const defaultModelId = defaultAgentModelId || availableModels[0]?.id;
        const defaultModelProvider = availableModels.find(
          (model) => model.id === defaultModelId,
        )?.provider;
        baseNode.data.config = {
          agent_type: 'classic',
          model_id: defaultModelId,
          llm_name: defaultModelProvider || '',
          system_prompt: 'You are a helpful assistant.',
          prompt_template: '',
          stream_to_user: true,
          sources: [],
          tools: [],
        } as AgentNodeConfig;
      } else if (type === 'state') {
        baseNode.data.title = 'Set State';
        baseNode.data.config = {
          operations: [{ expression: '', target_variable: '' }],
        };
      } else if (type === 'condition') {
        baseNode.data.title = 'If / Else';
        baseNode.data.config = {
          mode: 'simple',
          cases: [{ name: '', expression: '', sourceHandle: 'case_0' }],
        };
      } else if (type === 'note') {
        baseNode.data.title = 'Note';
        baseNode.data.label = 'Note';
      }

      setNodes((nds) => nds.concat(baseNode));
    },
    [reactFlowInstance, availableModels, defaultAgentModelId],
  );

  const handleNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      setSelectedNode(node);
      setShowNodeConfig(true);
    },
    [],
  );

  const handleDeleteNode = useCallback(() => {
    if (!selectedNode || selectedNode.type === 'start') return;
    setNodes((nds) => nds.filter((n) => n.id !== selectedNode.id));
    setEdges((eds) =>
      eds.filter(
        (e) => e.source !== selectedNode.id && e.target !== selectedNode.id,
      ),
    );
    setAgentJsonSchemaDrafts((prev) => {
      if (!(selectedNode.id in prev)) return prev;
      const next = { ...prev };
      delete next[selectedNode.id];
      return next;
    });
    setAgentJsonSchemaErrors((prev) => {
      if (!(selectedNode.id in prev)) return prev;
      const next = { ...prev };
      delete next[selectedNode.id];
      return next;
    });
    setSelectedNode(null);
    setShowNodeConfig(false);
  }, [selectedNode]);

  const handleUpdateNodeData = useCallback(
    (data: Record<string, unknown>) => {
      if (!selectedNode) return;
      setNodes((nds) =>
        nds.map((n) =>
          n.id === selectedNode.id ? { ...n, data: { ...n.data, ...data } } : n,
        ),
      );
      setSelectedNode((prev) =>
        prev ? { ...prev, data: { ...prev.data, ...data } } : null,
      );
    },
    [selectedNode],
  );

  const handleAgentJsonSchemaChange = useCallback(
    (text: string) => {
      if (!selectedNode || selectedNode.type !== 'agent') return;

      const nodeId = selectedNode.id;
      setAgentJsonSchemaDrafts((prev) => ({ ...prev, [nodeId]: text }));

      if (text.trim() === '') {
        setAgentJsonSchemaErrors((prev) => ({ ...prev, [nodeId]: null }));
        handleUpdateNodeData({
          config: {
            ...(selectedNode.data.config || {}),
            json_schema: undefined,
          },
        });
        return;
      }

      try {
        const parsed = JSON.parse(text);
        const validationError = validateJsonSchemaConfig(parsed);
        setAgentJsonSchemaErrors((prev) => ({
          ...prev,
          [nodeId]: validationError,
        }));
        if (!validationError) {
          handleUpdateNodeData({
            config: {
              ...(selectedNode.data.config || {}),
              json_schema: parsed,
            },
          });
        }
      } catch {
        setAgentJsonSchemaErrors((prev) => ({
          ...prev,
          [nodeId]: 'must be valid JSON',
        }));
      }
    },
    [handleUpdateNodeData, selectedNode],
  );

  const handleUpload = useCallback((files: File[]) => {
    if (files && files.length > 0) {
      setImageFile(files[0]);
    }
  }, []);

  const navigateBackToAgents = useCallback(() => {
    navigate(folderId ? `/agents?folder=${folderId}` : '/agents');
  }, [navigate, folderId]);

  const handleDeleteAgent = useCallback(async () => {
    const agentToDelete = currentAgentId || currentAgent.id;
    if (!agentToDelete) return;
    setIsDeletingAgent(true);
    try {
      const response = await userService.deleteAgent(agentToDelete, token);
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || 'Failed to delete workflow agent');
      }
      navigateBackToAgents();
    } catch (error) {
      setPublishErrors([
        error instanceof Error
          ? error.message
          : 'Failed to delete workflow agent',
      ]);
      setErrorContext('publish');
    } finally {
      setIsDeletingAgent(false);
    }
  }, [currentAgentId, currentAgent.id, token, navigateBackToAgents]);

  useEffect(() => {
    if (publishErrors.length > 0) {
      const timer = setTimeout(() => {
        setPublishErrors([]);
      }, 6000);
      return () => clearTimeout(timer);
    }
  }, [publishErrors.length]);

  useEffect(() => {
    if (!isPublishing) {
      setShowPrimaryActionSpinner(false);
      return;
    }

    const spinnerTimer = window.setTimeout(() => {
      setShowPrimaryActionSpinner(true);
    }, PRIMARY_ACTION_SPINNER_DELAY_MS);

    return () => window.clearTimeout(spinnerTimer);
  }, [isPublishing]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Delete' && selectedNode) {
        handleDeleteNode();
      }
      if (e.key === 'Escape') {
        setShowNodeConfig(false);
        setSelectedNode(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedNode, handleDeleteNode]);

  const handlePanelBackdropClick = useCallback(() => {
    setShowNodeConfig(false);
    setSelectedNode(null);
  }, []);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        workflowSettingsRef.current &&
        !workflowSettingsRef.current.contains(e.target as HTMLElement)
      ) {
        setShowWorkflowSettings(false);
      }
    };
    if (showWorkflowSettings) {
      document.addEventListener('mousedown', handleClickOutside);
      return () =>
        document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showWorkflowSettings]);

  useEffect(() => {
    const loadModelsAndTools = async () => {
      try {
        const modelsResponse = await modelService.getModels(null);
        if (modelsResponse.ok) {
          const modelsData = await modelsResponse.json();
          const transformedModels = modelService.transformModels(
            modelsData.models || [],
          );
          setAvailableModels(transformedModels);
          const preferredDefaultModel =
            transformedModels.find(
              (model) => model.id === modelsData.default_model_id,
            )?.id ||
            transformedModels[0]?.id ||
            '';
          setDefaultAgentModelId(preferredDefaultModel);
        }

        const toolsResponse = await userService.getUserTools(null);
        if (toolsResponse.ok) {
          const toolsData = await toolsResponse.json();
          setAvailableTools(toolsData.tools);
        }
      } catch (error) {
        console.error('Failed to load models or tools:', error);
      }
    };
    loadModelsAndTools();
  }, []);

  useEffect(() => {
    if (!selectedNode || selectedNode.type !== 'agent') return;
    if (!defaultAgentModelId) return;
    if (selectedNode.data.config?.model_id) return;

    handleUpdateNodeData({
      config: {
        ...(selectedNode.data.config || {}),
        model_id: defaultAgentModelId,
        llm_name:
          availableModels.find((model) => model.id === defaultAgentModelId)
            ?.provider || '',
      },
    });
  }, [
    selectedNode,
    defaultAgentModelId,
    availableModels,
    handleUpdateNodeData,
  ]);

  useEffect(() => {
    if (!selectedNode || selectedNode.type !== 'agent') return;
    const nodeId = selectedNode.id;
    const rawSchema = selectedNode.data.config?.json_schema;

    setAgentJsonSchemaDrafts((prev) => {
      if (prev[nodeId] !== undefined) return prev;
      if (rawSchema === undefined || rawSchema === null) {
        return { ...prev, [nodeId]: '' };
      }

      try {
        return { ...prev, [nodeId]: JSON.stringify(rawSchema, null, 2) };
      } catch {
        return { ...prev, [nodeId]: String(rawSchema) };
      }
    });

    setAgentJsonSchemaErrors((prev) => {
      if (prev[nodeId] !== undefined) return prev;
      return { ...prev, [nodeId]: validateJsonSchemaConfig(rawSchema) };
    });
  }, [selectedNode]);

  useEffect(() => {
    const loadAgentDetails = async () => {
      if (!agentId) return;
      try {
        const response = await userService.getAgent(agentId, token);
        if (!response.ok) throw new Error('Failed to fetch agent');
        const agent = await response.json();
        setCurrentAgent({
          ...createEmptyWorkflowAgent(),
          ...agent,
          agent_type: 'workflow',
        });
        if (agent.agent_type === 'workflow' && agent.workflow) {
          setWorkflowId(agent.workflow);
          setCurrentAgentId(agent.id);
          setWorkflowName(agent.name);
          setWorkflowDescription(agent.description || '');
        }
      } catch (error) {
        console.error('Failed to load agent:', error);
      }
    };
    loadAgentDetails();
  }, [agentId, token]);

  useEffect(() => {
    const loadWorkflow = async () => {
      if (!workflowId) return;
      try {
        const response = await userService.getWorkflow(workflowId, token);
        if (!response.ok) throw new Error('Failed to fetch workflow');
        const responseData = await response.json();
        const { workflow, nodes: apiNodes, edges: apiEdges } = responseData;
        const nextWorkflowName = workflow.name;
        const nextWorkflowDescription = workflow.description || '';
        const mappedNodes = apiNodes.map((n: WorkflowNode) => {
          const nodeData: Record<string, unknown> = {
            title: n.title,
            label: n.title,
          };
          if (n.type === 'agent' && n.data) {
            nodeData.config = n.data;
          } else if (n.type === 'condition' && n.data) {
            nodeData.config = {
              ...n.data,
              cases: normalizeConditionCases(n.data.cases || []),
            };
          } else if (n.type === 'state' && n.data) {
            nodeData.config = n.data;
          } else if (n.data) {
            Object.assign(nodeData, n.data);
          }
          return {
            id: n.id,
            type: n.type,
            position: n.position,
            data: nodeData,
          };
        });
        const mappedEdges = apiEdges.map(
          (e: {
            id: string;
            source: string;
            target: string;
            sourceHandle?: string;
            targetHandle?: string;
          }) => ({
            id: e.id,
            source: e.source,
            target: e.target,
            sourceHandle: e.sourceHandle,
            targetHandle: e.targetHandle,
          }),
        );
        setWorkflowName(nextWorkflowName);
        setWorkflowDescription(nextWorkflowDescription);
        setAgentJsonSchemaDrafts({});
        setAgentJsonSchemaErrors({});
        setNodes(mappedNodes);
        setEdges(mappedEdges);
        setSavedWorkflowSignature(
          JSON.stringify(
            createWorkflowPayload(
              nextWorkflowName,
              nextWorkflowDescription,
              mappedNodes,
              mappedEdges,
            ),
          ),
        );
        setTimeout(() => {
          reactFlowInstance.fitView({
            padding: 0.2,
            maxZoom: 0.8,
            duration: 300,
          });
        }, 100);
      } catch (error) {
        console.error('Failed to load workflow:', error);
      }
    };
    loadWorkflow();
  }, [workflowId, reactFlowInstance, token]);

  const validateWorkflow = useCallback((): string[] => {
    const errors: string[] = [];

    if (!workflowName.trim()) {
      errors.push('Workflow name is required');
    }

    const startNodes = nodes.filter((n) => n.type === 'start');
    if (startNodes.length !== 1) {
      errors.push('Workflow must have exactly one start node');
    }

    const endNodes = nodes.filter((n) => n.type === 'end');
    const endNodeIds = new Set(endNodes.map((n) => n.id));
    if (endNodes.length === 0) {
      errors.push('Workflow must have at least one end node');
    }

    const agentNodes = nodes.filter((n) => n.type === 'agent');
    if (agentNodes.length === 0) {
      errors.push('Workflow must have at least one AI agent node');
    }

    agentNodes.forEach((node) => {
      const config = node.data?.config;
      if (!config?.llm_name && !config?.model_id) {
        errors.push(
          `Agent "${node.data?.title || node.id}" must have a model selected`,
        );
      }

      const hasSchema =
        config?.json_schema !== undefined && config?.json_schema !== null;
      if (hasSchema && config?.model_id) {
        const selectedModel = availableModels.find(
          (model) => model.id === config.model_id,
        );
        if (selectedModel && !selectedModel.supports_structured_output) {
          errors.push(
            `Agent "${node.data?.title || node.id}" selected model does not support structured output`,
          );
        }
      }

      const schemaValidationError = validateJsonSchemaConfig(
        config?.json_schema,
      );
      const draftSchemaError = agentJsonSchemaErrors[node.id];
      const effectiveSchemaError =
        draftSchemaError !== undefined
          ? draftSchemaError
          : schemaValidationError;
      if (effectiveSchemaError) {
        errors.push(
          `Agent "${node.data?.title || node.id}" JSON schema ${effectiveSchemaError}`,
        );
      }
    });

    if (startNodes.length === 1) {
      const startId = startNodes[0].id;
      const hasOutgoing = edges.some((e) => e.source === startId);
      if (!hasOutgoing) {
        errors.push('Start node must be connected to another node');
      }
    }

    endNodes.forEach((endNode) => {
      const hasIncoming = edges.some((e) => e.target === endNode.id);
      if (!hasIncoming) {
        errors.push(
          `End node "${endNode.id}" must have an incoming connection`,
        );
      }
    });

    const nodeIds = new Set(nodes.map((n) => n.id));
    edges.forEach((edge) => {
      if (!nodeIds.has(edge.source)) {
        errors.push(`Edge references non-existent source node`);
      }
      if (!nodeIds.has(edge.target)) {
        errors.push(`Edge references non-existent target node`);
      }
    });

    const conditionNodes = nodes.filter((n) => n.type === 'condition');
    conditionNodes.forEach((node) => {
      const conditionTitle = node.data?.title || node.id;
      const conditionMode = node.data?.config?.mode || 'simple';
      const cases = (node.data?.config?.cases || []) as ConditionCase[];
      if (
        !cases.length ||
        !cases.some((c: ConditionCase) => Boolean((c.expression || '').trim()))
      ) {
        errors.push(
          `Condition "${conditionTitle}" must have at least one case with an expression`,
        );
      }

      const caseHandles = new Set<string>();
      const duplicateCaseHandles = new Set<string>();
      cases.forEach((conditionCase: ConditionCase) => {
        const handle = (conditionCase.sourceHandle || '').trim();
        if (!handle) {
          errors.push(
            `Condition "${conditionTitle}" has a case without a branch handle`,
          );
          return;
        }
        if (caseHandles.has(handle)) {
          duplicateCaseHandles.add(handle);
        }
        caseHandles.add(handle);
      });
      duplicateCaseHandles.forEach((handle) => {
        errors.push(
          `Condition "${conditionTitle}" has duplicate case handle "${handle}"`,
        );
      });

      const outgoing = edges.filter((e) => e.source === node.id);
      if (outgoing.length < 2) {
        errors.push(
          `Condition "${conditionTitle}" must have at least 2 outgoing connections`,
        );
      }

      const outgoingByHandle = new Map<string, Edge[]>();
      outgoing.forEach((edge) => {
        const handle = (edge.sourceHandle || '').trim();
        const handleEdges = outgoingByHandle.get(handle);
        if (handleEdges) {
          handleEdges.push(edge);
          return;
        }
        outgoingByHandle.set(handle, [edge]);
      });

      for (const [handle, handleEdges] of outgoingByHandle.entries()) {
        if (!handle) {
          errors.push(
            `Condition "${conditionTitle}" has a connection without a branch handle`,
          );
          continue;
        }
        if (handle !== 'else' && !caseHandles.has(handle)) {
          errors.push(
            `Condition "${conditionTitle}" has a connection from unknown branch "${handle}"`,
          );
        }
        if (handleEdges.length > 1) {
          errors.push(
            `Condition "${conditionTitle}" has multiple connections from branch "${handle}"`,
          );
        }
      }

      if (!outgoingByHandle.has('else')) {
        errors.push(`Condition "${conditionTitle}" must have an Else branch`);
      }

      cases.forEach((conditionCase: ConditionCase) => {
        const handle = (conditionCase.sourceHandle || '').trim();
        if (!handle) return;

        const hasExpression = Boolean((conditionCase.expression || '').trim());
        const hasOutgoing = Boolean(outgoingByHandle.get(handle)?.length);
        if (hasExpression && !hasOutgoing) {
          errors.push(
            `Condition "${conditionTitle}" case "${handle}" has an expression but no branch connection`,
          );
        }
        if (!hasExpression && hasOutgoing) {
          errors.push(
            `Condition "${conditionTitle}" case "${handle}" has a branch connection but no expression`,
          );
        }
        if (conditionMode === 'simple' && hasExpression) {
          const parsedCondition = parseSimpleCel(
            conditionCase.expression || '',
          );
          if (!parsedCondition.variable.trim()) {
            errors.push(
              `Condition "${conditionTitle}" case "${handle}" must specify a variable in Simple mode`,
            );
          }
        }
      });

      outgoing.forEach((edge) => {
        if (!canReachEnd(edge.target, edges, nodeIds, endNodeIds)) {
          const handle = edge.sourceHandle || 'branch';
          errors.push(
            `Branch "${handle}" of condition "${conditionTitle}" must eventually reach an end node`,
          );
        }
      });
    });

    return errors;
  }, [workflowName, nodes, edges, agentJsonSchemaErrors, availableModels]);

  const canManageAgent = Boolean(currentAgentId || currentAgent.id);
  const effectiveAgentId = currentAgentId || currentAgent.id || '';
  const currentAgentImage = currentAgent.image || '';

  const buildWorkflowPayload = useCallback(
    () =>
      createWorkflowPayload(workflowName, workflowDescription, nodes, edges),
    [workflowName, workflowDescription, nodes, edges],
  );

  const workflowPayloadSignature = useMemo(
    () => JSON.stringify(buildWorkflowPayload()),
    [buildWorkflowPayload],
  );

  const hasSavableChanges =
    canManageAgent && savedWorkflowSignature !== null
      ? workflowPayloadSignature !== savedWorkflowSignature ||
        imageFile !== null
      : false;

  const persistWorkflow = useCallback(
    async (navigateAfterSuccess: boolean): Promise<boolean> => {
      setPublishErrors([]);
      setErrorContext('publish');

      const validationErrors = validateWorkflow();
      if (validationErrors.length > 0) {
        setPublishErrors(validationErrors);
        return false;
      }

      setIsPublishing(true);
      let createdWorkflowId: string | null = null;
      try {
        const workflowPayload = buildWorkflowPayload();

        let savedWorkflowId = workflowId;
        if (workflowId) {
          const updateResponse = await userService.updateWorkflow(
            workflowId,
            workflowPayload,
            token,
          );
          if (!updateResponse.ok) {
            const errorData = await updateResponse.json().catch(() => ({}));
            throw new Error(errorData.message || 'Failed to update workflow');
          }

          if (effectiveAgentId) {
            const agentFormData = new FormData();
            agentFormData.append('name', workflowName);
            agentFormData.append(
              'description',
              workflowDescription || `Workflow agent: ${workflowName}`,
            );
            agentFormData.append('status', 'published');
            if (imageFile) {
              agentFormData.append('image', imageFile);
            }
            const agentUpdateResponse = await userService.updateAgent(
              effectiveAgentId,
              agentFormData,
              token,
            );
            if (!agentUpdateResponse.ok) {
              throw new Error('Failed to update agent');
            }
            const updatedAgent = await agentUpdateResponse
              .json()
              .catch(() => null);
            setCurrentAgent((prev) => ({
              ...prev,
              ...(updatedAgent || {}),
              id: effectiveAgentId,
              name: workflowName,
              description:
                workflowDescription || `Workflow agent: ${workflowName}`,
              image: updatedAgent?.image || prev.image || '',
            }));
          }
          setImageFile(null);
          setSavedWorkflowSignature(JSON.stringify(workflowPayload));
          if (navigateAfterSuccess) {
            navigateBackToAgents();
          }
          return true;
        }

        const createResponse = await userService.createWorkflow(
          workflowPayload,
          token,
        );
        if (!createResponse.ok) {
          const errorData = await createResponse.json().catch(() => ({}));
          const backendErrors = errorData.errors || [];
          if (backendErrors.length > 0) {
            setPublishErrors(backendErrors);
            return false;
          }
          throw new Error(errorData.message || 'Failed to create workflow');
        }
        const responseData = await createResponse.json();
        savedWorkflowId = responseData.id;
        createdWorkflowId = savedWorkflowId || null;
        if (savedWorkflowId) {
          setWorkflowId(savedWorkflowId);
        }

        const agentFormData = new FormData();
        agentFormData.append('name', workflowName);
        agentFormData.append(
          'description',
          workflowDescription || `Workflow agent: ${workflowName}`,
        );
        agentFormData.append('agent_type', 'workflow');
        agentFormData.append('status', 'published');
        agentFormData.append('workflow', savedWorkflowId || '');
        if (imageFile) {
          agentFormData.append('image', imageFile);
        }
        if (folderId) agentFormData.append('folder_id', folderId);

        const agentResponse = await userService.createAgent(
          agentFormData,
          token,
        );
        if (!agentResponse.ok) {
          const errorData = await agentResponse.json().catch(() => ({}));
          throw new Error(errorData.message || 'Failed to create agent');
        }
        const agentData = await agentResponse.json().catch(() => ({}));
        if (agentData?.id) {
          setCurrentAgentId(agentData.id);
          setCurrentAgent({
            ...createEmptyWorkflowAgent(),
            ...agentData,
            id: agentData.id,
            name: workflowName,
            description:
              workflowDescription || `Workflow agent: ${workflowName}`,
            image: agentData.image || '',
            workflow: savedWorkflowId || undefined,
            agent_type: 'workflow',
            status: 'published',
          });
        }

        setImageFile(null);
        setSavedWorkflowSignature(JSON.stringify(workflowPayload));
        if (navigateAfterSuccess) {
          navigateBackToAgents();
        }
        return true;
      } catch (error) {
        if (createdWorkflowId) {
          try {
            const cleanupResponse = await userService.deleteWorkflow(
              createdWorkflowId,
              token,
            );
            if (cleanupResponse.ok) {
              setWorkflowId(null);
            }
          } catch (cleanupError) {
            console.error(
              'Failed to clean up workflow after publish error:',
              cleanupError,
            );
          }
        }
        console.error('Failed to save workflow:', error);
        setPublishErrors([
          error instanceof Error ? error.message : 'Failed to save workflow',
        ]);
        return false;
      } finally {
        setIsPublishing(false);
      }
    },
    [
      validateWorkflow,
      buildWorkflowPayload,
      workflowId,
      token,
      effectiveAgentId,
      workflowName,
      workflowDescription,
      imageFile,
      folderId,
      navigateBackToAgents,
    ],
  );

  const handleWorkflowSettingsDone = useCallback(() => {
    setShowWorkflowSettings(false);
    if (!canManageAgent || !hasSavableChanges || isPublishing) return;
    void persistWorkflow(false);
  }, [canManageAgent, hasSavableChanges, isPublishing, persistWorkflow]);

  const isPrimaryActionDisabled =
    isPublishing || (canManageAgent && !hasSavableChanges);
  const primaryActionLabel = canManageAgent ? 'Save' : 'Publish';

  const handlePrimaryAction = useCallback(() => {
    if (isPrimaryActionDisabled) return;
    void persistWorkflow(!canManageAgent);
  }, [isPrimaryActionDisabled, persistWorkflow, canManageAgent]);

  const agentForDetails = useMemo<Agent>(
    () => ({
      ...createEmptyWorkflowAgent(),
      ...currentAgent,
      id: effectiveAgentId,
      name: workflowName,
      description: workflowDescription || `Workflow agent: ${workflowName}`,
      image: currentAgentImage,
      agent_type: 'workflow',
      status: currentAgent.status || 'published',
      workflow: workflowId || currentAgent.workflow,
    }),
    [
      currentAgent,
      effectiveAgentId,
      workflowName,
      workflowDescription,
      currentAgentImage,
      workflowId,
    ],
  );

  const selectedAgentJsonSchemaText = useMemo(() => {
    if (!selectedNode || selectedNode.type !== 'agent') return '';

    const draft = agentJsonSchemaDrafts[selectedNode.id];
    if (draft !== undefined) return draft;

    const schema = selectedNode.data.config?.json_schema;
    if (schema === undefined || schema === null) return '';

    try {
      return JSON.stringify(schema, null, 2);
    } catch {
      return String(schema);
    }
  }, [selectedNode, agentJsonSchemaDrafts]);

  const selectedAgentJsonSchemaError = useMemo(() => {
    if (!selectedNode || selectedNode.type !== 'agent') return null;

    const cachedError = agentJsonSchemaErrors[selectedNode.id];
    if (cachedError !== undefined) return cachedError;

    return validateJsonSchemaConfig(selectedNode.data.config?.json_schema);
  }, [selectedNode, agentJsonSchemaErrors]);

  const selectedAgentModelSupportsStructuredOutput = useMemo(() => {
    if (!selectedNode || selectedNode.type !== 'agent') return true;
    const modelId = selectedNode.data.config?.model_id;
    if (!modelId) return true;

    const selectedModel = availableModels.find((model) => model.id === modelId);
    if (!selectedModel) return true;

    return selectedModel.supports_structured_output;
  }, [selectedNode, availableModels]);

  return (
    <>
      <MobileBlocker />
      <div className="bg-lotion dark:bg-outer-space fixed inset-0 z-50 hidden h-screen w-full flex-col md:flex">
        <div className="border-light-silver dark:bg-raisin-black flex items-center justify-between border-b bg-white px-6 py-4 dark:border-[#3A3A3A]">
          <div className="flex items-center gap-4">
            <button
              onClick={navigateBackToAgents}
              className="rounded-full border p-3 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
            >
              <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
            </button>
            <div className="group relative flex items-center gap-2">
              <div>
                <div
                  className="max-w-xs truncate text-xl font-bold text-gray-900 dark:text-white"
                  title={workflowName || 'New Workflow'}
                >
                  {workflowName || 'New Workflow'}
                </div>
                {workflowDescription && (
                  <div
                    className="max-w-xs truncate text-xs text-gray-500 dark:text-gray-400"
                    title={workflowDescription}
                  >
                    {workflowDescription}
                  </div>
                )}
              </div>
              <button
                onClick={() => setShowWorkflowSettings(!showWorkflowSettings)}
                className="text-gray-400 opacity-0 transition-opacity group-hover:opacity-100 hover:text-gray-600 dark:hover:text-gray-200"
              >
                <Pencil size={14} />
              </button>
              {showWorkflowSettings && (
                <div
                  ref={workflowSettingsRef}
                  className="dark:bg-raisin-black absolute top-full left-0 z-50 mt-2 w-80 rounded-xl border border-[#E5E5E5] bg-white p-4 shadow-lg dark:border-[#3A3A3A]"
                >
                  <div className="mb-3">
                    <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                      Workflow Name
                    </label>
                    <input
                      type="text"
                      value={workflowName}
                      onChange={(e) => setWorkflowName(e.target.value)}
                      className="focus:ring-purple-30 w-full rounded-lg border border-[#E5E5E5] bg-white px-3 py-2 text-sm outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-white"
                      placeholder="Enter workflow name"
                    />
                  </div>
                  <div className="mb-3">
                    <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                      Description
                    </label>
                    <textarea
                      value={workflowDescription}
                      onChange={(e) => setWorkflowDescription(e.target.value)}
                      className="focus:ring-purple-30 w-full rounded-lg border border-[#E5E5E5] bg-white px-3 py-2 text-sm outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-white"
                      rows={3}
                      placeholder="Describe what this workflow does"
                    />
                  </div>
                  <div className="mb-3">
                    <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                      Agent Image
                    </label>
                    {currentAgentImage && !imageFile && (
                      <div className="mb-2 flex items-center gap-2">
                        <img
                          src={currentAgentImage}
                          alt="Agent image"
                          className="h-10 w-10 rounded-full object-cover"
                        />
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          Current image
                        </span>
                      </div>
                    )}
                    <FileUpload
                      showPreview
                      maxFiles={1}
                      previewSize={56}
                      onUpload={handleUpload}
                      onRemove={() => setImageFile(null)}
                      uploadText={[
                        {
                          text: 'Click to upload',
                          colorClass: 'text-violets-are-blue',
                        },
                        {
                          text: ' or drag and drop',
                          colorClass: 'text-gray-500',
                        },
                      ]}
                      className="rounded-lg border-2 border-dashed border-[#E5E5E5] p-3 text-center transition-colors dark:border-[#3A3A3A] dark:bg-[#2C2C2C]"
                    />
                    <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                      Image updates are included the next time you save.
                    </p>
                  </div>
                  <button
                    onClick={handleWorkflowSettingsDone}
                    disabled={isPublishing}
                    className="bg-violets-are-blue hover:bg-purple-30 w-full rounded-lg px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Done
                  </button>
                </div>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowWorkflowSettings((prev) => !prev)}
              className="flex items-center gap-2 rounded-full border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-gray-200 dark:hover:bg-[#383838]"
            >
              <Settings2 size={16} />
              Details
            </button>
            {canManageAgent && (
              <button
                onClick={() => navigate(`/agents/logs/${effectiveAgentId}`)}
                className="flex items-center gap-2 rounded-full border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-gray-200 dark:hover:bg-[#383838]"
              >
                <ChartColumn size={16} />
                Logs
              </button>
            )}
            {canManageAgent && (
              <button
                onClick={() => setAgentDetails('ACTIVE')}
                className="flex items-center gap-2 rounded-full border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-gray-200 dark:hover:bg-[#383838]"
              >
                <Link size={16} />
                Access Details
              </button>
            )}
            {canManageAgent && (
              <button
                onClick={() => setDeleteConfirmation('ACTIVE')}
                disabled={isDeletingAgent}
                className="flex items-center gap-2 rounded-full border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-900/30 dark:bg-[#2C2C2C] dark:text-red-400 dark:hover:bg-red-900/10"
              >
                <Trash2 size={16} />
                {isDeletingAgent ? 'Deleting...' : 'Delete'}
              </button>
            )}
            <button
              onClick={() => {
                const validationErrors = validateWorkflow();
                if (validationErrors.length > 0) {
                  setErrorContext('preview');
                  setPublishErrors(validationErrors);
                  return;
                }
                setShowPreview(true);
              }}
              className="flex items-center gap-2 rounded-full border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-gray-200 dark:hover:bg-[#383838]"
            >
              <Play size={16} />
              Preview
            </button>
            <button
              onClick={handlePrimaryAction}
              disabled={isPrimaryActionDisabled}
              className={`relative inline-flex items-center justify-center rounded-full px-6 py-2 text-sm font-medium shadow-sm transition-colors disabled:cursor-not-allowed ${
                canManageAgent && !hasSavableChanges
                  ? 'bg-gray-200 text-gray-500 dark:bg-[#3A3A3A] dark:text-gray-400'
                  : 'bg-violets-are-blue hover:bg-purple-30 text-white disabled:opacity-50'
              }`}
            >
              <span
                className={
                  showPrimaryActionSpinner ? 'opacity-0' : 'opacity-100'
                }
              >
                {primaryActionLabel}
              </span>
              {showPrimaryActionSpinner ? (
                <Loader2 size={16} className="absolute animate-spin" />
              ) : null}
            </button>
          </div>
        </div>

        {publishErrors.length > 0 && (
          <div className="pointer-events-none absolute top-20 right-0 left-0 z-50 flex justify-center px-4">
            <Alert
              variant="destructive"
              className="pointer-events-auto w-full max-w-md bg-red-50 shadow-lg dark:bg-red-950/20"
            >
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>
                {errorContext === 'preview'
                  ? 'Unable to preview workflow'
                  : canManageAgent
                    ? 'Unable to save workflow'
                    : 'Unable to publish workflow'}
              </AlertTitle>
              <AlertDescription>
                <ul className="mt-2 list-inside list-disc space-y-1 wrap-break-word">
                  {publishErrors.map((error, index) => (
                    <li key={index}>{error}</li>
                  ))}
                </ul>
              </AlertDescription>
              <button
                onClick={() => setPublishErrors([])}
                className="absolute top-4 right-4 text-red-700 hover:text-red-900 dark:text-red-300 dark:hover:text-red-100"
              >
                <X size={16} />
              </button>
            </Alert>
          </div>
        )}

        <div className="flex flex-1 overflow-hidden">
          <div className="border-light-silver dark:bg-raisin-black flex w-64 flex-col gap-6 border-r bg-gray-50 p-4 dark:border-[#3A3A3A]">
            <div>
              <h3 className="mb-3 text-xs font-semibold tracking-wider text-gray-500 uppercase dark:text-gray-400">
                Core Nodes
              </h3>
              <div className="flex flex-col gap-2">
                <div
                  className="group flex cursor-move items-center gap-3 rounded-full border bg-white px-4 py-3 shadow-sm transition-all hover:shadow-md dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:hover:bg-[#383838]"
                  draggable
                  onDragStart={(e) => handleNodeDragStart(e, 'agent')}
                >
                  <div className="text-violets-are-blue group-hover:bg-violets-are-blue flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-purple-100 transition-colors group-hover:text-white">
                    <Bot size={18} />
                  </div>
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
                    AI Agent
                  </span>
                </div>
                <div
                  className="group flex cursor-move items-center gap-3 rounded-full border bg-white px-4 py-3 shadow-sm transition-all hover:shadow-md dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:hover:bg-[#383838]"
                  draggable
                  onDragStart={(e) => handleNodeDragStart(e, 'end')}
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-green-100 text-green-600 transition-colors group-hover:bg-green-600 group-hover:text-white">
                    <Flag size={18} />
                  </div>
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
                    End
                  </span>
                </div>
                <div
                  className="group flex cursor-move items-center gap-3 rounded-full border bg-white px-4 py-3 shadow-sm transition-all hover:shadow-md dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:hover:bg-[#383838]"
                  draggable
                  onDragStart={(e) => handleNodeDragStart(e, 'note')}
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-yellow-100 text-yellow-600 transition-colors group-hover:bg-yellow-500 group-hover:text-white">
                    <StickyNote size={18} />
                  </div>
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
                    Note
                  </span>
                </div>
              </div>
            </div>

            <div>
              <h3 className="mb-3 text-xs font-semibold tracking-wider text-gray-500 uppercase dark:text-gray-400">
                Logic & Data
              </h3>
              <div className="flex flex-col gap-2">
                <div
                  className="group flex cursor-move items-center gap-3 rounded-full border bg-white px-4 py-3 shadow-sm transition-all hover:shadow-md dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:hover:bg-[#383838]"
                  draggable
                  onDragStart={(e) => handleNodeDragStart(e, 'state')}
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-600 transition-colors group-hover:bg-blue-600 group-hover:text-white">
                    <Database size={18} />
                  </div>
                  <div className="flex flex-col">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
                      Set State
                    </span>
                    <span className="text-[10px] text-gray-400">
                      Modify workflow variables
                    </span>
                  </div>
                </div>
                <div
                  className="group flex cursor-move items-center gap-3 rounded-full border bg-white px-4 py-3 shadow-sm transition-all hover:shadow-md dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:hover:bg-[#383838]"
                  draggable
                  onDragStart={(e) => handleNodeDragStart(e, 'condition')}
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-orange-100 text-orange-600 transition-colors group-hover:bg-orange-600 group-hover:text-white">
                    <GitBranch size={18} />
                  </div>
                  <div className="flex flex-col">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
                      If / Else
                    </span>
                    <span className="text-[10px] text-gray-400">
                      Conditional branching
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div
            ref={reactFlowWrapper}
            className="dark:bg-raisin-black/10 relative flex-1 bg-gray-50"
          >
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onEdgeClick={onEdgeClick}
              onDrop={onDrop}
              onDragOver={onDragOver}
              onNodeClick={handleNodeClick}
              nodeTypes={nodeTypes}
              deleteKeyCode={['Backspace', 'Delete']}
              fitView
            >
              <Background />
              <Controls />
            </ReactFlow>

            {showNodeConfig && selectedNode && (
              <>
                <div
                  className="absolute inset-0 z-10"
                  onClick={handlePanelBackdropClick}
                />
                <div className="border-light-silver dark:bg-raisin-black absolute top-4 right-4 z-20 w-96 rounded-2xl border bg-white shadow-[0px_4px_40px_-3px_#0000001A] dark:border-[#3A3A3A]">
                  <div className="border-light-silver flex items-center justify-between border-b p-4 dark:border-[#3A3A3A]">
                    <h3 className="font-semibold text-gray-900 dark:text-white">
                      {selectedNode.type === 'start' && 'Start Node'}
                      {selectedNode.type === 'end' && 'End Node'}
                      {selectedNode.type === 'agent' && 'AI Agent'}
                      {selectedNode.type === 'note' && 'Note'}
                      {selectedNode.type === 'state' && 'Set global variables'}
                      {selectedNode.type === 'condition' && 'If / Else'}
                    </h3>
                    <button
                      onClick={() => setShowNodeConfig(false)}
                      className="text-gray-400 transition-colors hover:text-gray-600 dark:hover:text-gray-200"
                    >
                      <X size={20} />
                    </button>
                  </div>

                  <div className="max-h-[calc(100vh-200px)] overflow-y-auto p-4">
                    <div className="mb-4 flex flex-col gap-2">
                      <div className="rounded-lg bg-gray-50 p-3 dark:bg-[#2C2C2C]">
                        <div className="mb-1 text-xs text-gray-500 dark:text-gray-400">
                          Node ID
                        </div>
                        <div className="truncate font-mono text-xs text-gray-700 dark:text-gray-300">
                          {selectedNode.id}
                        </div>
                      </div>

                      {selectedNode.type !== 'start' &&
                        selectedNode.type !== 'end' && (
                          <>
                            <div>
                              <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                                Title
                              </label>
                              <input
                                type="text"
                                value={
                                  selectedNode.data.title ||
                                  selectedNode.data.label ||
                                  ''
                                }
                                onChange={(e) =>
                                  handleUpdateNodeData({
                                    title: e.target.value,
                                    label: e.target.value,
                                  })
                                }
                                className="border-light-silver focus:ring-purple-30 w-full rounded-xl border bg-white px-3 py-2 text-sm transition-all outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-white"
                                placeholder="Enter node title"
                              />
                            </div>

                            {selectedNode.type === 'agent' && (
                              <>
                                <div>
                                  <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                                    Agent Type
                                  </label>
                                  <Select
                                    value={
                                      selectedNode.data.config?.agent_type ||
                                      'classic'
                                    }
                                    onValueChange={(value) =>
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          agent_type: value,
                                        },
                                      })
                                    }
                                  >
                                    <SelectTrigger className="w-full">
                                      <SelectValue placeholder="Select agent type" />
                                    </SelectTrigger>
                                    <SelectContent>
                                      <SelectItem value="classic">
                                        Classic
                                      </SelectItem>
                                      <SelectItem value="react">
                                        ReAct
                                      </SelectItem>
                                    </SelectContent>
                                  </Select>
                                </div>
                                <div>
                                  <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                                    Model
                                  </label>
                                  <Select
                                    value={
                                      selectedNode.data.config?.model_id || ''
                                    }
                                    onValueChange={(value) => {
                                      const selectedModel =
                                        availableModels.find(
                                          (m) => m.id === value,
                                        );
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          model_id: value,
                                          llm_name:
                                            selectedModel?.provider || '',
                                        },
                                      });
                                    }}
                                  >
                                    <SelectTrigger className="w-full">
                                      <SelectValue placeholder="Select a model" />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {availableModels.map((model) => (
                                        <SelectItem
                                          key={model.id}
                                          value={model.id}
                                        >
                                          {model.display_name} ·{' '}
                                          {model.provider}
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </div>
                                <div>
                                  <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                                    System Prompt
                                  </label>
                                  <textarea
                                    value={
                                      selectedNode.data.config?.system_prompt ??
                                      ''
                                    }
                                    onChange={(e) =>
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          system_prompt: e.target.value,
                                        },
                                      })
                                    }
                                    className="border-light-silver focus:ring-purple-30 w-full rounded-xl border bg-white px-3 py-2 text-sm transition-all outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-white"
                                    rows={3}
                                    placeholder="System prompt for the agent"
                                  />
                                </div>
                                <PromptTextArea
                                  label="Prompt Template"
                                  value={
                                    selectedNode.data.config?.prompt_template ||
                                    ''
                                  }
                                  onChange={(val) =>
                                    handleUpdateNodeData({
                                      config: {
                                        ...(selectedNode.data.config || {}),
                                        prompt_template: val,
                                      },
                                    })
                                  }
                                  nodes={nodes}
                                  edges={edges}
                                  selectedNodeId={selectedNode.id}
                                  placeholder="Use {{ agent.variable }} for dynamic content"
                                />
                                <div>
                                  <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                                    Output Variable
                                  </label>
                                  <input
                                    type="text"
                                    value={
                                      selectedNode.data.config
                                        ?.output_variable || ''
                                    }
                                    onChange={(e) => {
                                      const nextOutputVariable = e.target.value;
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          output_variable: nextOutputVariable,
                                        },
                                      });
                                    }}
                                    className="border-light-silver focus:ring-purple-30 w-full rounded-xl border bg-white px-3 py-2 text-sm transition-all outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-white"
                                    placeholder="Variable name for output"
                                  />
                                </div>
                                <div className="flex items-center gap-2">
                                  <input
                                    type="checkbox"
                                    id="stream_to_user"
                                    checked={
                                      selectedNode.data.config
                                        ?.stream_to_user ?? true
                                    }
                                    onChange={(e) =>
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          stream_to_user: e.target.checked,
                                        },
                                      })
                                    }
                                    className="h-4 w-4"
                                  />
                                  <label
                                    htmlFor="stream_to_user"
                                    className="text-sm text-gray-700 dark:text-gray-300"
                                  >
                                    Stream output to user
                                  </label>
                                </div>{' '}
                                <div>
                                  <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                                    Tools
                                  </label>
                                  <MultiSelect
                                    options={availableTools.map((tool) => ({
                                      value: tool.id,
                                      label: tool.displayName,
                                    }))}
                                    selected={
                                      selectedNode.data.config?.tools || []
                                    }
                                    onChange={(newTools) =>
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          tools: newTools,
                                        },
                                      })
                                    }
                                    placeholder="Select tools..."
                                    searchPlaceholder="Search tools..."
                                    emptyText="No tools available"
                                  />
                                </div>
                                <div>
                                  <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                                    Structured Output (JSON Schema)
                                  </label>
                                  {!selectedAgentModelSupportsStructuredOutput && (
                                    <p className="mb-2 text-xs text-red-600 dark:text-red-400">
                                      Selected model does not support structured
                                      output.
                                    </p>
                                  )}
                                  <textarea
                                    value={selectedAgentJsonSchemaText}
                                    onChange={(e) =>
                                      handleAgentJsonSchemaChange(
                                        e.target.value,
                                      )
                                    }
                                    className="border-light-silver focus:ring-purple-30 w-full rounded-xl border bg-white px-3 py-2 font-mono text-xs transition-all outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-white"
                                    rows={8}
                                    placeholder={`{
  "type": "object",
  "properties": {
    "summary": { "type": "string" }
  },
  "required": ["summary"]
}`}
                                  />
                                  {selectedAgentJsonSchemaText.trim() !==
                                    '' && (
                                    <p
                                      className={`mt-2 text-xs ${
                                        selectedAgentJsonSchemaError
                                          ? 'text-red-600 dark:text-red-400'
                                          : 'text-green-600 dark:text-green-400'
                                      }`}
                                    >
                                      {selectedAgentJsonSchemaError
                                        ? `Invalid JSON schema: ${selectedAgentJsonSchemaError}`
                                        : 'Valid JSON schema'}
                                    </p>
                                  )}
                                </div>
                              </>
                            )}

                            {selectedNode.type === 'note' && (
                              <div>
                                <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                                  Note Content
                                </label>
                                <textarea
                                  value={selectedNode.data.content || ''}
                                  onChange={(e) =>
                                    handleUpdateNodeData({
                                      content: e.target.value,
                                    })
                                  }
                                  className="border-light-silver focus:ring-purple-30 w-full rounded-xl border bg-white px-3 py-2 text-sm transition-all outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-white"
                                  rows={4}
                                  placeholder="Enter note content"
                                />
                              </div>
                            )}

                            {selectedNode.type === 'state' && (
                              <>
                                <p className="text-xs text-gray-500 dark:text-gray-400">
                                  Assign values to workflow&apos;s state
                                  variables
                                </p>
                                {(
                                  selectedNode.data.config?.operations || []
                                ).map(
                                  (
                                    op: {
                                      expression: string;
                                      target_variable: string;
                                    },
                                    idx: number,
                                  ) => (
                                    <div
                                      key={idx}
                                      className="rounded-xl border border-gray-200 p-3 dark:border-[#3A3A3A]"
                                    >
                                      <div className="mb-2 flex items-center justify-between">
                                        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                                          Assign value
                                        </span>
                                        {(
                                          selectedNode.data.config
                                            ?.operations || []
                                        ).length > 1 && (
                                          <button
                                            onClick={() => {
                                              const ops = [
                                                ...(selectedNode.data.config
                                                  ?.operations || []),
                                              ];
                                              ops.splice(idx, 1);
                                              handleUpdateNodeData({
                                                config: {
                                                  ...(selectedNode.data
                                                    .config || {}),
                                                  operations: ops,
                                                },
                                              });
                                            }}
                                            className="text-gray-400 transition-colors hover:text-red-500"
                                          >
                                            <Trash2 size={14} />
                                          </button>
                                        )}
                                      </div>
                                      <textarea
                                        value={op.expression}
                                        onChange={(e) => {
                                          const ops = [
                                            ...(selectedNode.data.config
                                              ?.operations || []),
                                          ];
                                          ops[idx] = {
                                            ...ops[idx],
                                            expression: e.target.value,
                                          };
                                          handleUpdateNodeData({
                                            config: {
                                              ...(selectedNode.data.config ||
                                                {}),
                                              operations: ops,
                                            },
                                          });
                                        }}
                                        className="border-light-silver focus:ring-purple-30 mb-1 w-full rounded-xl border bg-white px-3 py-2 text-sm transition-all outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#383838] dark:text-white"
                                        rows={2}
                                        placeholder="input.foo + 1"
                                      />
                                      <p className="mb-3 text-[10px] text-gray-400">
                                        Use Common Expression Language to create
                                        a custom expression.{' '}
                                        <a
                                          href="https://cel.dev/"
                                          target="_blank"
                                          rel="noreferrer"
                                          className="text-violets-are-blue underline"
                                        >
                                          Learn more
                                        </a>
                                      </p>
                                      <div>
                                        <span className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                                          To variable
                                        </span>
                                        <input
                                          type="text"
                                          value={op.target_variable}
                                          onChange={(e) => {
                                            const ops = [
                                              ...(selectedNode.data.config
                                                ?.operations || []),
                                            ];
                                            ops[idx] = {
                                              ...ops[idx],
                                              target_variable: e.target.value,
                                            };
                                            handleUpdateNodeData({
                                              config: {
                                                ...(selectedNode.data.config ||
                                                  {}),
                                                operations: ops,
                                              },
                                            });
                                          }}
                                          className="border-light-silver focus:ring-purple-30 w-full rounded-xl border bg-white px-3 py-2 text-sm transition-all outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#383838] dark:text-white"
                                          placeholder="variable_name"
                                        />
                                      </div>
                                    </div>
                                  ),
                                )}
                                <button
                                  onClick={() => {
                                    const ops = [
                                      ...(selectedNode.data.config
                                        ?.operations || []),
                                      { expression: '', target_variable: '' },
                                    ];
                                    handleUpdateNodeData({
                                      config: {
                                        ...(selectedNode.data.config || {}),
                                        operations: ops,
                                      },
                                    });
                                  }}
                                  className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-[#383838]"
                                >
                                  <Plus size={14} />
                                  Add
                                </button>
                              </>
                            )}

                            {selectedNode.type === 'condition' && (
                              <>
                                <p className="text-xs text-gray-500 dark:text-gray-400">
                                  Create conditions to branch your workflow
                                </p>
                                <div className="flex overflow-hidden rounded-lg border border-gray-200 dark:border-[#3A3A3A]">
                                  <button
                                    onClick={() =>
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          mode: 'simple',
                                        },
                                      })
                                    }
                                    className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors ${
                                      (selectedNode.data.config?.mode ||
                                        'simple') === 'simple'
                                        ? 'bg-violets-are-blue text-white'
                                        : 'text-gray-600 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-[#383838]'
                                    }`}
                                  >
                                    Simple
                                  </button>
                                  <button
                                    onClick={() =>
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          mode: 'advanced',
                                        },
                                      })
                                    }
                                    className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors ${
                                      selectedNode.data.config?.mode ===
                                      'advanced'
                                        ? 'bg-violets-are-blue text-white'
                                        : 'text-gray-600 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-[#383838]'
                                    }`}
                                  >
                                    Advanced
                                  </button>
                                </div>

                                {(selectedNode.data.config?.cases || []).map(
                                  (c: ConditionCase, idx: number) => (
                                    <div
                                      key={c.sourceHandle}
                                      className="rounded-xl border border-gray-200 p-3 dark:border-[#3A3A3A]"
                                    >
                                      <div className="mb-2 flex items-center justify-between">
                                        <span className="text-sm font-semibold text-orange-600 dark:text-orange-400">
                                          {idx === 0 ? 'If' : 'Else if'}
                                        </span>
                                        {(selectedNode.data.config?.cases || [])
                                          .length > 1 && (
                                          <button
                                            onClick={() => {
                                              const cases =
                                                normalizeConditionCases([
                                                  ...(selectedNode.data.config
                                                    ?.cases || []),
                                                ]);
                                              const removedHandle =
                                                cases[idx]?.sourceHandle;
                                              cases.splice(idx, 1);
                                              handleUpdateNodeData({
                                                config: {
                                                  ...(selectedNode.data
                                                    .config || {}),
                                                  cases,
                                                },
                                              });
                                              if (removedHandle) {
                                                setEdges((eds) =>
                                                  eds.filter(
                                                    (edge) =>
                                                      !(
                                                        edge.source ===
                                                          selectedNode.id &&
                                                        edge.sourceHandle ===
                                                          removedHandle
                                                      ),
                                                  ),
                                                );
                                              }
                                            }}
                                            className="text-gray-400 transition-colors hover:text-red-500"
                                          >
                                            <Trash2 size={14} />
                                          </button>
                                        )}
                                      </div>
                                      <input
                                        type="text"
                                        value={c.name || ''}
                                        onChange={(e) => {
                                          const cases = [
                                            ...(selectedNode.data.config
                                              ?.cases || []),
                                          ];
                                          cases[idx] = {
                                            ...cases[idx],
                                            name: e.target.value,
                                          };
                                          handleUpdateNodeData({
                                            config: {
                                              ...(selectedNode.data.config ||
                                                {}),
                                              cases,
                                            },
                                          });
                                        }}
                                        className="border-light-silver focus:ring-purple-30 mb-2 w-full rounded-xl border bg-white px-3 py-2 text-sm transition-all outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#383838] dark:text-white"
                                        placeholder="Case name (optional)"
                                      />
                                      {(selectedNode.data.config?.mode ||
                                        'simple') === 'simple' ? (
                                        <div className="flex items-center gap-2">
                                          <input
                                            type="text"
                                            value={
                                              parseSimpleCel(c.expression)
                                                .variable
                                            }
                                            onChange={(e) => {
                                              const parsed = parseSimpleCel(
                                                c.expression,
                                              );
                                              const cases = [
                                                ...(selectedNode.data.config
                                                  ?.cases || []),
                                              ];
                                              cases[idx] = {
                                                ...cases[idx],
                                                expression: buildSimpleCel(
                                                  e.target.value,
                                                  parsed.operator,
                                                  parsed.value,
                                                ),
                                              };
                                              handleUpdateNodeData({
                                                config: {
                                                  ...(selectedNode.data
                                                    .config || {}),
                                                  cases,
                                                },
                                              });
                                            }}
                                            className="border-light-silver focus:ring-purple-30 w-full rounded-xl border bg-white px-3 py-2 text-sm outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#383838] dark:text-white"
                                            placeholder="Variable"
                                          />
                                          <Select
                                            value={
                                              parseSimpleCel(c.expression)
                                                .operator
                                            }
                                            onValueChange={(op) => {
                                              const parsed = parseSimpleCel(
                                                c.expression,
                                              );
                                              const cases = [
                                                ...(selectedNode.data.config
                                                  ?.cases || []),
                                              ];
                                              cases[idx] = {
                                                ...cases[idx],
                                                expression: buildSimpleCel(
                                                  parsed.variable,
                                                  op,
                                                  parsed.value,
                                                ),
                                              };
                                              handleUpdateNodeData({
                                                config: {
                                                  ...(selectedNode.data
                                                    .config || {}),
                                                  cases,
                                                },
                                              });
                                            }}
                                          >
                                            <SelectTrigger className="w-24 shrink-0">
                                              <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent>
                                              <SelectItem value="==">
                                                =
                                              </SelectItem>
                                              <SelectItem value="!=">
                                                !=
                                              </SelectItem>
                                              <SelectItem value=">">
                                                &gt;
                                              </SelectItem>
                                              <SelectItem value="<">
                                                &lt;
                                              </SelectItem>
                                              <SelectItem value=">=">
                                                &gt;=
                                              </SelectItem>
                                              <SelectItem value="<=">
                                                &lt;=
                                              </SelectItem>
                                              <SelectItem value="contains">
                                                contains
                                              </SelectItem>
                                              <SelectItem value="startsWith">
                                                starts
                                              </SelectItem>
                                            </SelectContent>
                                          </Select>
                                          <input
                                            type="text"
                                            value={
                                              parseSimpleCel(c.expression).value
                                            }
                                            onChange={(e) => {
                                              const parsed = parseSimpleCel(
                                                c.expression,
                                              );
                                              const cases = [
                                                ...(selectedNode.data.config
                                                  ?.cases || []),
                                              ];
                                              cases[idx] = {
                                                ...cases[idx],
                                                expression: buildSimpleCel(
                                                  parsed.variable,
                                                  parsed.operator,
                                                  e.target.value,
                                                ),
                                              };
                                              handleUpdateNodeData({
                                                config: {
                                                  ...(selectedNode.data
                                                    .config || {}),
                                                  cases,
                                                },
                                              });
                                            }}
                                            className="border-light-silver focus:ring-purple-30 w-full rounded-xl border bg-white px-3 py-2 text-sm outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#383838] dark:text-white"
                                            placeholder="Value"
                                          />
                                        </div>
                                      ) : (
                                        <>
                                          <textarea
                                            value={c.expression}
                                            onChange={(e) => {
                                              const cases = [
                                                ...(selectedNode.data.config
                                                  ?.cases || []),
                                              ];
                                              cases[idx] = {
                                                ...cases[idx],
                                                expression: e.target.value,
                                              };
                                              handleUpdateNodeData({
                                                config: {
                                                  ...(selectedNode.data
                                                    .config || {}),
                                                  cases,
                                                },
                                              });
                                            }}
                                            className="border-light-silver focus:ring-purple-30 w-full rounded-xl border bg-white px-3 py-2 text-sm transition-all outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#383838] dark:text-white"
                                            rows={2}
                                            placeholder="Enter condition, e.g. input == 5"
                                          />
                                          <p className="mt-1 text-[10px] text-gray-400">
                                            Use Common Expression Language to
                                            create a custom expression.{' '}
                                            <a
                                              href="https://cel.dev/"
                                              target="_blank"
                                              rel="noreferrer"
                                              className="text-violets-are-blue underline"
                                            >
                                              Learn more
                                            </a>
                                          </p>
                                        </>
                                      )}
                                    </div>
                                  ),
                                )}

                                <button
                                  onClick={() => {
                                    const cases = normalizeConditionCases([
                                      ...(selectedNode.data.config?.cases ||
                                        []),
                                    ]);
                                    const nextHandle =
                                      getNextConditionHandle(cases);
                                    cases.push({
                                      name: '',
                                      expression: '',
                                      sourceHandle: nextHandle,
                                    });
                                    handleUpdateNodeData({
                                      config: {
                                        ...(selectedNode.data.config || {}),
                                        cases,
                                      },
                                    });
                                  }}
                                  className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-[#383838]"
                                >
                                  <Plus size={14} />
                                  Add
                                </button>
                              </>
                            )}
                          </>
                        )}
                    </div>

                    <button
                      onClick={handleDeleteNode}
                      disabled={selectedNode?.type === 'start'}
                      className="flex w-full items-center justify-center gap-2 rounded-full border border-red-200 px-4 py-2 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-900/30 dark:text-red-400 dark:hover:bg-red-900/10"
                    >
                      <Trash2 size={16} />
                      {selectedNode?.type === 'start'
                        ? 'Cannot Delete Start Node'
                        : 'Delete Node'}
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        <Sheet open={showPreview} onOpenChange={setShowPreview}>
          <SheetContent
            side="right"
            showCloseButton={false}
            className="dark:bg-raisin-black w-full max-w-none p-0 sm:max-w-[600px] md:max-w-[700px] lg:max-w-[800px] dark:border-[#3A3A3A]"
          >
            <WorkflowPreview
              workflowData={{
                name: workflowName,
                description: workflowDescription,
                nodes: nodes
                  .filter((n) => n.type !== 'note')
                  .map((n) => ({
                    id: n.id,
                    type: n.type as 'start' | 'end' | 'agent' | 'state',
                    title: n.data.title || n.data.label || n.type,
                    position: n.position,
                    data: n.type === 'agent' ? n.data.config : n.data,
                  })),
                edges: edges.map((e) => ({
                  id: e.id,
                  source: e.source,
                  target: e.target,
                  sourceHandle: e.sourceHandle || undefined,
                  targetHandle: e.targetHandle || undefined,
                })),
              }}
            />
          </SheetContent>
        </Sheet>
        <ConfirmationModal
          message={`Are you sure you want to delete "${workflowName || 'this workflow agent'}"?`}
          modalState={deleteConfirmation}
          setModalState={setDeleteConfirmation}
          submitLabel="Delete"
          handleSubmit={handleDeleteAgent}
          cancelLabel="Cancel"
          variant="danger"
        />
        {canManageAgent && (
          <AgentDetailsModal
            agent={agentForDetails}
            mode="edit"
            modalState={agentDetails}
            setModalState={setAgentDetails}
          />
        )}
      </div>
    </>
  );
}

export default function WorkflowBuilder() {
  return (
    <ReactFlowProvider>
      <WorkflowBuilderInner />
    </ReactFlowProvider>
  );
}
