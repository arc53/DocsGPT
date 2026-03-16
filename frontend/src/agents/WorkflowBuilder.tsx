import 'reactflow/dist/style.css';

import {
  AlertCircle,
  Bot,
  Database,
  Flag,
  Play,
  Settings,
  StickyNote,
  Trash2,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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

import modelService from '../api/services/modelService';
import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import { WorkflowNode } from './types/workflow';
import {
  AgentNode,
  EndNode,
  NoteNode,
  SetStateNode,
  StartNode,
} from './workflow/nodes';
import WorkflowPreview from './workflow/WorkflowPreview';

import type { Model } from '../models/types';
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

function WorkflowBuilderInner() {
  const navigate = useNavigate();
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
  const [publishErrors, setPublishErrors] = useState<string[]>([]);
  const [errorContext, setErrorContext] = useState<'preview' | 'publish'>(
    'publish',
  );
  const [showNodeConfig, setShowNodeConfig] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const configPanelRef = useRef<HTMLDivElement>(null);
  const workflowSettingsRef = useRef<HTMLDivElement>(null);
  const [availableModels, setAvailableModels] = useState<Model[]>([]);
  const [availableTools, setAvailableTools] = useState<UserTool[]>([]);

  const nodeTypes = useMemo<NodeTypes>(
    () => ({
      start: StartNode,
      agent: AgentNode,
      end: EndNode,
      note: NoteNode,
      state: SetStateNode,
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

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
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

      // Use screenToFlowPosition to correctly convert screen coordinates to flow coordinates
      // This accounts for viewport pan and zoom
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
        baseNode.data.config = {
          agent_type: 'classic',
          system_prompt: 'You are a helpful assistant.',
          prompt_template: '',
          stream_to_user: true,
          sources: [],
          tools: [],
        } as AgentNodeConfig;
      } else if (type === 'state') {
        baseNode.data.title = 'Set State';
        baseNode.data.variable = '';
        baseNode.data.value = '';
      } else if (type === 'note') {
        baseNode.data.title = 'Note';
        baseNode.data.label = 'Note';
      }

      setNodes((nds) => nds.concat(baseNode));
    },
    [reactFlowInstance],
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

  useEffect(() => {
    if (publishErrors.length > 0) {
      const timer = setTimeout(() => {
        setPublishErrors([]);
      }, 6000);
      return () => clearTimeout(timer);
    }
  }, [publishErrors.length]);

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

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      const isInsidePanel = configPanelRef.current?.contains(target) ?? false;
      const isInsideRadixPortal =
        target.closest('[data-radix-popper-content-wrapper]') !== null ||
        target.closest('[data-radix-select-content]') !== null ||
        target.closest('[role="listbox"]') !== null ||
        target.closest('[cmdk-root]') !== null;
      if (!isInsidePanel && !isInsideRadixPortal) {
        setShowNodeConfig(false);
      }
    };
    if (showNodeConfig) {
      document.addEventListener('mousedown', handleClickOutside);
      return () =>
        document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showNodeConfig]);

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
          setAvailableModels(modelService.transformModels(modelsData.models));
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
    const loadAgentDetails = async () => {
      if (!agentId) return;
      try {
        const response = await userService.getAgent(agentId, null);
        if (!response.ok) throw new Error('Failed to fetch agent');
        const agent = await response.json();
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
  }, [agentId]);

  useEffect(() => {
    const loadWorkflow = async () => {
      if (!workflowId) return;
      try {
        const response = await userService.getWorkflow(workflowId, null);
        if (!response.ok) throw new Error('Failed to fetch workflow');
        const responseData = await response.json();
        const { workflow, nodes: apiNodes, edges: apiEdges } = responseData;
        setWorkflowName(workflow.name);
        setWorkflowDescription(workflow.description || '');
        setNodes(
          apiNodes.map((n: WorkflowNode) => {
            const nodeData: Record<string, unknown> = {
              title: n.title,
              label: n.title,
            };
            if (n.type === 'agent' && n.data) {
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
          }),
        );
        setEdges(
          apiEdges.map(
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
          ),
        );
        // Fit view after loading with slight delay to ensure nodes are rendered
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
  }, [workflowId, reactFlowInstance]);

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

    return errors;
  }, [workflowName, nodes, edges]);

  const handlePublish = useCallback(async () => {
    setPublishErrors([]);
    setErrorContext('publish');

    const validationErrors = validateWorkflow();
    if (validationErrors.length > 0) {
      setPublishErrors(validationErrors);
      return;
    }

    setIsPublishing(true);
    try {
      const workflowPayload = {
        name: workflowName,
        description: workflowDescription,
        nodes: nodes.map((n) => ({
          id: n.id,
          type: n.type as 'start' | 'end' | 'agent' | 'note' | 'state',
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
      };

      let savedWorkflowId = workflowId;
      if (workflowId) {
        const updateResponse = await userService.updateWorkflow(
          workflowId,
          workflowPayload,
          null,
        );
        if (!updateResponse.ok) {
          const errorData = await updateResponse.json().catch(() => ({}));
          throw new Error(errorData.message || 'Failed to update workflow');
        }

        if (currentAgentId) {
          const agentFormData = new FormData();
          agentFormData.append('name', workflowName);
          agentFormData.append(
            'description',
            workflowDescription || `Workflow agent: ${workflowName}`,
          );
          agentFormData.append('status', 'published');
          const agentUpdateResponse = await userService.updateAgent(
            currentAgentId,
            agentFormData,
            null,
          );
          if (!agentUpdateResponse.ok) {
            throw new Error('Failed to update agent');
          }
        }
      } else {
        const createResponse = await userService.createWorkflow(
          workflowPayload,
          null,
        );
        if (!createResponse.ok) {
          const errorData = await createResponse.json().catch(() => ({}));
          const backendErrors = errorData.errors || [];
          if (backendErrors.length > 0) {
            setPublishErrors(backendErrors);
            return;
          }
          throw new Error(errorData.message || 'Failed to create workflow');
        }
        const responseData = await createResponse.json();
        savedWorkflowId = responseData.id;

        const agentFormData = new FormData();
        agentFormData.append('name', workflowName);
        agentFormData.append(
          'description',
          workflowDescription || `Workflow agent: ${workflowName}`,
        );
        agentFormData.append('agent_type', 'workflow');
        agentFormData.append('status', 'published');
        agentFormData.append('workflow', savedWorkflowId || '');
        if (folderId) agentFormData.append('folder_id', folderId);

        const agentResponse = await userService.createAgent(
          agentFormData,
          null,
        );
        if (!agentResponse.ok) throw new Error('Failed to create agent');
      }

      navigate(folderId ? `/agents?folder=${folderId}` : '/agents');
    } catch (error) {
      console.error('Failed to publish workflow:', error);
      setPublishErrors([
        error instanceof Error ? error.message : 'Failed to publish workflow',
      ]);
    } finally {
      setIsPublishing(false);
    }
  }, [
    workflowName,
    workflowDescription,
    nodes,
    edges,
    navigate,
    folderId,
    workflowId,
    currentAgentId,
    validateWorkflow,
  ]);

  return (
    <div className="bg-lotion dark:bg-outer-space flex h-screen w-full flex-col">
      <div className="border-light-silver dark:bg-raisin-black flex items-center justify-between border-b bg-white px-6 py-4 dark:border-[#3A3A3A]">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/agents')}
            className="rounded-full border p-3 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
          >
            <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
          </button>
          <div className="relative">
            <button
              onClick={() => setShowWorkflowSettings(!showWorkflowSettings)}
              className="flex items-center gap-2 text-left"
            >
              <div>
                <div className="text-xl font-bold text-gray-900 dark:text-white">
                  {workflowName || 'New Workflow'}
                </div>
                {workflowDescription && (
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {workflowDescription.length > 50
                      ? `${workflowDescription.slice(0, 50)}...`
                      : workflowDescription}
                  </div>
                )}
              </div>
              <Settings
                size={16}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
              />
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
                <button
                  onClick={() => setShowWorkflowSettings(false)}
                  className="bg-violets-are-blue hover:bg-purple-30 w-full rounded-lg px-3 py-2 text-sm font-medium text-white"
                >
                  Done
                </button>
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
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
            onClick={handlePublish}
            disabled={isPublishing}
            className="bg-violets-are-blue hover:bg-purple-30 rounded-full px-6 py-2 text-sm font-medium text-white shadow-sm transition-colors disabled:opacity-50"
          >
            {isPublishing ? 'Publishing...' : 'Publish'}
          </button>
        </div>
      </div>

      {publishErrors.length > 0 && (
        <div className="pointer-events-none absolute top-20 right-0 left-64 z-50 flex justify-center px-4">
          <Alert
            variant="destructive"
            className="pointer-events-auto w-full max-w-md bg-red-50 shadow-lg dark:bg-red-950/20"
          >
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>
              {errorContext === 'preview'
                ? 'Unable to preview workflow'
                : 'Unable to publish workflow'}
            </AlertTitle>
            <AlertDescription>
              <ul className="mt-2 list-inside list-disc space-y-1">
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
                onDragStart={(e) =>
                  e.dataTransfer.setData('application/reactflow', 'agent')
                }
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
                onDragStart={(e) =>
                  e.dataTransfer.setData('application/reactflow', 'end')
                }
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
                onDragStart={(e) =>
                  e.dataTransfer.setData('application/reactflow', 'note')
                }
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
                onDragStart={(e) =>
                  e.dataTransfer.setData('application/reactflow', 'state')
                }
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
            onDrop={onDrop}
            onDragOver={onDragOver}
            onNodeClick={handleNodeClick}
            nodeTypes={nodeTypes}
            fitView
          >
            <Background />
            <Controls />
          </ReactFlow>

          {showNodeConfig && selectedNode && (
            <div
              ref={configPanelRef}
              className="border-light-silver dark:bg-raisin-black absolute top-4 right-4 w-96 rounded-2xl border bg-white shadow-[0px_4px_40px_-3px_#0000001A] dark:border-[#3A3A3A]"
            >
              <div className="border-light-silver flex items-center justify-between border-b p-4 dark:border-[#3A3A3A]">
                <h3 className="font-semibold text-gray-900 dark:text-white">
                  {selectedNode.type === 'start' && 'Start Node'}
                  {selectedNode.type === 'end' && 'End Node'}
                  {selectedNode.type === 'agent' && 'AI Agent'}
                  {selectedNode.type === 'note' && 'Note'}
                  {selectedNode.type === 'state' && 'Set State'}
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
                    <div className="font-mono text-xs text-gray-700 dark:text-gray-300">
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
                                  <SelectItem value="react">ReAct</SelectItem>
                                </SelectContent>
                              </Select>
                            </div>
                            <div>
                              <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                                Model
                              </label>
                              <Select
                                value={selectedNode.data.config?.model_id || ''}
                                onValueChange={(value) => {
                                  const selectedModel = availableModels.find(
                                    (m) => m.id === value,
                                  );
                                  handleUpdateNodeData({
                                    config: {
                                      ...(selectedNode.data.config || {}),
                                      model_id: value,
                                      llm_name: selectedModel?.provider || '',
                                    },
                                  });
                                }}
                              >
                                <SelectTrigger className="w-full">
                                  <SelectValue placeholder="Select a model" />
                                </SelectTrigger>
                                <SelectContent>
                                  {availableModels.map((model) => (
                                    <SelectItem key={model.id} value={model.id}>
                                      {model.display_name} · {model.provider}
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
                                  selectedNode.data.config?.system_prompt ||
                                  'You are a helpful assistant.'
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
                            <div>
                              <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                                Prompt Template
                              </label>
                              <textarea
                                value={
                                  selectedNode.data.config?.prompt_template ||
                                  ''
                                }
                                onChange={(e) =>
                                  handleUpdateNodeData({
                                    config: {
                                      ...(selectedNode.data.config || {}),
                                      prompt_template: e.target.value,
                                    },
                                  })
                                }
                                className="border-light-silver focus:ring-purple-30 w-full rounded-xl border bg-white px-3 py-2 text-sm transition-all outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-white"
                                rows={4}
                                placeholder="Use {{variable}} for dynamic content"
                              />
                            </div>
                            <div>
                              <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                                Output Variable
                              </label>
                              <input
                                type="text"
                                value={
                                  selectedNode.data.config?.output_variable ||
                                  ''
                                }
                                onChange={(e) =>
                                  handleUpdateNodeData({
                                    config: {
                                      ...(selectedNode.data.config || {}),
                                      output_variable: e.target.value,
                                    },
                                  })
                                }
                                className="border-light-silver focus:ring-purple-30 w-full rounded-xl border bg-white px-3 py-2 text-sm transition-all outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-white"
                                placeholder="Variable name for output"
                              />
                            </div>
                            <div className="flex items-center gap-2">
                              <input
                                type="checkbox"
                                id="stream_to_user"
                                checked={
                                  selectedNode.data.config?.stream_to_user ??
                                  true
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
                                selected={selectedNode.data.config?.tools || []}
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
                            <div>
                              <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                                Variable Name
                              </label>
                              <input
                                type="text"
                                value={selectedNode.data.variable || ''}
                                onChange={(e) =>
                                  handleUpdateNodeData({
                                    variable: e.target.value,
                                  })
                                }
                                className="border-light-silver focus:ring-purple-30 w-full rounded-xl border bg-white px-3 py-2 text-sm transition-all outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-white"
                                placeholder="e.g. analysis_type"
                              />
                            </div>
                            <div>
                              <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                                Value
                              </label>
                              <input
                                type="text"
                                value={selectedNode.data.value || ''}
                                onChange={(e) =>
                                  handleUpdateNodeData({
                                    value: e.target.value,
                                  })
                                }
                                className="border-light-silver focus:ring-purple-30 w-full rounded-xl border bg-white px-3 py-2 text-sm transition-all outline-none focus:ring-2 dark:border-[#3A3A3A] dark:bg-[#2C2C2C] dark:text-white"
                                placeholder="e.g. price_check"
                              />
                            </div>
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
          )}
        </div>
      </div>

      {/* Preview Panel */}
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
              nodes: nodes.map((n) => ({
                id: n.id,
                type: n.type as 'start' | 'end' | 'agent' | 'note' | 'state',
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
    </div>
  );
}

export default function WorkflowBuilder() {
  return (
    <ReactFlowProvider>
      <WorkflowBuilderInner />
    </ReactFlowProvider>
  );
}
