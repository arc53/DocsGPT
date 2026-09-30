import 'reactflow/dist/style.css';

import { CircleAlert, Link, Pencil, Play, Trash2, Users } from 'lucide-react';
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
  Edge,
  EdgeChange,
  Node,
  NodeChange,
  NodeTypes,
  ReactFlowProvider,
  useReactFlow,
  XYPosition,
} from 'reactflow';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

import modelService from '../../api/services/modelService';
import userService from '../../api/services/userService';
import AgentDetailsModal from '../../modals/AgentDetailsModal';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { ActiveState } from '../../models/misc';
import ShareToTeamModal from '../../teams/ShareToTeamModal';
import { can } from '../../utils/accessUtils';
import {
  selectSourceDocs,
  selectToken,
} from '../../preferences/preferenceSlice';
import { agentEditPath, agentsListPath } from '../paths';
import { ActionMenu } from '@/components/ui/dropdown-menu';
import AgentPageHeader from '../AgentPageHeader';
import AgentPreviewSheet from '../components/AgentPreviewSheet';
import {
  confirmTakeOver,
  readSponsorRefusal,
  saveWithSponsorConsent,
  sponsorNotAllowedMessage,
} from '../sponsorConsent';
import { useSponsorPrompt } from '../useSponsorPrompt';
import ResourceStatusNotice, {
  type NamedResource,
  unnamedResourceLabel,
} from '../components/ResourceStatusNotice';
import FloatingResourceNotice from './components/FloatingResourceNotice';
import { useSignInAgain } from '../../connectors/SignInAgainNotice';
import WorkflowDetailsSheet, {
  type WorkflowDetailsSave,
} from './components/WorkflowDetailsSheet';
import type { SponsorAudience } from '../sponsorConsent';
import { Agent, ResourceSponsor, ResourceState } from '../types';
import { ConditionCase, WorkflowNode } from '../types/workflow';
import {
  createDefaultCodeConfig,
  normalizeCodeConfig,
  parseCodeJsonSchemaDraft,
  serializeCodeConfig,
  validateCodeJsonSchema,
} from './codeNodeConfig';
import MobileBlocker from './components/MobileBlocker';
import { parseSimpleCel } from './simpleCel';
import { extractUpstreamVariables } from './components/PromptTextArea';
import { toDocumentVariableOptions } from './documentConfig';
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
import CanvasControls from './CanvasControls';
import NodePalette from './NodePalette';
import NodePanel from './panels/NodePanel';
import { WorkflowModelsContext } from './WorkflowModelsContext';
import AgentPanel from './panels/AgentPanel';
import CodePanel from './panels/CodePanel';
import ConditionPanel from './panels/ConditionPanel';
import NotePanel from './panels/NotePanel';
import StatePanel from './panels/StatePanel';
import WorkflowPreview from './WorkflowPreview';
import {
  nodeResourceIds,
  stoppedNodeResources,
  withoutNodeResource,
} from './nodeResources';
import {
  type AgentNodeConfig,
  findFreePosition,
  NO_ESCAPE,
  normalizeConditionCases,
  schemaErrorText,
  type UserTool,
  validateJsonSchemaConfig,
} from './workflowHelpers';
import { selectWorkflowPreviewStatus } from './workflowPreviewSlice';
import { readerIdFromToken } from '../../utils/personLabel';
import { canAddToolToOwn, getToolDisplayName } from '../../utils/toolUtils';

import type { Model } from '../../models/types';

const PRIMARY_ACTION_SPINNER_DELAY_MS = 180;

