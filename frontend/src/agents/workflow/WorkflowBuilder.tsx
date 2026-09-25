import 'reactflow/dist/style.css';

import {
  AlertCircle,
  Bot,
  Code2,
  Database,
  Flag,
  GitBranch,
  Link,
  Pencil,
  Play,
  Plus,
  Redo2,
  StickyNote,
  Trash2,
  Undo2,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
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
  Panel,
  ReactFlowProvider,
  useReactFlow,
} from 'reactflow';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { MultiSelect } from '@/components/ui/multi-select';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { SettingRow } from '@/components/ui/setting-row';
import { Sheet, SheetContent } from '@/components/ui/sheet';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

import modelService from '../../api/services/modelService';
import userService from '../../api/services/userService';
import { FileUpload } from '../../components/FileUpload';
import AgentDetailsModal from '../../modals/AgentDetailsModal';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { ActiveState } from '../../models/misc';
import {
  selectSourceDocs,
  selectToken,
} from '../../preferences/preferenceSlice';
import { getToolDisplayName } from '../../utils/toolUtils';
import { agentEditPath, agentsListPath } from '../paths';
import AgentPageHeader from '../AgentPageHeader';
import { Agent } from '../types';
import { ConditionCase, WorkflowNode } from '../types/workflow';
import {
  createDefaultCodeConfig,
  normalizeCodeConfig,
  parseCodeJsonSchemaDraft,
  serializeCodeConfig,
  validateCodeJsonSchema,
} from './codeNodeConfig';
import MobileBlocker from './components/MobileBlocker';
import { buildSimpleCel, parseSimpleCel } from './simpleCel';
import NodeDocumentsControl from './components/NodeDocumentsControl';
import PromptTextArea, {
  extractUpstreamVariables,
} from './components/PromptTextArea';
import {
  FILE_PASSING_OPTIONS,
  FilePassing,
  normalizeFilePassing,
  toDocumentVariableOptions,
} from './documentConfig';
import { useUndoRedo, WorkflowSnapshot } from './hooks/useUndoRedo';
import {
  AgentNode,
  CodeNode,
  ConditionNode,
  EndNode,
  NoteNode,
  SetStateNode,
  StartNode,
} from './nodes';
import WorkflowPreview from './WorkflowPreview';

import type { Model } from '../../models/types';
import { useOutsideAlerter } from '@/hooks';

const PRIMARY_ACTION_SPINNER_DELAY_MS = 180;

interface AgentNodeConfig {
  agent_type: 'classic' | 'research';
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
  input_documents?: string[];
  file_passing?: FilePassing;
}

interface UserTool {
  id: string;
  name: string;
  displayName: string;
  customName?: string;
  // Workflow-only builtins (e.g. read_document) are kept here; the classic
  // agent picker filters them out.
  workflow_only?: boolean;
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

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
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
        'start' | 'end' | 'agent' | 'note' | 'state' | 'condition' | 'code',
      title: node.data.title || node.data.label || node.type,
      position: node.position,
      data:
        node.type === 'code'
          ? serializeCodeConfig(node.data.config)
          : node.type === 'agent' ||
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

const NODE_TYPES: NodeTypes = {
  start: StartNode,
  agent: AgentNode,
  end: EndNode,
  note: NoteNode,
  state: SetStateNode,
  condition: ConditionNode,
  code: CodeNode,
};

function WorkflowBuilderInner() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const sourceDocs = useSelector(selectSourceDocs);
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
  const sourceOptions = useMemo(
    () =>
      (sourceDocs ?? [])
        .filter((doc) => Boolean(doc.id))
        .map((doc) => ({ value: doc.id as string, label: doc.name })),
    [sourceDocs],
  );
  const [agentJsonSchemaDrafts, setAgentJsonSchemaDrafts] = useState<
    Record<string, string>
  >({});
  const [agentJsonSchemaErrors, setAgentJsonSchemaErrors] = useState<
    Record<string, string | null>
  >({});

  const nodeTypes = NODE_TYPES;

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

  const handleHistoryRestore = useCallback(
    (snapshot: WorkflowSnapshot) => {
      setAgentJsonSchemaDrafts({});
      setAgentJsonSchemaErrors({});
      if (!selectedNode) return;
      const restoredNode = snapshot.nodes.find((n) => n.id === selectedNode.id);
      if (restoredNode) {
        setSelectedNode(restoredNode);
      } else {
        setSelectedNode(null);
        setShowNodeConfig(false);
      }
    },
    [selectedNode],
  );

  const { takeSnapshot, undo, redo, clearHistory, canUndo, canRedo } =
    useUndoRedo({
      nodes,
      edges,
      setNodes,
      setEdges,
      onRestore: handleHistoryRestore,
    });

  const snapshotBeforeCanvasChange = useCallback(
    () => takeSnapshot(),
    [takeSnapshot],
  );

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

  const onConnect = useCallback(
    (params: Connection) => {
      const exists = edges.some(
        (e) =>
          e.source === params.source &&
          e.sourceHandle === params.sourceHandle &&
          e.target === params.target &&
          e.targetHandle === params.targetHandle,
      );
      if (exists) return;

      takeSnapshot();

      const targetNode = nodes.find((n) => n.id === params.target);
      const isEndNode = targetNode?.type === 'end';

      setEdges((eds) => {
        const filtered = eds.filter(
          (e) =>
            !(
              e.source === params.source &&
              e.sourceHandle === (params.sourceHandle ?? null)
            ) &&
            // End nodes accept multiple incoming edges
            (isEndNode ||
              !(
                e.target === params.target &&
                e.targetHandle === (params.targetHandle ?? null)
              )),
        );
        return addEdge(params, filtered);
      });
    },
    [nodes, edges, takeSnapshot],
  );

