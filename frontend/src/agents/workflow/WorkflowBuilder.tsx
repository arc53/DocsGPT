import 'reactflow/dist/style.css';

import {
  Bot,
  CircleAlert,
  CodeXml,
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
  type LucideIcon,
} from 'lucide-react';
import {
  type DragEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { type TFunction } from 'i18next';
import { Trans, useTranslation } from 'react-i18next';
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
import { Avatar } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { IconButton } from '@/components/ui/icon-button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { MultiSelect } from '@/components/ui/multi-select';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { SectionHeader } from '@/components/ui/section-header';
import { SettingRow } from '@/components/ui/setting-row';
import { Sheet, SheetContent } from '@/components/ui/sheet';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

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

const PRIMARY_ACTION_SPINNER_DELAY_MS = 180;

type PaletteTone = 'primary' | 'success' | 'warning' | 'info';

// Whole class strings per tone so Tailwind sees them.
const PALETTE_TONE_CLASSES: Record<PaletteTone, string> = {
  primary:
    'bg-primary/10 text-primary group-hover:bg-primary group-hover:text-primary-foreground',
  success:
    'bg-success/10 text-success group-hover:bg-success group-hover:text-success-foreground',
  warning:
    'bg-warning/10 text-warning group-hover:bg-warning group-hover:text-warning-foreground',
  info: 'bg-info/10 text-info group-hover:bg-info group-hover:text-info-foreground',
};

interface PaletteEntry {
  type: string;
  group: 'core' | 'logic';
  icon: LucideIcon;
  tone: PaletteTone;
  labelKey: string;
  hintKey?: string;
}

const PALETTE: PaletteEntry[] = [
  {
    type: 'agent',
    group: 'core',
    icon: Bot,
    tone: 'primary',
    labelKey: 'agents.workflow.builder.aiAgent',
  },
  {
    type: 'end',
    group: 'core',
    icon: Flag,
    tone: 'success',
    labelKey: 'agents.workflow.nodes.end',
  },
  {
    type: 'note',
    group: 'core',
    icon: StickyNote,
    tone: 'warning',
    labelKey: 'agents.workflow.nodes.note',
  },
  {
    type: 'state',
    group: 'logic',
    icon: Database,
    tone: 'info',
    labelKey: 'agents.workflow.nodes.setState',
    hintKey: 'agents.workflow.builder.setStateHint',
  },
  {
    type: 'condition',
    group: 'logic',
    icon: GitBranch,
    tone: 'warning',
    labelKey: 'agents.workflow.nodes.condition',
    hintKey: 'agents.workflow.builder.conditionHint',
  },
  {
    type: 'code',
    group: 'logic',
    icon: CodeXml,
    tone: 'info',
    labelKey: 'agents.workflow.nodes.code',
    hintKey: 'agents.workflow.builder.codeHint',
  },
];

/**
 * A draggable pill in the builder's node palette.
 *
 * Args:
 *   entry: The palette entry to render.
 *   onDragStart: Starts dragging a node of the entry's type onto the canvas.
 */
function NodePaletteItem({
  entry,
  onDragStart,
}: {
  entry: PaletteEntry;
  onDragStart: (e: DragEvent, nodeType: string) => void;
}) {
  const { t } = useTranslation();
  const Icon = entry.icon;
  const label = (
    <span className="text-foreground text-sm font-medium">
      {t(entry.labelKey)}
    </span>
  );
  return (
    <div
      className="group border-border bg-card hover:border-primary/40 flex cursor-move items-center gap-3 rounded-full border px-4 py-3 transition-colors"
      draggable
      onDragStart={(e) => onDragStart(e, entry.type)}
    >
      <div
        className={cn(
          'flex size-8 shrink-0 items-center justify-center rounded-full transition-colors',
          PALETTE_TONE_CLASSES[entry.tone],
        )}
      >
        <Icon className="size-4.5" />
      </div>
      {entry.hintKey ? (
        <div className="flex flex-col">
          {label}
          <span className="text-muted-foreground text-xs">
            {t(entry.hintKey)}
          </span>
        </div>
      ) : (
        label
      )}
    </div>
  );
}

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

// The schema validators return short English fragments (tests and the
// validation list key off them); these map each to its locale key.
// Names and handles are the user's own text: React escapes on render, so
// i18next must not escape them first.
const NO_ESCAPE = { interpolation: { escapeValue: false } } as const;

const SCHEMA_ERROR_KEYS: Record<string, string> = {
  'must be a valid JSON object': 'agents.workflow.schema.notObject',
  'must include either a "type" or "schema" field':
    'agents.workflow.schema.missingType',
  'must be valid JSON': 'agents.workflow.schema.invalidJson',
};

/**
 * Translate a JSON schema validation fragment.
 *
 * Args:
 *   t: The i18next translate function.
 *   fragment: The fragment a schema validator returned.
 *
 * Returns:
 *   The translated fragment, or the fragment itself when it is unknown.
 */
function schemaErrorText(t: TFunction, fragment: string): string {
  const key = SCHEMA_ERROR_KEYS[fragment];
  return key ? t(key) : fragment;
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
        throw new Error(
          errorData.message || t('agents.workflow.builder.deleteFailed'),
        );
      }
      navigateBackToAgents();
    } catch (error) {
      setPublishErrors([
        error instanceof Error
          ? error.message
          : t('agents.workflow.builder.deleteFailed'),
      ]);
      setErrorContext('publish');
    } finally {
      setIsDeletingAgent(false);
    }
  }, [currentAgentId, currentAgent.id, token, navigateBackToAgents, t]);

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
      errors.push(t('agents.workflow.validation.nameRequired'));
    }

    const startNodes = nodes.filter((n) => n.type === 'start');
    if (startNodes.length !== 1) {
      errors.push(t('agents.workflow.validation.oneStart'));
    }

    const endNodes = nodes.filter((n) => n.type === 'end');
    const endNodeIds = new Set(endNodes.map((n) => n.id));
    if (endNodes.length === 0) {
      errors.push(t('agents.workflow.validation.needEnd'));
    }

    const agentNodes = nodes.filter((n) => n.type === 'agent');
    if (agentNodes.length === 0) {
      errors.push(t('agents.workflow.validation.needAgent'));
    }

    agentNodes.forEach((node) => {
      const config = node.data?.config;
      if (!config?.llm_name && !config?.model_id) {
        errors.push(
          t('agents.workflow.validation.agentModel', {
            ...NO_ESCAPE,
            name: node.data?.title || node.id,
          }),
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
            t('agents.workflow.validation.agentStructuredOutput', {
              ...NO_ESCAPE,
              name: node.data?.title || node.id,
            }),
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
          t('agents.workflow.validation.agentSchema', {
            ...NO_ESCAPE,
            name: node.data?.title || node.id,
            error: schemaErrorText(t, effectiveSchemaError),
          }),
        );
      }
    });

    if (startNodes.length === 1) {
      const startId = startNodes[0].id;
      const hasOutgoing = edges.some((e) => e.source === startId);
      if (!hasOutgoing) {
        errors.push(t('agents.workflow.validation.startConnected'));
      }
    }

    endNodes.forEach((endNode) => {
      const hasIncoming = edges.some((e) => e.target === endNode.id);
      if (!hasIncoming) {
        errors.push(
          t('agents.workflow.validation.endIncoming', {
            ...NO_ESCAPE,
            name: endNode.id,
          }),
        );
      }
    });

    const nodeIds = new Set(nodes.map((n) => n.id));
    edges.forEach((edge) => {
      if (!nodeIds.has(edge.source)) {
        errors.push(t('agents.workflow.validation.edgeSource'));
      }
      if (!nodeIds.has(edge.target)) {
        errors.push(t('agents.workflow.validation.edgeTarget'));
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
          t('agents.workflow.validation.conditionNeedsCase', {
            ...NO_ESCAPE,
            name: conditionTitle,
          }),
        );
      }

      const caseHandles = new Set<string>();
      const duplicateCaseHandles = new Set<string>();
      cases.forEach((conditionCase: ConditionCase) => {
        const handle = (conditionCase.sourceHandle || '').trim();
        if (!handle) {
          errors.push(
            t('agents.workflow.validation.conditionCaseNoHandle', {
              ...NO_ESCAPE,
              name: conditionTitle,
            }),
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
          t('agents.workflow.validation.conditionDuplicateHandle', {
            ...NO_ESCAPE,
            name: conditionTitle,
            handle,
          }),
        );
      });

      const outgoing = edges.filter((e) => e.source === node.id);
      if (outgoing.length < 2) {
        errors.push(
          t('agents.workflow.validation.conditionTwoOutgoing', {
            ...NO_ESCAPE,
            name: conditionTitle,
          }),
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
            t('agents.workflow.validation.conditionEdgeNoHandle', {
              ...NO_ESCAPE,
              name: conditionTitle,
            }),
          );
          continue;
        }
        if (handle !== 'else' && !caseHandles.has(handle)) {
          errors.push(
            t('agents.workflow.validation.conditionUnknownBranch', {
              ...NO_ESCAPE,
              name: conditionTitle,
              handle,
            }),
          );
        }
        if (handleEdges.length > 1) {
          errors.push(
            t('agents.workflow.validation.conditionMultipleEdges', {
              ...NO_ESCAPE,
              name: conditionTitle,
              handle,
            }),
          );
        }
      }

      if (!outgoingByHandle.has('else')) {
        errors.push(
          t('agents.workflow.validation.conditionNeedsElse', {
            ...NO_ESCAPE,
            name: conditionTitle,
          }),
        );
      }

      cases.forEach((conditionCase: ConditionCase) => {
        const handle = (conditionCase.sourceHandle || '').trim();
        if (!handle) return;

        const hasExpression = Boolean((conditionCase.expression || '').trim());
        const hasOutgoing = Boolean(outgoingByHandle.get(handle)?.length);
        if (hasExpression && !hasOutgoing) {
          errors.push(
            t('agents.workflow.validation.caseNoConnection', {
              ...NO_ESCAPE,
              name: conditionTitle,
              handle,
            }),
          );
        }
        if (!hasExpression && hasOutgoing) {
          errors.push(
            t('agents.workflow.validation.caseNoExpression', {
              ...NO_ESCAPE,
              name: conditionTitle,
              handle,
            }),
          );
        }
        if (conditionMode === 'simple' && hasExpression) {
          const parsedCondition = parseSimpleCel(
            conditionCase.expression || '',
          );
          if (!parsedCondition.variable.trim()) {
            errors.push(
              t('agents.workflow.validation.caseNoVariable', {
                ...NO_ESCAPE,
                name: conditionTitle,
                handle,
              }),
            );
          }
        }
      });

      outgoing.forEach((edge) => {
        if (!canReachEnd(edge.target, edges, nodeIds, endNodeIds)) {
          const handle = edge.sourceHandle || 'branch';
          errors.push(
            t('agents.workflow.validation.branchReachEnd', {
              ...NO_ESCAPE,
              name: conditionTitle,
              handle,
            }),
          );
        }
      });
    });

    const codeNodes = nodes.filter((n) => n.type === 'code');
    codeNodes.forEach((node) => {
      const codeTitle = node.data?.title || node.id;
      const config = node.data?.config;
      if (!(config?.code || '').trim()) {
        errors.push(
          t('agents.workflow.validation.codeRequired', {
            ...NO_ESCAPE,
            name: codeTitle,
          }),
        );
      }

      const schemaValidationError = validateCodeJsonSchema(config?.json_schema);
      const draftSchemaError = agentJsonSchemaErrors[node.id];
      const effectiveSchemaError =
        draftSchemaError !== undefined
          ? draftSchemaError
          : schemaValidationError;
      if (effectiveSchemaError) {
        errors.push(
          t('agents.workflow.validation.codeSchema', {
            ...NO_ESCAPE,
            name: codeTitle,
            error: schemaErrorText(t, effectiveSchemaError),
          }),
        );
      }
    });

    return errors;
  }, [workflowName, nodes, edges, agentJsonSchemaErrors, availableModels, t]);

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
            throw new Error(
              errorData.message ||
                t('agents.workflow.builder.updateWorkflowFailed'),
            );
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
              throw new Error(t('agents.workflow.builder.updateAgentFailed'));
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
          throw new Error(
            errorData.message ||
              t('agents.workflow.builder.createWorkflowFailed'),
          );
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
          throw new Error(
            errorData.message || t('agents.workflow.builder.createAgentFailed'),
          );
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
          error instanceof Error
            ? error.message
            : t('agents.workflow.builder.saveFailed'),
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
      t,
    ],
  );

  const handleWorkflowSettingsDone = useCallback(() => {
    setShowWorkflowSettings(false);
    if (!canManageAgent || !hasSavableChanges || isPublishing) return;
    void persistWorkflow(false);
  }, [canManageAgent, hasSavableChanges, isPublishing, persistWorkflow]);

  const isPrimaryActionDisabled =
    isPublishing || (canManageAgent && !hasSavableChanges);
  const primaryActionLabel = canManageAgent
    ? t('agents.form.buttons.save')
    : t('agents.form.buttons.publish');

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
      description:
        workflowDescription ||
        t('agents.workflow.builder.defaultDescription', {
          ...NO_ESCAPE,
          name: workflowName,
        }),
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
      t,
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
      <div className="bg-background fixed inset-0 z-50 hidden h-screen w-full flex-col lg:flex">
        <div className="border-border bg-card flex items-center justify-between border-b px-6 py-4">
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
                  className="text-foreground max-w-xs truncate text-xl leading-tight font-semibold"
                  title={
                    workflowName || t('agents.workflow.builder.newWorkflow')
                  }
                >
                  {workflowName || t('agents.workflow.builder.newWorkflow')}
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
            <Popover
              open={showWorkflowSettings}
              onOpenChange={setShowWorkflowSettings}
            >
              <PopoverTrigger asChild>
                <IconButton
                  variant="ghost-muted"
                  size="icon-xs"
                  side="bottom"
                  label={t('agents.workflow.builder.editDetails')}
                  hint={
                    workflowDescription
                      ? `${workflowName || t('agents.workflow.builder.newWorkflow')} — ${workflowDescription}`
                      : undefined
                  }
                  icon={Pencil}
                />
              </PopoverTrigger>
              <PopoverContent align="start" className="w-80">
                <div className="flex flex-col gap-5">
                  <FormField label={t('agents.workflow.builder.workflowName')}>
                    <Input
                      type="text"
                      value={workflowName}
                      onChange={(e) => setWorkflowName(e.target.value)}
                      placeholder={t(
                        'agents.workflow.builder.workflowNamePlaceholder',
                      )}
                    />
                  </FormField>
                  <FormField label={t('agents.form.labels.description')}>
                    <Textarea
                      value={workflowDescription}
                      onChange={(e) => setWorkflowDescription(e.target.value)}
                      rows={3}
                      placeholder={t(
                        'agents.workflow.builder.workflowDescriptionPlaceholder',
                      )}
                    />
                  </FormField>
                  {currentAgentImage && !imageFile && (
                    <div className="flex items-center gap-2">
                      <Avatar
                        src={currentAgentImage}
                        alt={t('agents.workflow.builder.agentImageAlt')}
                        size="lg"
                        shape="circle"
                        imgClassName="size-full object-cover"
                      />
                      <span className="text-muted-foreground text-xs">
                        {t('agents.workflow.builder.currentImage')}
                      </span>
                    </div>
                  )}
                  <FormField
                    label={t('agents.workflow.builder.agentImage')}
                    hint={t('agents.workflow.builder.agentImageHint')}
                  >
                    <FileUpload
                      showPreview
                      maxFiles={1}
                      previewSize={56}
                      size="compact"
                      onUpload={handleUpload}
                      onRemove={() => setImageFile(null)}
                      uploadText={[
                        {
                          text: t('agents.form.upload.clickToUpload'),
                          highlight: true,
                        },
                        {
                          text: t('agents.form.upload.dragAndDrop'),
                        },
                      ]}
                    />
                  </FormField>
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
                  <Button
                    type="button"
                    onClick={handleWorkflowSettingsDone}
                    disabled={isPublishing}
                    className="w-full"
                  >
                    {t('agents.workflow.builder.done')}
                  </Button>
                </div>
              </PopoverContent>
            </Popover>
          </div>
          <div className="flex items-center gap-2">
            {canManageAgent && (
              <Button
                type="button"
                variant="outline"
                shape="pill"
                onClick={() => setAgentDetails('ACTIVE')}
              >
                <Link />
                {t('agents.form.buttons.accessDetails')}
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
                <Trash2 />
                {t('agents.form.buttons.delete')}
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
              <Play />
              {t('agents.form.sections.preview')}
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
          <div className="pointer-events-none absolute top-20 right-0 left-0 z-20 flex justify-center px-4">
            <div className="bg-card pointer-events-auto w-full max-w-md rounded-xl shadow-md">
              <Alert
                variant="destructive"
                // eslint-disable-next-line shadcn/no-restyle -- the close button sits in the top-right corner, so a long title wraps clear of it
                className="pr-10"
              >
                <CircleAlert className="size-4" />
                <AlertTitle>
                  {errorContext === 'preview'
                    ? t('agents.workflow.builder.unablePreview')
                    : canManageAgent
                      ? t('agents.workflow.builder.unableSave')
                      : t('agents.workflow.builder.unablePublish')}
                </AlertTitle>
                <AlertDescription>
                  <ul className="mt-2 list-inside list-disc space-y-1 wrap-break-word">
                    {publishErrors.map((error, index) => (
                      <li key={index}>{error}</li>
                    ))}
                  </ul>
                </AlertDescription>
                <div className="absolute top-2.5 right-2.5">
                  <IconButton
                    variant="ghost"
                    size="icon-xs"
                    onClick={() => setPublishErrors([])}
                    label={t('agents.close')}
                    icon={X}
                  />
                </div>
              </Alert>
            </div>
          </div>
        )}

        <div className="flex flex-1 overflow-hidden">
          <div className="border-border bg-muted flex w-64 flex-col gap-6 border-r p-4">
            <div className="flex flex-col gap-3">
              <SectionHeader
                as="h3"
                size="sm"
                title={t('agents.workflow.builder.coreNodes')}
              />
              <div className="flex flex-col gap-2">
                {PALETTE.filter((entry) => entry.group === 'core').map(
                  (entry) => (
                    <NodePaletteItem
                      key={entry.type}
                      entry={entry}
                      onDragStart={handleNodeDragStart}
                    />
                  ),
                )}
              </div>
            </div>

            <div className="flex flex-col gap-3">
              <SectionHeader
                as="h3"
                size="sm"
                title={t('agents.workflow.builder.logicNodes')}
              />
              <div className="flex flex-col gap-2">
                {PALETTE.filter((entry) => entry.group === 'logic').map(
                  (entry) => (
                    <NodePaletteItem
                      key={entry.type}
                      entry={entry}
                      onDragStart={handleNodeDragStart}
                    />
                  ),
                )}
              </div>
            </div>
          </div>

          <div ref={reactFlowWrapper} className="bg-muted relative flex-1">
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
                <IconButton
                  variant="outline"
                  size="icon-sm"
                  side="bottom"
                  onClick={undo}
                  disabled={!canUndo}
                  label={t('agents.workflow.undo')}
                  hint={t('agents.workflow.undoHint')}
                  icon={Undo2}
                />
                <IconButton
                  variant="outline"
                  size="icon-sm"
                  side="bottom"
                  onClick={redo}
                  disabled={!canRedo}
                  label={t('agents.workflow.redo')}
                  hint={t('agents.workflow.redoHint')}
                  icon={Redo2}
                />
              </Panel>
            </ReactFlow>

            {showNodeConfig && selectedNode && (
              <>
                <div className="border-border bg-card absolute top-4 right-4 z-20 w-96 rounded-2xl border shadow-md">
                  <div className="border-border flex items-center justify-between border-b p-4">
                    <h3 className="text-foreground text-sm font-semibold">
                      {selectedNode.type === 'start' &&
                        t('agents.workflow.builder.startNode')}
                      {selectedNode.type === 'end' &&
                        t('agents.workflow.builder.endNode')}
                      {selectedNode.type === 'agent' &&
                        t('agents.workflow.builder.aiAgent')}
                      {selectedNode.type === 'note' &&
                        t('agents.workflow.nodes.note')}
                      {selectedNode.type === 'state' &&
                        t('agents.workflow.builder.stateTitle')}
                      {selectedNode.type === 'condition' &&
                        t('agents.workflow.nodes.condition')}
                      {selectedNode.type === 'code' &&
                        t('agents.workflow.nodes.code')}
                    </h3>
                    <IconButton
                      variant="ghost-muted"
                      size="icon-xs"
                      side="bottom"
                      onClick={() => setShowNodeConfig(false)}
                      label={t('agents.close')}
                    >
                      <X className="size-5" aria-hidden />
                    </IconButton>
                  </div>

                  <div className="max-h-[calc(100vh-200px)] overflow-y-auto p-4">
                    <div className="mb-4 flex flex-col gap-5">
                      <div className="bg-muted rounded-lg p-3">
                        <div className="text-muted-foreground mb-1 text-xs">
                          {t('agents.workflow.builder.nodeId')}
                        </div>
                        <div className="text-foreground truncate font-mono text-xs">
                          {selectedNode.id}
                        </div>
                      </div>

                      {selectedNode.type !== 'start' &&
                        selectedNode.type !== 'end' && (
                          <>
                            <FormField
                              label={t('agents.workflow.builder.title')}
                            >
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
                                placeholder={t(
                                  'agents.workflow.builder.titlePlaceholder',
                                )}
                              />
                            </FormField>

                            {selectedNode.type === 'agent' && (
                              <>
                                <FormField
                                  label={t('agents.workflow.builder.agentType')}
                                >
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
                                    <SelectTrigger
                                      size="field"
                                      className="w-full"
                                    >
                                      <SelectValue
                                        placeholder={t(
                                          'agents.workflow.builder.agentTypePlaceholder',
                                        )}
                                      />
                                    </SelectTrigger>
                                    <SelectContent>
                                      <SelectItem value="classic">
                                        {t('agents.form.agentTypes.classic')}
                                      </SelectItem>
                                      <SelectItem value="research">
                                        {t('agents.form.agentTypes.research')}
                                      </SelectItem>
                                    </SelectContent>
                                  </Select>
                                </FormField>
                                <FormField
                                  label={t('agents.workflow.builder.model')}
                                >
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
                                    <SelectTrigger
                                      size="field"
                                      className="w-full"
                                    >
                                      <SelectValue
                                        placeholder={t(
                                          'agents.workflow.builder.modelPlaceholder',
                                        )}
                                      />
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
                                <FormField
                                  label={t(
                                    'agents.workflow.builder.systemPrompt',
                                  )}
                                >
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
                                    placeholder={t(
                                      'agents.workflow.builder.systemPromptPlaceholder',
                                    )}
                                  />
                                </FormField>
                                <PromptTextArea
                                  label={t(
                                    'agents.workflow.builder.promptTemplate',
                                  )}
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
                                  placeholder={t(
                                    'agents.workflow.builder.promptTemplatePlaceholder',
                                    {
                                      ...NO_ESCAPE,
                                      example: '{{ agent.variable }}',
                                    },
                                  )}
                                />
                                <FormField
                                  label={t(
                                    'agents.workflow.builder.outputVariable',
                                  )}
                                >
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
                                    placeholder={t(
                                      'agents.workflow.builder.outputVariablePlaceholder',
                                    )}
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
                                    {t('agents.workflow.builder.streamToUser')}
                                  </label>
                                </div>{' '}
                                <FormField
                                  label={t('agents.form.sections.tools')}
                                >
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
                                    placeholder={t(
                                      'agents.form.placeholders.selectTools',
                                    )}
                                    searchPlaceholder={t(
                                      'agents.form.toolsPopup.searchPlaceholder',
                                    )}
                                    emptyText={t(
                                      'agents.form.toolsPopup.noOptionsMessage',
                                    )}
                                  />
                                </FormField>
                                <FormField
                                  label={t('agents.workflow.builder.sources')}
                                >
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
                                    placeholder={t(
                                      'agents.form.placeholders.selectSources',
                                    )}
                                    searchPlaceholder={t(
                                      'agents.form.sourcePopup.searchPlaceholder',
                                    )}
                                    emptyText={t(
                                      'agents.form.sourcePopup.noOptionsMessage',
                                    )}
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
                                  label={t('agents.workflow.builder.documents')}
                                  helpText={t(
                                    'agents.workflow.builder.documentsHint',
                                  )}
                                />
                                <FormField
                                  label={t(
                                    'agents.workflow.builder.filePassing',
                                  )}
                                  hint={t(
                                    'agents.workflow.builder.filePassingHint',
                                  )}
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
                                    <SelectTrigger
                                      size="field"
                                      className="w-full"
                                    >
                                      <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {FILE_PASSING_OPTIONS.map((option) => (
                                        <SelectItem
                                          key={option.value}
                                          value={option.value}
                                        >
                                          {t(
                                            `agents.workflow.filePassing.${option.value}`,
                                            { defaultValue: option.label },
                                          )}
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </FormField>
                                <FormField
                                  label={t(
                                    'agents.workflow.builder.structuredOutput',
                                  )}
                                  hint={
                                    [
                                      !selectedAgentModelSupportsStructuredOutput
                                        ? t(
                                            'agents.workflow.builder.modelNoStructuredOutput',
                                          )
                                        : null,
                                      selectedAgentJsonSchemaText.trim() !==
                                        '' && !selectedAgentJsonSchemaError
                                        ? t(
                                            'agents.workflow.builder.validSchema',
                                          )
                                        : null,
                                    ]
                                      .filter(Boolean)
                                      .join(' ') || undefined
                                  }
                                  error={
                                    selectedAgentJsonSchemaText.trim() !== '' &&
                                    selectedAgentJsonSchemaError
                                      ? t(
                                          'agents.workflow.builder.invalidSchema',
                                          {
                                            ...NO_ESCAPE,
                                            error: schemaErrorText(
                                              t,
                                              selectedAgentJsonSchemaError,
                                            ),
                                          },
                                        )
                                      : undefined
                                  }
                                >
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
                              <FormField
                                label={t('agents.workflow.builder.noteContent')}
                              >
                                <Textarea
                                  value={selectedNode.data.content || ''}
                                  onChange={(e) =>
                                    handleUpdateNodeData({
                                      content: e.target.value,
                                    })
                                  }
                                  rows={4}
                                  placeholder={t(
                                    'agents.workflow.builder.noteContentPlaceholder',
                                  )}
                                />
                              </FormField>
                            )}

                            {selectedNode.type === 'state' && (
                              <>
                                <p className="text-muted-foreground text-xs">
                                  {t('agents.workflow.builder.stateIntro')}
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
                                    <Card
                                      key={idx}
                                      padding="sm"
                                      className="gap-2"
                                    >
                                      <div className="flex items-center justify-between">
                                        <span className="text-foreground text-sm font-medium">
                                          {t(
                                            'agents.workflow.builder.assignValue',
                                          )}
                                        </span>
                                        {(
                                          selectedNode.data.config
                                            ?.operations || []
                                        ).length > 1 && (
                                          <IconButton
                                            variant="ghost-destructive"
                                            size="icon-xs"
                                            label={t(
                                              'agents.workflow.removeAssignment',
                                              { index: idx + 1 },
                                            )}
                                            icon={Trash2}
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
                                          />
                                        )}
                                      </div>
                                      <div className="flex flex-col gap-5">
                                        <div className="flex flex-col gap-1">
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
                                                  ...(selectedNode.data
                                                    .config || {}),
                                                  operations: ops,
                                                },
                                              });
                                            }}
                                            rows={2}
                                            placeholder="query"
                                            aria-label={t(
                                              'agents.workflow.expressionRow',
                                              { index: idx + 1 },
                                            )}
                                          />
                                          <p className="text-muted-foreground text-xs">
                                            <Trans
                                              i18nKey="agents.workflow.builder.celHint"
                                              components={{ code: <code /> }}
                                              values={{ braced: '{{query}}' }}
                                            />{' '}
                                            <Button
                                              variant="link"
                                              size="inline"
                                              asChild
                                              // eslint-disable-next-line shadcn/no-restyle -- a link in a 12px hint keeps the sentence's size and weight
                                              className="text-xs font-normal"
                                            >
                                              <a
                                                href="https://cel.dev/"
                                                target="_blank"
                                                rel="noreferrer"
                                              >
                                                {t(
                                                  'agents.workflow.builder.learnMore',
                                                )}
                                              </a>
                                            </Button>
                                          </p>
                                        </div>
                                        <FormField
                                          label={t(
                                            'agents.workflow.builder.toVariable',
                                          )}
                                        >
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
                                                  ...(selectedNode.data
                                                    .config || {}),
                                                  operations: ops,
                                                },
                                              });
                                            }}
                                            placeholder="variable_name"
                                          />
                                        </FormField>
                                      </div>
                                    </Card>
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
                                  <Plus className="size-3.5" />
                                  {t('agents.form.buttons.add')}
                                </Button>
                              </>
                            )}

                            {selectedNode.type === 'condition' && (
                              <>
                                <p className="text-muted-foreground text-xs">
                                  {t('agents.workflow.builder.conditionIntro')}
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
                                    {t('agents.workflow.builder.modeSimple')}
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
                                    {t('agents.workflow.builder.modeAdvanced')}
                                  </Button>
                                </div>

                                {(selectedNode.data.config?.cases || []).map(
                                  (c: ConditionCase, idx: number) => (
                                    <Card
                                      key={c.sourceHandle}
                                      padding="sm"
                                      className="gap-2"
                                    >
                                      <div className="flex items-center justify-between">
                                        <span className="text-warning text-sm font-semibold">
                                          {idx === 0
                                            ? t('agents.workflow.nodes.if')
                                            : t('agents.workflow.nodes.elseIf')}
                                        </span>
                                        {(selectedNode.data.config?.cases || [])
                                          .length > 1 && (
                                          <IconButton
                                            variant="ghost-destructive"
                                            size="icon-xs"
                                            label={t(
                                              'agents.workflow.removeCondition',
                                              { index: idx + 1 },
                                            )}
                                            icon={Trash2}
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
                                          />
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
                                        placeholder={t(
                                          'agents.workflow.builder.caseNamePlaceholder',
                                        )}
                                        aria-label={t(
                                          'agents.workflow.conditionNameRow',
                                          { index: idx + 1 },
                                        )}
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
                                            placeholder={t(
                                              'agents.workflow.builder.variablePlaceholder',
                                            )}
                                            aria-label={t(
                                              'agents.workflow.conditionVariableRow',
                                              { index: idx + 1 },
                                            )}
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
                                              size="field"
                                              className="w-24 shrink-0"
                                              aria-label={t(
                                                'agents.workflow.conditionOperatorRow',
                                                { index: idx + 1 },
                                              )}
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
                                                {t(
                                                  'agents.workflow.builder.opContains',
                                                )}
                                              </SelectItem>
                                              <SelectItem value="startsWith">
                                                {t(
                                                  'agents.workflow.builder.opStartsWith',
                                                )}
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
                                            placeholder={t(
                                              'agents.workflow.builder.valuePlaceholder',
                                            )}
                                            aria-label={t(
                                              'agents.workflow.conditionValueRow',
                                              { index: idx + 1 },
                                            )}
                                          />
                                        </div>
                                      ) : (
                                        <FormField
                                          label={t(
                                            'agents.workflow.conditionRow',
                                            { index: idx + 1 },
                                          )}
                                          hint={
                                            <>
                                              <Trans
                                                i18nKey="agents.workflow.builder.celHint"
                                                components={{ code: <code /> }}
                                                values={{ braced: '{{query}}' }}
                                              />{' '}
                                              <Button
                                                variant="link"
                                                size="inline"
                                                asChild
                                                // eslint-disable-next-line shadcn/no-restyle -- a link in a 12px hint keeps the sentence's size and weight
                                                className="text-xs font-normal"
                                              >
                                                <a
                                                  href="https://cel.dev/"
                                                  target="_blank"
                                                  rel="noreferrer"
                                                >
                                                  {t(
                                                    'agents.workflow.builder.learnMore',
                                                  )}
                                                </a>
                                              </Button>
                                            </>
                                          }
                                        >
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
                                            placeholder={t(
                                              'agents.workflow.builder.conditionPlaceholder',
                                            )}
                                          />
                                        </FormField>
                                      )}
                                    </Card>
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
                                  <Plus className="size-3.5" />
                                  {t('agents.form.buttons.add')}
                                </Button>
                              </>
                            )}

                            {selectedNode.type === 'code' && (
                              <>
                                <p className="text-muted-foreground text-xs">
                                  {t('agents.workflow.builder.codeIntro')}
                                </p>
                                <FormField
                                  label={t('agents.workflow.nodes.code')}
                                >
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
                                  label={t(
                                    'agents.workflow.builder.inputFiles',
                                  )}
                                  helpText={t(
                                    'agents.workflow.builder.inputFilesHint',
                                  )}
                                />
                                <FormField
                                  label={t(
                                    'agents.workflow.builder.outputVariable',
                                  )}
                                >
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
                                    placeholder={t(
                                      'agents.workflow.builder.outputVariablePlaceholder',
                                    )}
                                  />
                                </FormField>
                                <FormField
                                  label={t('agents.workflow.builder.timeout')}
                                >
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
                                    placeholder={t(
                                      'agents.workflow.builder.optional',
                                    )}
                                  />
                                </FormField>
                                <FormField
                                  label={t(
                                    'agents.workflow.builder.structuredOutput',
                                  )}
                                  hint={
                                    selectedCodeJsonSchemaText.trim() !== '' &&
                                    !selectedCodeJsonSchemaError
                                      ? t('agents.workflow.builder.validSchema')
                                      : undefined
                                  }
                                  error={
                                    selectedCodeJsonSchemaText.trim() !== '' &&
                                    selectedCodeJsonSchemaError
                                      ? t(
                                          'agents.workflow.builder.invalidSchema',
                                          {
                                            ...NO_ESCAPE,
                                            error: schemaErrorText(
                                              t,
                                              selectedCodeJsonSchemaError,
                                            ),
                                          },
                                        )
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
                      <Trash2 />
                      {selectedNode?.type === 'start'
                        ? t('agents.workflow.builder.cannotDeleteStart')
                        : t('agents.workflow.builder.deleteNode')}
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
          message={
            workflowName
              ? t('agents.workflow.builder.deleteConfirm', {
                  ...NO_ESCAPE,
                  name: workflowName,
                })
              : t('agents.workflow.builder.deleteConfirmUnnamed')
          }
          modalState={deleteConfirmation}
          setModalState={setDeleteConfirmation}
          submitLabel={t('agents.form.buttons.delete')}
          handleSubmit={handleDeleteAgent}
          cancelLabel={t('agents.form.buttons.cancel')}
          variant="destructive"
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