/** How a save ended; `cancelled` when the caller declined to sponsor. */
type WorkflowSaveOutcome = 'saved' | 'failed' | 'cancelled';
// A node added from the palette while one is selected lands this far right
// of it (then moves down until it covers nothing).
const ADD_BESIDE_GAP_X = 80;
// Roughly half a node's size, to centre a new node in the view.
const NEW_NODE_HALF_WIDTH = 100;
const NEW_NODE_HALF_HEIGHT = 32;
// A duplicate sits this far down and right of its original.
const DUPLICATE_OFFSET = 40;

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
    chunks: '6',
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
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const readerId = useMemo(() => readerIdFromToken(token), [token]);
  const sourceDocs = useSelector(selectSourceDocs);
  const previewStatus = useSelector(selectWorkflowPreviewStatus);
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
  const [showDetails, setShowDetails] = useState(false);
  // A save asked for by the details sheet runs after its values reach state.
  const [detailsSaveRequested, setDetailsSaveRequested] = useState(false);
  const [detailsSaving, setDetailsSaving] = useState(false);
  const [detailsSaveFailed, setDetailsSaveFailed] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [showPrimaryActionSpinner, setShowPrimaryActionSpinner] =
    useState(false);
  const [publishErrors, setPublishErrors] = useState<string[]>([]);
  // Asks before a node resource the owner can't use runs with the
  // caller's access; the save that asked gets the retried save's result.
  const sponsorPrompt = useSponsorPrompt();
  // What runs on the nodes with an editor's access and what stopped, from
  // the workflow read (people who may edit it).
  const [workflowResources, setWorkflowResources] = useState<{
    sponsors: ResourceSponsor[];
    states: ResourceState[];
    audience?: SponsorAudience;
  }>({ sponsors: [], states: [] });
  // Keys of stopped node resources the caller agreed to run with their
  // access; sent as ``confirm_sponsor`` with the next save.
  const [takeovers, setTakeovers] = useState<string[]>([]);
  // Bumped after a reconnect so the run state is read again.
  const [resourcesReloadKey, setResourcesReloadKey] = useState(0);
  const signInAgain = useSignInAgain({
    onConnected: () => setResourcesReloadKey((key) => key + 1),
  });
  const [errorContext, setErrorContext] = useState<'preview' | 'publish'>(
    'publish',
  );
  const [showNodeConfig, setShowNodeConfig] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');
  const [agentDetails, setAgentDetails] = useState<ActiveState>('INACTIVE');
  // Access details opened from Share to allow changes: its allowlist unfolds.
  const [detailsOnApiWrites, setDetailsOnApiWrites] = useState(false);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [isDeletingAgent, setIsDeletingAgent] = useState(false);
  const [currentAgent, setCurrentAgent] = useState<Agent>(
    createEmptyWorkflowAgent(),
  );
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [savedWorkflowSignature, setSavedWorkflowSignature] = useState<
    string | null
  >(null);
  const [availableModels, setAvailableModels] = useState<Model[]>([]);
  const modelNames = useMemo(
    () =>
      Object.fromEntries(
        availableModels.map((model) => [model.id, model.display_name]),
      ),
    [availableModels],
  );
  const [defaultAgentModelId, setDefaultAgentModelId] = useState('');
  const [availableTools, setAvailableTools] = useState<UserTool[]>([]);
  // Names of every tool and source the saved graph references, whoever owns
  // them, so node pickers keep a remove-only option for the owner's private
  // ones (GET /api/workflows/<id> ``ref_details``).
  const [nodeRefNames, setNodeRefNames] = useState<{
    tools: { id: string; label: string }[];
    sources: { id: string; label: string }[];
  }>({ tools: [], sources: [] });
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

  /**
   * Add a node of a palette type at a flow position, with its default config.
   * Takes an undo snapshot first; the selection is left as it was.
   */
  const createNode = useCallback(
    (type: string, position: XYPosition) => {
      takeSnapshot();

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
    [availableModels, defaultAgentModelId, takeSnapshot],
  );

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const type = event.dataTransfer.getData('application/reactflow');
      if (!type) return;

      createNode(
        type,
        reactFlowInstance.screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        }),
      );
    },
    [reactFlowInstance, createNode],
  );

  // Click or Enter on a palette pill: beside the selected node, else in the
  // middle of what the canvas shows.
  const handleAddNodeFromPalette = useCallback(
    (type: string) => {
      const anchor = selectedNode
        ? nodes.find((n) => n.id === selectedNode.id)
        : undefined;
      if (anchor) {
        createNode(
          type,
          findFreePosition(nodes, {
            x: anchor.position.x + (anchor.width ?? 0) + ADD_BESIDE_GAP_X,
            y: anchor.position.y,
          }),
        );
        return;
      }
      const rect = reactFlowWrapper.current?.getBoundingClientRect();
      const center = rect
        ? reactFlowInstance.screenToFlowPosition({
            x: rect.left + rect.width / 2,
            y: rect.top + rect.height / 2,
          })
        : { x: 0, y: 0 };
      // Positions are a node's top-left corner; centre a typical node.
      createNode(
        type,
        findFreePosition(nodes, {
          x: center.x - NEW_NODE_HALF_WIDTH,
          y: center.y - NEW_NODE_HALF_HEIGHT,
        }),
      );
    },
    [selectedNode, nodes, createNode, reactFlowInstance],
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

  // Clone the open node beside itself and open the copy.
  const handleDuplicateNode = useCallback(() => {
    if (!selectedNode || selectedNode.type === 'start') return;
    const original = nodes.find((n) => n.id === selectedNode.id);
    if (!original) return;
    takeSnapshot();
    const copy: Node = {
      id: `${original.type}_${Date.now()}`,
      type: original.type,
      position: {
        x: original.position.x + DUPLICATE_OFFSET,
        y: original.position.y + DUPLICATE_OFFSET,
      },
      data: structuredClone(original.data),
      selected: true,
    };
    setNodes((nds) =>
      nds.map((n) => (n.selected ? { ...n, selected: false } : n)).concat(copy),
    );
    setSelectedNode(copy);
    setShowNodeConfig(true);
  }, [selectedNode, nodes, takeSnapshot]);

  const handleRemoveConditionBranch = useCallback(
    (sourceHandle: string) => {
      if (!selectedNode) return;
      const nodeId = selectedNode.id;
      setEdges((eds) =>
        eds.filter(
          (edge) =>
            !(edge.source === nodeId && edge.sourceHandle === sourceHandle),
        ),
      );
    },
    [selectedNode],
  );

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
      e.defaultPrevented ||
      showPreview ||
      showDetails ||
      isEditableTarget(e.target);

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
    showDetails,
  ]);

  const handlePaneClick = useCallback(() => {
    setShowNodeConfig(false);
    setSelectedNode(null);
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
          // Shared tools the caller can't add to their own agents stay out.
          setAvailableTools(
            (toolsData.tools as UserTool[]).filter(canAddToolToOwn),
          );
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

  const applyResourceDetails = useCallback(
    (data: {
      resource_sponsors?: ResourceSponsor[];
      resource_states?: ResourceState[];
      sponsor_audience?: SponsorAudience;
    }) =>
      setWorkflowResources({
        sponsors: data.resource_sponsors ?? [],
        states: data.resource_states ?? [],
        audience: data.sponsor_audience,
      }),
    [],
  );

  // Fresh sponsor details and run state after a save or a reconnect,
  // without touching the canvas.
  const refreshResourceDetails = useCallback(
    async (id: string | null) => {
      if (!id) return;
      try {
        const response = await userService.getWorkflow(id, token);
        if (!response.ok) return;
        const responseData = await response.json();
        applyResourceDetails(responseData.data ?? {});
      } catch {
        // The notice keeps what it showed.
      }
    },
    [applyResourceDetails, token],
  );

  useEffect(() => {
    if (resourcesReloadKey > 0) void refreshResourceDetails(workflowId);
    // Only a reconnect asks for this; the workflow id is read when it does.
  }, [resourcesReloadKey, refreshResourceDetails]);

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
          ref_details: refDetails,
        } = responseData.data;
        applyResourceDetails(responseData.data);
        setNodeRefNames({
          tools: (refDetails?.tools ?? []).map(
            (tool: { id: string; name?: string; display_name?: string }) => ({
              id: tool.id,
              label: getToolDisplayName(tool),
            }),
          ),
          sources: (refDetails?.sources ?? []).map(
            (source: { id: string; name: string | null }) => ({
              id: source.id,
              label: source.name || '',
            }),
          ),
        });
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
  }, [
    workflowId,
    reactFlowInstance,
    token,
    clearHistory,
    applyResourceDetails,
  ]);

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
        imageFile !== null ||
        takeovers.length > 0
      : false;

  const persistWorkflow = useCallback(
    async (navigateAfterSuccess: boolean): Promise<WorkflowSaveOutcome> => {
      setPublishErrors([]);
      setErrorContext('publish');

      const validationErrors = validateWorkflow();
      if (validationErrors.length > 0) {
        setPublishErrors(validationErrors);
        return 'failed';
      }

      setIsPublishing(true);
      let createdWorkflowId: string | null = null;
      try {
        const workflowPayload = buildWorkflowPayload();

        let savedWorkflowId = workflowId;
        if (workflowId) {
          // A node tool or source the owner can't use would run with the
          // caller's access: ask first, then save again with their answer.
          const updateResponse = await saveWithSponsorConsent(
            (confirm) =>
              userService.updateWorkflow(
                workflowId,
                confirm.length > 0
                  ? { ...workflowPayload, confirm_sponsor: confirm }
                  : workflowPayload,
                token,
              ),
            sponsorPrompt.ask,
            takeovers,
          );
          if (!updateResponse) return 'cancelled';
          if (!updateResponse.ok) {
            const refusal = await readSponsorRefusal(updateResponse);
            if (refusal?.kind === 'unexpected') {
              // Someone changed the workflow since the caller chose.
              setTakeovers([]);
              void refreshResourceDetails(workflowId);
              throw new Error(t('agents.form.sponsors.confirmationOutdated'));
            }
            if (refusal?.kind === 'notAllowed') {
              throw new Error(
                sponsorNotAllowedMessage(t, i18n.language, refusal.resources),
              );
            }
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
          setTakeovers([]);
          void refreshResourceDetails(workflowId);
          if (navigateAfterSuccess) {
            navigateBackToAgents();
          }
          return 'saved';
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
            return 'failed';
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
        return 'saved';
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
        return 'failed';
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
      currentAgent.allow_system_prompt_override,
      folderId,
      navigateBackToAgents,
      t,
      i18n.language,
      sponsorPrompt.ask,
      takeovers,
      refreshResourceDetails,
    ],
  );

  const openDetails = useCallback(() => {
    setDetailsSaveFailed(false);
    setShowDetails(true);
  }, []);

  // Save from the details sheet: put its values into the builder, then save
  // once they are in state (the effect below), so the request carries them.
  const handleDetailsSave = useCallback((values: WorkflowDetailsSave) => {
    setWorkflowName(values.name);
    setWorkflowDescription(values.description);
    setCurrentAgent((prev) => ({
      ...prev,
      allow_system_prompt_override: values.allowPromptOverride,
    }));
    if (values.imageFile) setImageFile(values.imageFile);
    setDetailsSaveRequested(true);
  }, []);

  useEffect(() => {
    if (!detailsSaveRequested) return;
    setDetailsSaveRequested(false);
    setDetailsSaving(true);
    setDetailsSaveFailed(false);
    void persistWorkflow(false).then((outcome) => {
      setDetailsSaving(false);
      if (outcome === 'saved') setShowDetails(false);
      // Declining the sponsor confirmation leaves the sheet open, no error.
      else if (outcome === 'failed') setDetailsSaveFailed(true);
    });
  }, [detailsSaveRequested, persistWorkflow]);

  // Save on a saved workflow is an edit; the first save publishes it. A new
  // workflow has no access fields, so it reads as the owner's.
  // Without it the Save/Publish button isn't rendered at all.
  const canSubmit = can(currentAgent, canManageAgent ? 'edit' : 'publish');
  const isPrimaryActionDisabled =
    isPublishing || (canManageAgent && !hasSavableChanges);
  const primaryActionLabel = canManageAgent
    ? t('agents.form.buttons.save')
    : t('agents.form.buttons.publish');

  const handlePrimaryAction = useCallback(() => {
    if (isPrimaryActionDisabled) return;
    void persistWorkflow(false);
  }, [isPrimaryActionDisabled, persistWorkflow]);

  // Stopped node resources still on the canvas.
  const stoppedResources = useMemo(
    () =>
      stoppedNodeResources(workflowResources.states, nodeResourceIds(nodes)),
    [workflowResources.states, nodes],
  );

  const resolveResourceName = useCallback(
    (item: NamedResource): string => {
      if (item.name) return item.name;
      const known = (
        item.type === 'tool' ? nodeRefNames.tools : nodeRefNames.sources
      ).find((entry) => entry.id.toLowerCase() === item.id)?.label;
      return known || unnamedResourceLabel(t, item);
    },
    [nodeRefNames, t],
  );

  /** Take a stopped tool or source off every agent node; saving stores it. */
  const removeResource = useCallback(
    (item: ResourceState) => {
      takeSnapshot();
      setNodes((prev) => withoutNodeResource(prev, item));
      setTakeovers((prev) => prev.filter((k) => k !== item.key));
    },
    [takeSnapshot],
  );

  /**
   * Ask before a stopped node resource runs with the caller's access,
   * naming who reaches it through the workflow; on yes the next save
   * confirms it.
   */
  const takeOverResource = useCallback(
    async (item: ResourceState) => {
      const agreed = await confirmTakeOver(
        sponsorPrompt.ask,
        item,
        resolveResourceName(item),
        workflowResources.audience,
      );
      if (agreed)
        setTakeovers((prev) =>
          prev.includes(item.key) ? prev : [...prev, item.key],
        );
    },
    [resolveResourceName, sponsorPrompt.ask, workflowResources.audience],
  );

  /** Sign a stopped node tool's connection in again, in place where possible. */
  const reconnectResource = useCallback(
    (item: ResourceState) => {
      const connection = item.connection;
      if (!connection?.id || !connection.connector_key) return;
      const isMcp =
        availableTools.find((tool) => tool.id === item.id)?.name === 'mcp_tool';
      signInAgain.reconnect(
        { id: connection.id, connector_key: connection.connector_key },
        isMcp ? item.id : undefined,
      );
    },
    [availableTools, signInAgain],
  );

  const resourceNoticeAgent = useMemo<Agent>(
    () => ({ ...currentAgent, resource_sponsors: workflowResources.sponsors }),
    [currentAgent, workflowResources.sponsors],
  );
  // Only stopped items float; who added what is in the node pickers.
  const showResourceNotice = canManageAgent && stoppedResources.length > 0;

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
      <div className="bg-background fixed inset-0 z-50 hidden h-dvh w-full flex-col lg:flex">
        <div className="border-border bg-background flex items-center justify-between gap-4 border-b px-6 py-4">
          <AgentPageHeader
            agentId={canManageAgent ? effectiveAgentId : undefined}
            agentName={workflowName || t('agents.workflow.builder.newWorkflow')}
            agentEditPath={agentEditPath(effectiveAgentId, true)}
            agentImage={currentAgentImage}
            access={canManageAgent ? currentAgent : undefined}
            onNameClick={openDetails}
            status={
              canManageAgent && currentAgent.status !== 'draft' ? (
                <Badge variant="success">
                  {t('agents.form.status.published')}
                </Badge>
              ) : (
                <Badge variant="neutral">{t('agents.card.draft')}</Badge>
              )
            }
            inline
          />
          <div className="flex shrink-0 items-center gap-2">
            {(!canManageAgent || hasSavableChanges) && (
              <span className="text-muted-foreground mr-2 text-sm">
                {t('agents.workflow.builder.unsavedChanges')}
              </span>
            )}
            <Button
              type="button"
              variant="outline"
              size="field"
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
            {canSubmit && (
              <Button
                type="button"
                onClick={handlePrimaryAction}
                disabled={isPrimaryActionDisabled}
                loading={showPrimaryActionSpinner}
                size="field"
                shape="pill"
              >
                {primaryActionLabel}
              </Button>
            )}
            <ActionMenu
              size="toolbar"
              triggerLabel={t('agents.form.buttons.moreActions')}
              options={[
                {
                  label: t('agents.workflow.builder.editDetailsMenu'),
                  icon: Pencil,
                  onClick: openDetails,
                },
                ...(canManageAgent && can(currentAgent, 'manage_access_details')
                  ? [
                      {
                        label: t('agents.form.buttons.accessDetails'),
                        icon: Link,
                        onClick: () => setAgentDetails('ACTIVE'),
                      },
                    ]
                  : []),
                ...(canManageAgent && can(currentAgent, 'share')
                  ? [
                      {
                        label: t('agents.shareWithTeam'),
                        icon: Users,
                        onClick: () => setShareModalOpen(true),
                      },
                    ]
                  : []),
                ...(canManageAgent && can(currentAgent, 'delete')
                  ? [
                      {
                        label: t('agents.form.buttons.delete'),
                        icon: Trash2,
                        variant: 'destructive' as const,
                        disabled: isDeletingAgent,
                        onClick: () => setDeleteConfirmation('ACTIVE'),
                      },
                    ]
                  : []),
              ]}
            />
          </div>
        </div>

        {publishErrors.length > 0 && !showDetails && (
          <div className="pointer-events-none absolute top-20 right-0 left-0 z-20 flex justify-center px-4">
            <div className="bg-card pointer-events-auto w-full max-w-md rounded-xl shadow-md">
              <Alert variant="destructive" onClose={() => setPublishErrors([])}>
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
              </Alert>
            </div>
          </div>
        )}

        <div className="relative flex min-h-0 flex-1 overflow-hidden">
          <NodePalette
            onAdd={handleAddNodeFromPalette}
            onDragStart={handleNodeDragStart}
          />

          <div
            ref={reactFlowWrapper}
            className="bg-muted relative min-w-0 flex-1"
          >
            {showResourceNotice && (
              <FloatingResourceNotice
                stoppedCount={stoppedResources.length}
                // The publish errors float over the same corner; they win.
                hidden={publishErrors.length > 0 && !showDetails}
              >
                {(close) => (
                  <ResourceStatusNotice
                    agent={resourceNoticeAgent}
                    stopped={stoppedResources}
                    resolveName={resolveResourceName}
                    readerId={readerId}
                    takeovers={takeovers}
                    onTakeOver={(item) => void takeOverResource(item)}
                    onUndoTakeover={(key) =>
                      setTakeovers((prev) => prev.filter((k) => k !== key))
                    }
                    onRemove={removeResource}
                    onReconnect={reconnectResource}
                    onClose={close}
                  />
                )}
              </FloatingResourceNotice>
            )}
            <WorkflowModelsContext.Provider value={modelNames}>
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
                proOptions={{ hideAttribution: true }}
                fitView
              >
                <Background />
                <CanvasControls
                  onUndo={undo}
                  onRedo={redo}
                  canUndo={canUndo}
                  canRedo={canRedo}
                />
              </ReactFlow>
            </WorkflowModelsContext.Provider>
          </div>

          {showNodeConfig && selectedNode && (
            <NodePanel
              node={selectedNode}
              onClose={() => setShowNodeConfig(false)}
              onDuplicate={handleDuplicateNode}
              onDelete={handleDeleteNode}
              onUpdate={handleUpdateNodeData}
            >
              {selectedNode.type === 'agent' && (
                <AgentPanel
                  node={selectedNode}
                  onUpdate={handleUpdateNodeData}
                  nodes={nodes}
                  edges={edges}
                  availableModels={availableModels}
                  availableTools={availableTools}
                  sourceOptions={sourceOptions}
                  attachedTools={nodeRefNames.tools}
                  attachedSources={nodeRefNames.sources}
                  documentOptions={selectedAgentDocumentOptions}
                  jsonSchemaText={selectedAgentJsonSchemaText}
                  jsonSchemaError={selectedAgentJsonSchemaError}
                  modelSupportsStructuredOutput={
                    selectedAgentModelSupportsStructuredOutput
                  }
                  onJsonSchemaChange={handleAgentJsonSchemaChange}
                />
              )}
              {selectedNode.type === 'note' && (
                <NotePanel
                  node={selectedNode}
                  onUpdate={handleUpdateNodeData}
                />
              )}
              {selectedNode.type === 'state' && (
                <StatePanel
                  node={selectedNode}
                  onUpdate={handleUpdateNodeData}
                />
              )}
              {selectedNode.type === 'condition' && (
                <ConditionPanel
                  node={selectedNode}
                  onUpdate={handleUpdateNodeData}
                  onRemoveBranch={handleRemoveConditionBranch}
                />
              )}
              {selectedNode.type === 'code' && (
                <CodePanel
                  node={selectedNode}
                  onUpdate={handleUpdateNodeData}
                  documentOptions={selectedCodeDocumentOptions}
                  jsonSchemaText={selectedCodeJsonSchemaText}
                  jsonSchemaError={selectedCodeJsonSchemaError}
                  onJsonSchemaChange={handleCodeJsonSchemaChange}
                />
              )}
            </NodePanel>
          )}
        </div>

        <WorkflowDetailsSheet
          open={showDetails}
          onOpenChange={setShowDetails}
          details={{
            name: workflowName,
            description: workflowDescription,
            allowPromptOverride: Boolean(
              currentAgent.allow_system_prompt_override,
            ),
          }}
          currentImage={currentAgentImage}
          saving={detailsSaving}
          errors={detailsSaveFailed ? publishErrors : []}
          onSave={handleDetailsSave}
        />
        <AgentPreviewSheet
          open={showPreview}
          onOpenChange={setShowPreview}
          title={t('agents.form.sections.preview')}
          description={
            workflowDescription
              ? `${workflowName} · ${workflowDescription}`
              : workflowName
          }
          running={previewStatus === 'loading'}
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
                  type: n.type as 'start' | 'end' | 'agent' | 'state' | 'code',
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
        </AgentPreviewSheet>
        {sponsorPrompt.modal}
        {signInAgain.modals}
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
        {shareModalOpen && effectiveAgentId && (
          <ShareToTeamModal
            resourceType="agent"
            resourceId={effectiveAgentId}
            resourceName={workflowName}
            onClose={() => setShareModalOpen(false)}
            onOpenAccessDetails={
              canManageAgent && can(currentAgent, 'manage_access_details')
                ? () => {
                    setShareModalOpen(false);
                    setDetailsOnApiWrites(true);
                    setAgentDetails('ACTIVE');
                  }
                : undefined
            }
          />
        )}
        {canManageAgent && (
          <AgentDetailsModal
            agent={agentForDetails}
            mode="edit"
            modalState={agentDetails}
            setModalState={(state) => {
              setAgentDetails(state);
              if (state === 'INACTIVE') setDetailsOnApiWrites(false);
            }}
            openApiWrites={detailsOnApiWrites}
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