  const onEdgeClick = useCallback(
    (_event: React.MouseEvent, edge: Edge) => {
      takeSnapshot();
      setEdges((eds) => eds.filter((e) => e.id !== edge.id));
    },
    [takeSnapshot],
  );

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

      takeSnapshot();

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
      } else if (type === 'code') {
        baseNode.data.title = 'Code';
        baseNode.data.label = 'Code';
        baseNode.data.config = createDefaultCodeConfig();
      } else if (type === 'note') {
        baseNode.data.title = 'Note';
        baseNode.data.label = 'Note';
      }

      setNodes((nds) => nds.concat(baseNode));
    },
    [reactFlowInstance, availableModels, defaultAgentModelId, takeSnapshot],
  );

  const handleNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      setSelectedNode(node);
      setShowNodeConfig(true);
    },
    [],
  );

  const deleteNodesAndEdges = useCallback(
    (nodesToDelete: Node[], edgesToDelete: Edge[]) => {
      const removableIds = new Set(
        nodesToDelete.filter((n) => n.type !== 'start').map((n) => n.id),
      );
      const edgeIdsToDelete = new Set(edgesToDelete.map((e) => e.id));
      if (removableIds.size === 0 && edgeIdsToDelete.size === 0) return;

      takeSnapshot();
      setNodes((nds) => nds.filter((n) => !removableIds.has(n.id)));
      setEdges((eds) =>
        eds.filter(
          (e) =>
            !edgeIdsToDelete.has(e.id) &&
            !removableIds.has(e.source) &&
            !removableIds.has(e.target),
        ),
      );
      const dropRemoved = <T,>(prev: Record<string, T>): Record<string, T> => {
        const next = { ...prev };
        let changed = false;
        removableIds.forEach((id) => {
          if (id in next) {
            delete next[id];
            changed = true;
          }
        });
        return changed ? next : prev;
      };
      setAgentJsonSchemaDrafts(dropRemoved);
      setAgentJsonSchemaErrors(dropRemoved);
      if (selectedNode && removableIds.has(selectedNode.id)) {
        setSelectedNode(null);
        setShowNodeConfig(false);
      }
    },
    [selectedNode, takeSnapshot],
  );

  const handleDeleteNode = useCallback(() => {
    if (!selectedNode) return;
    deleteNodesAndEdges([selectedNode], []);
  }, [selectedNode, deleteNodesAndEdges]);

  const handleUpdateNodeData = useCallback(
    (data: Record<string, unknown>, options?: { snapshot?: boolean }) => {
      if (!selectedNode) return;
      if (options?.snapshot !== false) {
        // Group per node so a burst of keystrokes becomes one undo step
        takeSnapshot(`node-data:${selectedNode.id}`);
      }
      setNodes((nds) =>
        nds.map((n) =>
          n.id === selectedNode.id ? { ...n, data: { ...n.data, ...data } } : n,
        ),
      );
      setSelectedNode((prev) =>
        prev ? { ...prev, data: { ...prev.data, ...data } } : null,
      );
    },
    [selectedNode, takeSnapshot],
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

  const handleCodeJsonSchemaChange = useCallback(
    (text: string) => {
      if (!selectedNode || selectedNode.type !== 'code') return;

      const nodeId = selectedNode.id;
      setAgentJsonSchemaDrafts((prev) => ({ ...prev, [nodeId]: text }));

      const { schema, error } = parseCodeJsonSchemaDraft(text);
      setAgentJsonSchemaErrors((prev) => ({ ...prev, [nodeId]: error }));
      if (!error) {
        handleUpdateNodeData({
          config: {
            ...(selectedNode.data.config || {}),
            json_schema: schema,
          },
        });
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
    navigate(agentsListPath(folderId));
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
    // Shared guard for the canvas shortcuts (undo/redo, Delete/Backspace to
    // remove the selection, Escape to close the config panel): ignore the
    // keystroke while typing in a field, while the Preview Sheet is open (its
    // own inputs own the keys — a stray Delete there must not delete the node
    // behind it), or once another handler has already consumed the event. Kept
    // in one place so the branches can't drift apart.
    const shouldIgnoreShortcut = (e: KeyboardEvent): boolean =>
      e.defaultPrevented || showPreview || isEditableTarget(e.target);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (shouldIgnoreShortcut(e)) return;

      if (e.ctrlKey || e.metaKey) {
        const key = e.key.toLowerCase();
        if (key === 'z') {
          e.preventDefault();
          if (e.shiftKey) redo();
          else undo();
          return;
        }
        if (key === 'y') {
          e.preventDefault();
          redo();
          return;
        }
      }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        deleteNodesAndEdges(
          nodes.filter((n) => n.selected || n.id === selectedNode?.id),
          edges.filter((edge) => edge.selected),
        );
      }
      if (e.key === 'Escape') {
        setShowNodeConfig(false);
        setSelectedNode(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    nodes,
    edges,
    selectedNode,
    deleteNodesAndEdges,
    undo,
    redo,
    showPreview,
  ]);

  const handlePaneClick = useCallback(() => {
    setShowNodeConfig(false);
    setSelectedNode(null);
    setShowWorkflowSettings(false);
  }, []);

  const handleCloseWorkflowSettings = useCallback(() => {
    setShowWorkflowSettings(false);
  }, []);

  useOutsideAlerter(
    workflowSettingsRef,
    handleCloseWorkflowSettings,
    [],
    false,
  );

  useEffect(() => {
    const loadModelsAndTools = async () => {
      try {
        const modelsResponse = await modelService.getModels(token);
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

        const toolsResponse = await userService.getUserTools(token);
        if (toolsResponse.ok) {
          const toolsData = await toolsResponse.json();
          setAvailableTools(toolsData.tools);
        }
      } catch (error) {
        console.error('Failed to load models or tools:', error);
      }
    };
    loadModelsAndTools();
  }, [token]);

  useEffect(() => {
    if (!selectedNode || selectedNode.type !== 'agent') return;
    if (!defaultAgentModelId) return;
    if (selectedNode.data.config?.model_id) return;

    handleUpdateNodeData(
      {
        config: {
          ...(selectedNode.data.config || {}),
          model_id: defaultAgentModelId,
          llm_name:
            availableModels.find((model) => model.id === defaultAgentModelId)
              ?.provider || '',
        },
      },
      { snapshot: false },
    );
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
    if (!selectedNode || selectedNode.type !== 'code') return;
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
      return { ...prev, [nodeId]: validateCodeJsonSchema(rawSchema) };
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
        const {
          workflow,
          nodes: apiNodes,
          edges: apiEdges,
        } = responseData.data;
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
          } else if (n.type === 'code') {
            nodeData.config = normalizeCodeConfig(
              n.data as Record<string, unknown> | undefined,
            );
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
        clearHistory();
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
  }, [workflowId, reactFlowInstance, token, clearHistory]);

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

    const codeNodes = nodes.filter((n) => n.type === 'code');
    codeNodes.forEach((node) => {
      const codeTitle = node.data?.title || node.id;
      const config = node.data?.config;
      if (!(config?.code || '').trim()) {
        errors.push(`Code node "${codeTitle}" must have code to run`);
      }

      const schemaValidationError = validateCodeJsonSchema(config?.json_schema);
      const draftSchemaError = agentJsonSchemaErrors[node.id];
      const effectiveSchemaError =
        draftSchemaError !== undefined
          ? draftSchemaError
          : schemaValidationError;
      if (effectiveSchemaError) {
        errors.push(
          `Code node "${codeTitle}" JSON schema ${effectiveSchemaError}`,
        );
      }
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
            agentFormData.append(
              'allow_system_prompt_override',
              currentAgent.allow_system_prompt_override ? 'True' : 'False',
            );
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
        savedWorkflowId = responseData?.data?.id ?? responseData?.id;
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
        agentFormData.append(
          'allow_system_prompt_override',
          currentAgent.allow_system_prompt_override ? 'True' : 'False',
        );
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
    void persistWorkflow(false);
  }, [isPrimaryActionDisabled, persistWorkflow]);

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

  const selectedAgentDocumentOptions = useMemo(() => {
    if (!selectedNode || selectedNode.type !== 'agent') return [];
    return toDocumentVariableOptions(
      extractUpstreamVariables(nodes, edges, selectedNode.id),
    );
  }, [selectedNode, nodes, edges]);

  const selectedCodeDocumentOptions = useMemo(() => {
    if (!selectedNode || selectedNode.type !== 'code') return [];
    return toDocumentVariableOptions(
      extractUpstreamVariables(nodes, edges, selectedNode.id),
    );
  }, [selectedNode, nodes, edges]);

  const selectedCodeJsonSchemaText = useMemo(() => {
    if (!selectedNode || selectedNode.type !== 'code') return '';

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

  const selectedCodeJsonSchemaError = useMemo(() => {
    if (!selectedNode || selectedNode.type !== 'code') return null;

    const cachedError = agentJsonSchemaErrors[selectedNode.id];
    if (cachedError !== undefined) return cachedError;

    return validateCodeJsonSchema(selectedNode.data.config?.json_schema);
  }, [selectedNode, agentJsonSchemaErrors]);

  return (
    <>
      <MobileBlocker />
      <div className="bg-background fixed inset-0 z-50 hidden h-screen w-full flex-col md:flex">
        <div className="border-border bg-card dark:bg-background flex items-center justify-between border-b px-6 py-4">
          <div className="flex items-center gap-4">
            {canManageAgent ? (
              <AgentPageHeader
                agentId={effectiveAgentId}
                agentName={workflowName}
                agentEditPath={agentEditPath(effectiveAgentId, true)}
                currentPage="overview"
                inline
              />
            ) : (
              <Button
                type="button"
                variant="outline"
                shape="pill"
                onClick={navigateBackToAgents}
              >
                {t('agents.backToAll')}
              </Button>
            )}
            {!canManageAgent && (
              <div className="min-w-0">
                <div
                  className="text-foreground max-w-xs truncate text-xl font-bold"
                  title={workflowName || 'New Workflow'}
                >
                  {workflowName || 'New Workflow'}
                </div>
                {workflowDescription && (
                  <div
                    className="text-muted-foreground max-w-xs truncate text-xs"
                    title={workflowDescription}
                  >
                    {workflowDescription}
                  </div>
                )}
              </div>
            )}
            <div className="relative flex items-center">
              <Button
                type="button"
                variant="ghost-muted"
                size="icon-xs"
                onClick={() => setShowWorkflowSettings(!showWorkflowSettings)}
                aria-label="Edit workflow details"
                title={
                  workflowDescription
                    ? `${workflowName || 'New Workflow'} — ${workflowDescription}`
                    : 'Edit workflow details'
                }
              >
                <Pencil size={14} />
              </Button>
              {showWorkflowSettings && (
                <div
                  ref={workflowSettingsRef}
                  className="border-border bg-card absolute top-full left-0 z-50 mt-2 w-80 rounded-xl border p-4 shadow-lg"
                >
                  <FormField label="Workflow Name" className="mb-3">
                    <Input
                      type="text"
                      value={workflowName}
                      onChange={(e) => setWorkflowName(e.target.value)}
                      placeholder="Enter workflow name"
                    />
                  </FormField>
                  <FormField label="Description" className="mb-3">
                    <Textarea
                      value={workflowDescription}
                      onChange={(e) => setWorkflowDescription(e.target.value)}
                      rows={3}
                      placeholder="Describe what this workflow does"
                    />
                  </FormField>
                  <FormField
                    label="Agent Image"
                    hint="Image updates are included the next time you save."
                    className="mb-3"
                  >
                    {currentAgentImage && !imageFile && (
                      <div className="flex items-center gap-2">
                        <img
                          src={currentAgentImage}
                          alt="Agent image"
                          className="h-10 w-10 rounded-full object-cover"
                        />
                        <span className="text-muted-foreground text-xs">
                          Current image
                        </span>
                      </div>
                    )}
                    <FileUpload
                      showPreview
                      maxFiles={1}
                      previewSize={56}
                      size="compact"
                      onUpload={handleUpload}
                      onRemove={() => setImageFile(null)}
                      uploadText={[
                        {
                          text: 'Click to upload',
                          highlight: true,
                        },
                        {
                          text: ' or drag and drop',
                        },
                      ]}
                    />
                  </FormField>
                  <div className="mb-3">
                    <SettingRow
                      label={t('agents.form.advanced.systemPromptOverride')}
                      description={t(
                        'agents.form.advanced.systemPromptOverrideDescription',
                      )}
                      htmlFor="workflow-system-prompt-override"
                    >
                      <Switch
                        id="workflow-system-prompt-override"
                        checked={Boolean(
                          currentAgent.allow_system_prompt_override,
                        )}
                        onCheckedChange={() =>
                          setCurrentAgent((prev) => ({
                            ...prev,
                            allow_system_prompt_override:
                              !prev.allow_system_prompt_override,
                          }))
                        }
                      />
                    </SettingRow>
                  </div>
                  <Button
                    type="button"
                    onClick={handleWorkflowSettingsDone}
                    disabled={isPublishing}
                    className="w-full"
                  >
                    Done
                  </Button>
                </div>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {canManageAgent && (
              <Button
                type="button"
                variant="outline"
                shape="pill"
                onClick={() => setAgentDetails('ACTIVE')}
              >
                <Link size={16} />
                Access Details
              </Button>
            )}
            {canManageAgent && (
              <Button
                type="button"
                variant="destructive-outline"
                shape="pill"
                onClick={() => setDeleteConfirmation('ACTIVE')}
                loading={isDeletingAgent}
              >
                <Trash2 size={16} />
                Delete
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              shape="pill"
              onClick={() => {
                const validationErrors = validateWorkflow();
                if (validationErrors.length > 0) {
                  setErrorContext('preview');
                  setPublishErrors(validationErrors);
                  return;
                }
                setShowPreview(true);
              }}
            >
              <Play size={16} />
              Preview
            </Button>
            <Button
              type="button"
              onClick={handlePrimaryAction}
              disabled={isPrimaryActionDisabled}
              loading={showPrimaryActionSpinner}
              size="lg"
              shape="pill"
            >
              {primaryActionLabel}
            </Button>
          </div>
        </div>

        {publishErrors.length > 0 && (
          <div className="pointer-events-none absolute top-20 right-0 left-0 z-50 flex justify-center px-4">
            <div className="bg-card pointer-events-auto w-full max-w-md rounded-lg shadow-lg">
              <Alert variant="destructive">
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
                <div className="absolute top-2.5 right-2.5">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    onClick={() => setPublishErrors([])}
                    aria-label={t('agents.close')}
                  >
                    <X size={16} aria-hidden />
                  </Button>
                </div>
              </Alert>
            </div>
          </div>
        )}

        <div className="flex flex-1 overflow-hidden">
          <div className="border-border bg-muted dark:bg-background flex w-64 flex-col gap-6 border-r p-4">
            <div>
              <h3 className="text-muted-foreground mb-3 text-xs font-semibold tracking-wider uppercase">
                Core Nodes
              </h3>
              <div className="flex flex-col gap-2">
                <div
                  className="group border-border bg-card flex cursor-move items-center gap-3 rounded-full border px-4 py-3 shadow-sm transition-all hover:shadow-md"
                  draggable
                  onDragStart={(e) => handleNodeDragStart(e, 'agent')}
                >
                  <div className="bg-primary/10 text-primary group-hover:bg-primary group-hover:text-primary-foreground flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors">
                    <Bot size={18} />
                  </div>
                  <span className="text-foreground text-sm font-medium">
                    AI Agent
                  </span>
                </div>
                <div
                  className="group border-border bg-card flex cursor-move items-center gap-3 rounded-full border px-4 py-3 shadow-sm transition-all hover:shadow-md"
                  draggable
                  onDragStart={(e) => handleNodeDragStart(e, 'end')}
                >
                  <div className="bg-success/10 text-success group-hover:bg-success group-hover:text-success-foreground flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors">
                    <Flag size={18} />
                  </div>
                  <span className="text-foreground text-sm font-medium">
                    End
                  </span>
                </div>
                <div
                  className="group border-border bg-card flex cursor-move items-center gap-3 rounded-full border px-4 py-3 shadow-sm transition-all hover:shadow-md"
                  draggable
                  onDragStart={(e) => handleNodeDragStart(e, 'note')}
                >
                  <div className="bg-warning/10 text-warning group-hover:bg-warning group-hover:text-warning-foreground flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors">
                    <StickyNote size={18} />
                  </div>
                  <span className="text-foreground text-sm font-medium">
                    Note
                  </span>
                </div>
              </div>
            </div>

            <div>
              <h3 className="text-muted-foreground mb-3 text-xs font-semibold tracking-wider uppercase">
                Logic & Data
              </h3>
              <div className="flex flex-col gap-2">
                <div
                  className="group border-border bg-card flex cursor-move items-center gap-3 rounded-full border px-4 py-3 shadow-sm transition-all hover:shadow-md"
                  draggable
                  onDragStart={(e) => handleNodeDragStart(e, 'state')}
                >
                  <div className="bg-info/10 text-info group-hover:bg-info group-hover:text-info-foreground flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors">
                    <Database size={18} />
                  </div>
                  <div className="flex flex-col">
                    <span className="text-foreground text-sm font-medium">
                      Set State
                    </span>
                    <span className="text-muted-foreground text-xs">
                      Modify workflow variables
                    </span>
                  </div>
                </div>
                <div
                  className="group border-border bg-card flex cursor-move items-center gap-3 rounded-full border px-4 py-3 shadow-sm transition-all hover:shadow-md"
                  draggable
                  onDragStart={(e) => handleNodeDragStart(e, 'condition')}
                >
                  <div className="bg-warning/10 text-warning group-hover:bg-warning group-hover:text-warning-foreground flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors">
                    <GitBranch size={18} />
                  </div>
                  <div className="flex flex-col">
                    <span className="text-foreground text-sm font-medium">
                      If / Else
                    </span>
                    <span className="text-muted-foreground text-xs">
                      Conditional branching
                    </span>
                  </div>
                </div>
                <div
                  className="group border-border bg-card flex cursor-move items-center gap-3 rounded-full border px-4 py-3 shadow-sm transition-all hover:shadow-md"
                  draggable
                  onDragStart={(e) => handleNodeDragStart(e, 'code')}
                >
                  <div className="bg-info/10 text-info group-hover:bg-info group-hover:text-info-foreground flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors">
                    <Code2 size={18} />
                  </div>
                  <div className="flex flex-col">
                    <span className="text-foreground text-sm font-medium">
                      Code
                    </span>
                    <span className="text-muted-foreground text-xs">
                      Run code in a sandbox
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div
            ref={reactFlowWrapper}
            className="bg-muted dark:bg-background/10 relative flex-1"
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
              onPaneClick={handlePaneClick}
              onNodeDragStart={snapshotBeforeCanvasChange}
              onSelectionDragStart={snapshotBeforeCanvasChange}
              nodeTypes={nodeTypes}
              nodeDragThreshold={1}
              deleteKeyCode={null}
              fitView
            >
              <Background />
              <Controls />
              <Panel position="top-left" className="flex gap-1.5">
                <Button
                  type="button"
                  variant="outline"
                  size="icon-sm"
                  onClick={undo}
                  disabled={!canUndo}
                  title="Undo (Ctrl+Z)"
                  aria-label="Undo"
                >
                  <Undo2 size={16} />
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="icon-sm"
                  onClick={redo}
                  disabled={!canRedo}
                  title="Redo (Ctrl+Shift+Z)"
                  aria-label="Redo"
                >
                  <Redo2 size={16} />
                </Button>
              </Panel>
            </ReactFlow>

            {showNodeConfig && selectedNode && (
              <>
                <div className="border-border bg-card shadow-modal absolute top-4 right-4 z-20 w-96 rounded-2xl border">
                  <div className="border-border flex items-center justify-between border-b p-4">
                    <h3 className="text-foreground font-semibold">
                      {selectedNode.type === 'start' && 'Start Node'}
                      {selectedNode.type === 'end' && 'End Node'}
                      {selectedNode.type === 'agent' && 'AI Agent'}
                      {selectedNode.type === 'note' && 'Note'}
                      {selectedNode.type === 'state' && 'Set global variables'}
                      {selectedNode.type === 'condition' && 'If / Else'}
                      {selectedNode.type === 'code' && 'Code'}
                    </h3>
                    <Button
                      type="button"
                      variant="ghost-muted"
                      size="icon-xs"
                      onClick={() => setShowNodeConfig(false)}
                    >
                      <X size={20} className="size-5" />
                    </Button>
                  </div>

                  <div className="max-h-[calc(100vh-200px)] overflow-y-auto p-4">
                    <div className="mb-4 flex flex-col gap-2">
                      <div className="bg-muted rounded-lg p-3">
                        <div className="text-muted-foreground mb-1 text-xs">
                          Node ID
                        </div>
                        <div className="text-foreground truncate font-mono text-xs">
                          {selectedNode.id}
                        </div>
                      </div>

                      {selectedNode.type !== 'start' &&
                        selectedNode.type !== 'end' && (
                          <>
                            <FormField label="Title">
                              <Input
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
                                placeholder="Enter node title"
                              />
                            </FormField>

                            {selectedNode.type === 'agent' && (
                              <>
                                <FormField label="Agent Type">
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
                                    <SelectTrigger size="lg" className="w-full">
                                      <SelectValue placeholder="Select agent type" />
                                    </SelectTrigger>
                                    <SelectContent>
                                      <SelectItem value="classic">
                                        Classic
                                      </SelectItem>
                                      <SelectItem value="research">
                                        Research
                                      </SelectItem>
                                    </SelectContent>
                                  </Select>
                                </FormField>
                                <FormField label="Model">
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
                                    <SelectTrigger size="lg" className="w-full">
                                      <SelectValue placeholder="Select a model" />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {(() => {
                                        const builtin = availableModels.filter(
                                          (m) => m.source !== 'user',
                                        );
                                        const user = availableModels.filter(
                                          (m) => m.source === 'user',
                                        );
                                        return (
                                          <>
                                            {builtin.length > 0 && (
                                              <SelectGroup>
                                                <SelectLabel>
                                                  {t(
                                                    'settings.customModels.modelsGroup.builtin',
                                                  )}
                                                </SelectLabel>
                                                {builtin.map((model) => (
                                                  <SelectItem
                                                    key={model.id}
                                                    value={model.id}
                                                  >
                                                    {model.display_name} ·{' '}
                                                    {model.provider}
                                                  </SelectItem>
                                                ))}
                                              </SelectGroup>
                                            )}
                                            {user.length > 0 && (
                                              <SelectGroup>
                                                <SelectLabel>
                                                  {t(
                                                    'settings.customModels.modelsGroup.user',
                                                  )}
                                                </SelectLabel>
                                                {user.map((model) => (
                                                  <SelectItem
                                                    key={model.id}
                                                    value={model.id}
                                                  >
                                                    {model.display_name} ·{' '}
                                                    {model.provider}
                                                  </SelectItem>
                                                ))}
                                              </SelectGroup>
                                            )}
                                          </>
                                        );
                                      })()}
                                    </SelectContent>
                                  </Select>
                                </FormField>
                                <FormField label="System Prompt">
                                  <Textarea
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
                                    rows={3}
                                    placeholder="System prompt for the agent"
                                  />
                                </FormField>
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
                                <FormField label="Output Variable">
                                  <Input
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
                                    placeholder="Variable name for output"
                                  />
                                </FormField>
                                <div className="flex items-center gap-2">
                                  <Checkbox
                                    id="stream_to_user"
                                    checked={
                                      selectedNode.data.config
                                        ?.stream_to_user ?? true
                                    }
                                    onCheckedChange={(checked) =>
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          stream_to_user: checked === true,
                                        },
                                      })
                                    }
                                  />
                                  <label
                                    htmlFor="stream_to_user"
                                    className="text-foreground text-sm"
                                  >
                                    Stream output to user
                                  </label>
                                </div>{' '}
                                <FormField label="Tools">
                                  <MultiSelect
                                    options={availableTools.map((tool) => ({
                                      value: tool.id,
                                      label: getToolDisplayName(tool),
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
                                </FormField>
                                <FormField label="Sources">
                                  <MultiSelect
                                    options={sourceOptions}
                                    selected={
                                      selectedNode.data.config?.sources || []
                                    }
                                    onChange={(newSources) =>
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          sources: newSources,
                                        },
                                      })
                                    }
                                    placeholder="Select sources..."
                                    searchPlaceholder="Search sources..."
                                    emptyText="No sources available"
                                  />
                                </FormField>
                                <NodeDocumentsControl
                                  key={selectedNode.id}
                                  value={
                                    selectedNode.data.config?.input_documents ??
                                    []
                                  }
                                  onChange={(nextInputDocuments) =>
                                    handleUpdateNodeData({
                                      config: {
                                        ...(selectedNode.data.config || {}),
                                        input_documents: nextInputDocuments,
                                      },
                                    })
                                  }
                                  options={selectedAgentDocumentOptions}
                                  label="Documents"
                                  helpText="Documents passed to this agent from uploads or upstream nodes."
                                />
                                <FormField
                                  label="File passing"
                                  hint="Auto: send native when the model supports it, otherwise extract text."
                                >
                                  <Select
                                    value={normalizeFilePassing(
                                      selectedNode.data.config?.file_passing,
                                    )}
                                    onValueChange={(value) =>
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          file_passing: value as FilePassing,
                                        },
                                      })
                                    }
                                  >
                                    <SelectTrigger size="lg" className="w-full">
                                      <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {FILE_PASSING_OPTIONS.map((option) => (
                                        <SelectItem
                                          key={option.value}
                                          value={option.value}
                                        >
                                          {option.label}
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </FormField>
                                <FormField
                                  label="Structured Output (JSON Schema)"
                                  hint={
                                    selectedAgentJsonSchemaText.trim() !== '' &&
                                    !selectedAgentJsonSchemaError
                                      ? 'Valid JSON schema'
                                      : undefined
                                  }
                                  error={
                                    selectedAgentJsonSchemaText.trim() !== '' &&
                                    selectedAgentJsonSchemaError
                                      ? `Invalid JSON schema: ${selectedAgentJsonSchemaError}`
                                      : undefined
                                  }
                                >
                                  {!selectedAgentModelSupportsStructuredOutput && (
                                    <p className="text-destructive text-xs">
                                      Selected model does not support structured
                                      output.
                                    </p>
                                  )}
                                  <Textarea
                                    value={selectedAgentJsonSchemaText}
                                    onChange={(e) =>
                                      handleAgentJsonSchemaChange(
                                        e.target.value,
                                      )
                                    }
                                    className="font-mono"
                                    rows={8}
                                    placeholder={`{
  "type": "object",
  "properties": {
    "summary": { "type": "string" }
  },
  "required": ["summary"]
}`}
                                  />
                                </FormField>
                              </>
                            )}

                            {selectedNode.type === 'note' && (
                              <FormField label="Note Content">
                                <Textarea
                                  value={selectedNode.data.content || ''}
                                  onChange={(e) =>
                                    handleUpdateNodeData({
                                      content: e.target.value,
                                    })
                                  }
                                  rows={4}
                                  placeholder="Enter note content"
                                />
                              </FormField>
                            )}

                            {selectedNode.type === 'state' && (
                              <>
                                <p className="text-muted-foreground text-xs">
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
                                      className="border-border rounded-xl border p-3"
                                    >
                                      <div className="mb-2 flex items-center justify-between">
                                        <span className="text-foreground text-sm font-medium">
                                          Assign value
                                        </span>
                                        {(
                                          selectedNode.data.config
                                            ?.operations || []
                                        ).length > 1 && (
                                          <Button
                                            type="button"
                                            variant="ghost-destructive"
                                            size="icon-xs"
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
                                          >
                                            <Trash2 size={14} />
                                          </Button>
                                        )}
                                      </div>
                                      <Textarea
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
                                        className="mb-1"
                                        rows={2}
                                        placeholder="query"
                                      />
                                      <p className="text-muted-foreground mb-3 text-xs">
                                        Use Common Expression Language to create
                                        a custom expression. Reference state by
                                        bare name (<code>query</code>), not{' '}
                                        <code>{'{{query}}'}</code>.{' '}
                                        <a
                                          href="https://cel.dev/"
                                          target="_blank"
                                          rel="noreferrer"
                                          className="text-primary underline"
                                        >
                                          Learn more
                                        </a>
                                      </p>
                                      <div>
                                        <span className="text-foreground mb-1 block text-sm font-medium">
                                          To variable
                                        </span>
                                        <Input
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
                                          placeholder="variable_name"
                                        />
                                      </div>
                                    </div>
                                  ),
                                )}
                                <Button
                                  type="button"
                                  variant="ghost-muted"
                                  size="sm"
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
                                  className="self-start"
                                >
                                  <Plus size={14} />
                                  Add
                                </Button>
                              </>
                            )}

                            {selectedNode.type === 'condition' && (
                              <>
                                <p className="text-muted-foreground text-xs">
                                  Create conditions to branch your workflow
                                </p>
                                <div className="border-border bg-card flex gap-1 rounded-xl border p-1">
                                  <Button
                                    type="button"
                                    variant={
                                      (selectedNode.data.config?.mode ||
                                        'simple') === 'simple'
                                        ? 'outline'
                                        : 'ghost-muted'
                                    }
                                    size="xs"
                                    onClick={() =>
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          mode: 'simple',
                                        },
                                      })
                                    }
                                    className="flex-1"
                                  >
                                    Simple
                                  </Button>
                                  <Button
                                    type="button"
                                    variant={
                                      selectedNode.data.config?.mode ===
                                      'advanced'
                                        ? 'outline'
                                        : 'ghost-muted'
                                    }
                                    size="xs"
                                    onClick={() =>
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          mode: 'advanced',
                                        },
                                      })
                                    }
                                    className="flex-1"
                                  >
                                    Advanced
                                  </Button>
                                </div>

                                {(selectedNode.data.config?.cases || []).map(
                                  (c: ConditionCase, idx: number) => (
                                    <div
                                      key={c.sourceHandle}
                                      className="border-border rounded-xl border p-3"
                                    >
                                      <div className="mb-2 flex items-center justify-between">
                                        <span className="text-warning text-sm font-semibold">
                                          {idx === 0 ? 'If' : 'Else if'}
                                        </span>
                                        {(selectedNode.data.config?.cases || [])
                                          .length > 1 && (
                                          <Button
                                            type="button"
                                            variant="ghost-destructive"
                                            size="icon-xs"
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
                                          >
                                            <Trash2 size={14} />
                                          </Button>
                                        )}
                                      </div>
                                      <Input
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
                                        className="mb-2"
                                        placeholder="Case name (optional)"
                                      />
                                      {(selectedNode.data.config?.mode ||
                                        'simple') === 'simple' ? (
                                        <div className="flex items-center gap-2">
                                          <Input
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
                                            <SelectTrigger
                                              size="lg"
                                              className="w-24 shrink-0"
                                            >
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
                                          <Input
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
                                            placeholder="Value"
                                          />
                                        </div>
                                      ) : (
                                        <>
                                          <Textarea
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
                                            rows={2}
                                            placeholder='Enter condition, e.g. query.contains("refund")'
                                          />
                                          <p className="text-muted-foreground mt-1 text-xs">
                                            Use Common Expression Language to
                                            create a custom expression.
                                            Reference state by bare name (
                                            <code>query</code>), not{' '}
                                            <code>{'{{query}}'}</code>.{' '}
                                            <a
                                              href="https://cel.dev/"
                                              target="_blank"
                                              rel="noreferrer"
                                              className="text-primary underline"
                                            >
                                              Learn more
                                            </a>
                                          </p>
                                        </>
                                      )}
                                    </div>
                                  ),
                                )}

                                <Button
                                  type="button"
                                  variant="ghost-muted"
                                  size="sm"
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
                                  className="self-start"
                                >
                                  <Plus size={14} />
                                  Add
                                </Button>
                              </>
                            )}

                            {selectedNode.type === 'code' && (
                              <>
                                <p className="text-muted-foreground text-xs">
                                  Run code in the workflow sandbox. Produced
                                  files are saved as artifacts.
                                </p>
                                <FormField label="Code">
                                  <Textarea
                                    value={selectedNode.data.config?.code ?? ''}
                                    onChange={(e) =>
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          code: e.target.value,
                                        },
                                      })
                                    }
                                    className="font-mono"
                                    rows={10}
                                    spellCheck={false}
                                    placeholder={'print("hello world")'}
                                  />
                                </FormField>
                                <NodeDocumentsControl
                                  key={selectedNode.id}
                                  value={selectedNode.data.config?.inputs ?? []}
                                  onChange={(nextInputs) =>
                                    handleUpdateNodeData({
                                      config: {
                                        ...(selectedNode.data.config || {}),
                                        inputs: nextInputs,
                                      },
                                    })
                                  }
                                  options={selectedCodeDocumentOptions}
                                  label="Input files"
                                  helpText="Artifacts/upstream refs staged as files in the sandbox (one becomes inputs/<name>)."
                                />
                                <FormField label="Output Variable">
                                  <Input
                                    type="text"
                                    value={
                                      selectedNode.data.config
                                        ?.output_variable || ''
                                    }
                                    onChange={(e) =>
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          output_variable: e.target.value,
                                        },
                                      })
                                    }
                                    placeholder="Variable name for output"
                                  />
                                </FormField>
                                <FormField label="Timeout (seconds)">
                                  <Input
                                    type="number"
                                    min={1}
                                    value={
                                      selectedNode.data.config?.timeout ?? ''
                                    }
                                    onChange={(e) => {
                                      const raw = e.target.value;
                                      const parsed =
                                        raw.trim() === ''
                                          ? undefined
                                          : Number.parseInt(raw, 10);
                                      handleUpdateNodeData({
                                        config: {
                                          ...(selectedNode.data.config || {}),
                                          timeout:
                                            parsed !== undefined &&
                                            Number.isFinite(parsed)
                                              ? parsed
                                              : undefined,
                                        },
                                      });
                                    }}
                                    placeholder="Optional"
                                  />
                                </FormField>
                                <FormField
                                  label="Structured Output (JSON Schema)"
                                  hint={
                                    selectedCodeJsonSchemaText.trim() !== '' &&
                                    !selectedCodeJsonSchemaError
                                      ? 'Valid JSON schema'
                                      : undefined
                                  }
                                  error={
                                    selectedCodeJsonSchemaText.trim() !== '' &&
                                    selectedCodeJsonSchemaError
                                      ? `Invalid JSON schema: ${selectedCodeJsonSchemaError}`
                                      : undefined
                                  }
                                >
                                  <Textarea
                                    value={selectedCodeJsonSchemaText}
                                    onChange={(e) =>
                                      handleCodeJsonSchemaChange(e.target.value)
                                    }
                                    className="font-mono"
                                    rows={6}
                                    placeholder={`{
  "type": "object",
  "properties": {
    "result": { "type": "string" }
  },
  "required": ["result"]
}`}
                                  />
                                </FormField>
                              </>
                            )}
                          </>
                        )}
                    </div>

                    <Button
                      type="button"
                      variant="destructive-outline"
                      onClick={handleDeleteNode}
                      disabled={selectedNode?.type === 'start'}
                      shape="pill"
                      className="w-full"
                    >
                      <Trash2 size={16} />
                      {selectedNode?.type === 'start'
                        ? 'Cannot Delete Start Node'
                        : 'Delete Node'}
                    </Button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        <Sheet open={showPreview} onOpenChange={setShowPreview}>
          <SheetContent
            side="right"
            title="Workflow preview"
            className="w-full max-w-none p-0 sm:max-w-[600px] md:max-w-[700px] lg:max-w-[800px]"
          >
            <WorkflowPreview
              workflowId={workflowId}
              workflowData={{
                name: workflowName,
                description: workflowDescription,
                nodes: nodes
                  .filter((n) => n.type !== 'note')
                  .map((n) => ({
                    id: n.id,
                    type: n.type as
                      'start' | 'end' | 'agent' | 'state' | 'code',
                    title: n.data.title || n.data.label || n.type,
                    position: n.position,
                    data:
                      n.type === 'code'
                        ? serializeCodeConfig(n.data.config)
                        : n.type === 'agent'
                          ? n.data.config
                          : n.data,
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
            onKeyRegenerated={(key) =>
              setCurrentAgent((prev) => ({ ...prev, key }))
            }
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
