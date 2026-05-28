import isEqual from 'lodash/isEqual';
import { MoreHorizontal } from 'lucide-react';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';

import devicesService from '../api/services/devicesService';
import modelService from '../api/services/modelService';
import userService from '../api/services/userService';
import SourceIcon from '../assets/source.svg';
import { FileUpload } from '../components/FileUpload';
import {
  MultiSelectPopover,
  type MultiSelectPopoverItem,
} from '../components/MultiSelectPopover';
import Spinner from '../components/Spinner';
import AgentDetailsModal from '../modals/AgentDetailsModal';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState, Doc, Prompt } from '../models/misc';
import {
  selectAgentFolders,
  selectSelectedAgent,
  selectSourceDocs,
  selectToken,
  selectPrompts,
  setAgentFolders,
  setSelectedAgent,
  setPrompts,
} from '../preferences/preferenceSlice';
import PromptsModal from '../preferences/PromptsModal';
import Prompts from '../settings/Prompts';
import { UserToolType } from '../settings/types';
import { getToolDisplayName } from '../utils/toolUtils';
import AgentPageHeader from './AgentPageHeader';
import AgentPreview from './AgentPreview';
import { Agent, ToolSummary } from './types';
import WorkflowBuilder from './workflow/WorkflowBuilder';

import type { Model } from '../models/types';

export default function NewAgent({ mode }: { mode: 'new' | 'edit' | 'draft' }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const { agentId } = useParams();

  const [searchParams] = useSearchParams();
  const folderIdFromUrl = searchParams.get('folder_id');

  const token = useSelector(selectToken);
  const sourceDocs = useSelector(selectSourceDocs);
  const selectedAgent = useSelector(selectSelectedAgent);
  const prompts = useSelector(selectPrompts);
  const agentFolders = useSelector(selectAgentFolders);

  const [validatedFolderId, setValidatedFolderId] = useState<string | null>(
    null,
  );

  const [effectiveMode, setEffectiveMode] = useState(mode);
  const [agent, setAgent] = useState<Agent>({
    id: agentId || '',
    name: '',
    description: '',
    image: '',
    source: '',
    sources: [],
    chunks: '2',
    retriever: 'classic',
    prompt_id: 'default',
    tools: [],
    agent_type: 'classic',
    status: '',
    json_schema: undefined,
    limited_token_mode: false,
    token_limit: undefined,
    limited_request_mode: false,
    request_limit: undefined,
    allow_system_prompt_override: false,
    models: [],
    default_model_id: '',
  });
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [userTools, setUserTools] = useState<MultiSelectPopoverItem[]>([]);
  const [rawUserTools, setRawUserTools] = useState<UserToolType[]>([]);
  const [availableModels, setAvailableModels] = useState<Model[]>([]);
  const [isSourcePopupOpen, setIsSourcePopupOpen] = useState(false);
  const [isToolsPopupOpen, setIsToolsPopupOpen] = useState(false);
  const [isModelsPopupOpen, setIsModelsPopupOpen] = useState(false);
  const [selectedSourceIds, setSelectedSourceIds] = useState<Set<string>>(
    new Set(),
  );
  const [selectedTools, setSelectedTools] = useState<ToolSummary[]>([]);
  const [selectedModelIds, setSelectedModelIds] = useState<Set<string>>(
    new Set(),
  );
  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');
  const [agentDetails, setAgentDetails] = useState<ActiveState>('INACTIVE');
  const [addPromptModal, setAddPromptModal] = useState<ActiveState>('INACTIVE');
  const [hasChanges, setHasChanges] = useState(false);
  const [draftLoading, setDraftLoading] = useState(false);
  const [publishLoading, setPublishLoading] = useState(false);
  const [jsonSchemaText, setJsonSchemaText] = useState('');
  const [jsonSchemaValid, setJsonSchemaValid] = useState(true);
  const [isAdvancedSectionExpanded, setIsAdvancedSectionExpanded] =
    useState(false);

  const initialAgentRef = useRef<Agent | null>(null);
  const sourceAnchorButtonRef = useRef<HTMLButtonElement>(null);
  const toolAnchorButtonRef = useRef<HTMLButtonElement>(null);
  const modelAnchorButtonRef = useRef<HTMLButtonElement>(null);

  const modeConfig = {
    new: {
      heading: t('agents.form.headings.new'),
      buttonText: t('agents.form.buttons.publish'),
      showDelete: false,
      showSaveDraft: true,
      showAccessDetails: false,
      trackChanges: false,
    },
    edit: {
      heading: t('agents.form.headings.edit'),
      buttonText: t('agents.form.buttons.save'),
      showDelete: true,
      showSaveDraft: false,
      showAccessDetails: true,
      trackChanges: true,
    },
    draft: {
      heading: t('agents.form.headings.draft'),
      buttonText: t('agents.form.buttons.publish'),
      showDelete: true,
      showSaveDraft: true,
      showAccessDetails: false,
      trackChanges: false,
    },
  };
  const chunks = ['0', '2', '4', '6', '8', '10'];
  const agentTypes = [
    { label: t('agents.form.agentTypes.classic'), value: 'classic' },
    { label: 'Agentic', value: 'agentic' },
    { label: 'Research', value: 'research' },
  ];

  const isPublishable = () => {
    const hasRequiredFields =
      agent.name && agent.description && agent.prompt_id && agent.agent_type;
    const isJsonSchemaValidOrEmpty =
      jsonSchemaText.trim() === '' || jsonSchemaValid;
    const hasSource = selectedSourceIds.size > 0;
    return hasRequiredFields && isJsonSchemaValidOrEmpty && hasSource;
  };

  const isJsonSchemaInvalid = () => {
    return jsonSchemaText.trim() !== '' && !jsonSchemaValid;
  };

  const handleUpload = useCallback((files: File[]) => {
    if (files && files.length > 0) {
      const file = files[0];
      setImageFile(file);
    }
  }, []);

  const navigateBackToAgents = useCallback(() => {
    const targetPath = validatedFolderId
      ? `/agents?folder=${validatedFolderId}`
      : '/agents';
    navigate(targetPath);
  }, [navigate, validatedFolderId]);

  const handleCancel = () => {
    if (selectedAgent) dispatch(setSelectedAgent(null));
    navigateBackToAgents();
  };

  const handleDelete = async (agentId: string) => {
    const response = await userService.deleteAgent(agentId, token);
    if (!response.ok) throw new Error('Failed to delete agent');
    navigateBackToAgents();
  };

  const handleSaveDraft = async () => {
    const formData = new FormData();
    formData.append('name', agent.name);
    formData.append('description', agent.description);

    if (selectedSourceIds.size > 1) {
      const sourcesArray = Array.from(selectedSourceIds)
        .map((id) => {
          const sourceDoc = sourceDocs?.find(
            (source) =>
              source.id === id || source.retriever === id || source.name === id,
          );
          if (sourceDoc?.name === 'Default' && !sourceDoc?.id) {
            return 'default';
          }
          return sourceDoc?.id || id;
        })
        .filter(Boolean);
      formData.append('sources', JSON.stringify(sourcesArray));
      formData.append('source', '');
    } else if (selectedSourceIds.size === 1) {
      const singleSourceId = Array.from(selectedSourceIds)[0];
      const sourceDoc = sourceDocs?.find(
        (source) =>
          source.id === singleSourceId ||
          source.retriever === singleSourceId ||
          source.name === singleSourceId,
      );
      let finalSourceId;
      if (sourceDoc?.name === 'Default' && !sourceDoc?.id)
        finalSourceId = 'default';
      else finalSourceId = sourceDoc?.id || singleSourceId;
      formData.append('source', String(finalSourceId));
      formData.append('sources', JSON.stringify([]));
    } else {
      formData.append('source', '');
      formData.append('sources', JSON.stringify([]));
    }

    formData.append('chunks', agent.chunks);
    formData.append('retriever', agent.retriever);
    formData.append('prompt_id', agent.prompt_id);
    formData.append('agent_type', agent.agent_type);
    formData.append('status', 'draft');

    if (agent.limited_token_mode && agent.token_limit) {
      formData.append('limited_token_mode', 'True');
      formData.append('token_limit', agent.token_limit.toString());
    } else {
      formData.append('limited_token_mode', 'False');
      formData.append('token_limit', '0');
    }

    if (agent.limited_request_mode && agent.request_limit) {
      formData.append('limited_request_mode', 'True');
      formData.append('request_limit', agent.request_limit.toString());
    } else {
      formData.append('limited_request_mode', 'False');
      formData.append('request_limit', '0');
    }

    formData.append(
      'allow_system_prompt_override',
      agent.allow_system_prompt_override ? 'True' : 'False',
    );

    if (imageFile) formData.append('image', imageFile);

    if (agent.tools && agent.tools.length > 0)
      formData.append('tools', JSON.stringify(agent.tools));
    else formData.append('tools', '[]');

    if (agent.json_schema) {
      formData.append('json_schema', JSON.stringify(agent.json_schema));
    }

    if (agent.models && agent.models.length > 0) {
      formData.append('models', JSON.stringify(agent.models));
    }
    if (agent.default_model_id) {
      formData.append('default_model_id', agent.default_model_id);
    }
    if (agent.agent_type === 'workflow' && agent.workflow) {
      formData.append('workflow', JSON.stringify(agent.workflow));
    }

    if (effectiveMode === 'new' && validatedFolderId) {
      formData.append('folder_id', validatedFolderId);
    }

    try {
      setDraftLoading(true);
      const response =
        effectiveMode === 'new'
          ? await userService.createAgent(formData, token)
          : await userService.updateAgent(agent.id || '', formData, token);
      if (!response.ok) throw new Error('Failed to create agent draft');
      const data = await response.json();

      const updatedAgent = {
        ...agent,
        id: data.id || agent.id,
        image: data.image || agent.image,
      };
      setAgent(updatedAgent);

      if (effectiveMode === 'new') setEffectiveMode('draft');
    } catch (error) {
      console.error('Error saving draft:', error);
      throw new Error('Failed to save draft');
    } finally {
      setDraftLoading(false);
    }
  };

  const handlePublish = async () => {
    const formData = new FormData();
    formData.append('name', agent.name);
    formData.append('description', agent.description);

    if (selectedSourceIds.size > 1) {
      const sourcesArray = Array.from(selectedSourceIds)
        .map((id) => {
          const sourceDoc = sourceDocs?.find(
            (source) =>
              source.id === id || source.retriever === id || source.name === id,
          );
          if (sourceDoc?.name === 'Default' && !sourceDoc?.id) {
            return 'default';
          }
          return sourceDoc?.id || id;
        })
        .filter(Boolean);
      formData.append('sources', JSON.stringify(sourcesArray));
      formData.append('source', '');
    } else if (selectedSourceIds.size === 1) {
      const singleSourceId = Array.from(selectedSourceIds)[0];
      const sourceDoc = sourceDocs?.find(
        (source) =>
          source.id === singleSourceId ||
          source.retriever === singleSourceId ||
          source.name === singleSourceId,
      );
      let finalSourceId;
      if (sourceDoc?.name === 'Default' && !sourceDoc?.id)
        finalSourceId = 'default';
      else finalSourceId = sourceDoc?.id || singleSourceId;
      formData.append('source', String(finalSourceId));
      formData.append('sources', JSON.stringify([]));
    } else {
      formData.append('source', '');
      formData.append('sources', JSON.stringify([]));
    }

    formData.append('chunks', agent.chunks);
    formData.append('retriever', agent.retriever);
    formData.append('prompt_id', agent.prompt_id);
    formData.append('agent_type', agent.agent_type);
    formData.append('status', 'published');

    if (imageFile) formData.append('image', imageFile);
    if (agent.tools && agent.tools.length > 0)
      formData.append('tools', JSON.stringify(agent.tools));
    else formData.append('tools', '[]');

    if (agent.json_schema) {
      formData.append('json_schema', JSON.stringify(agent.json_schema));
    }

    // Always send the limited mode fields
    if (agent.limited_token_mode && agent.token_limit) {
      formData.append('limited_token_mode', 'True');
      formData.append('token_limit', agent.token_limit.toString());
    } else {
      formData.append('limited_token_mode', 'False');
      formData.append('token_limit', '0');
    }

    if (agent.limited_request_mode && agent.request_limit) {
      formData.append('limited_request_mode', 'True');
      formData.append('request_limit', agent.request_limit.toString());
    } else {
      formData.append('limited_request_mode', 'False');
      formData.append('request_limit', '0');
    }

    formData.append(
      'allow_system_prompt_override',
      agent.allow_system_prompt_override ? 'True' : 'False',
    );

    if (agent.models && agent.models.length > 0) {
      formData.append('models', JSON.stringify(agent.models));
    }
    if (agent.default_model_id) {
      formData.append('default_model_id', agent.default_model_id);
    }
    if (agent.agent_type === 'workflow' && agent.workflow) {
      formData.append('workflow', JSON.stringify(agent.workflow));
    }

    if (effectiveMode === 'new' && validatedFolderId) {
      formData.append('folder_id', validatedFolderId);
    }

    try {
      setPublishLoading(true);
      const response =
        effectiveMode === 'new'
          ? await userService.createAgent(formData, token)
          : await userService.updateAgent(agent.id || '', formData, token);
      if (!response.ok) throw new Error('Failed to publish agent');
      const data = await response.json();

      const updatedAgent = {
        ...agent,
        id: data.id || agent.id,
        key: data.key || agent.key,
        status: 'published',
        image: data.image || agent.image,
      };
      setAgent(updatedAgent);
      initialAgentRef.current = updatedAgent;

      if (effectiveMode === 'new' || effectiveMode === 'draft') {
        setEffectiveMode('edit');
        setAgentDetails('ACTIVE');
      }
      setImageFile(null);
    } catch (error) {
      console.error('Error publishing agent:', error);
      throw new Error('Failed to publish agent');
    } finally {
      setPublishLoading(false);
    }
  };

  const validateAndSetJsonSchema = (text: string) => {
    setJsonSchemaText(text);
    if (text.trim() === '') {
      setAgent({ ...agent, json_schema: undefined });
      setJsonSchemaValid(true);
      return;
    }
    try {
      const parsed = JSON.parse(text);
      setAgent({ ...agent, json_schema: parsed });
      setJsonSchemaValid(true);
    } catch (error) {
      setJsonSchemaValid(false);
    }
  };

  useEffect(() => {
    const getTools = async () => {
      const [toolsResponse, devicesResult] = await Promise.all([
        userService.getUserTools(token),
        // Tolerate failures here: the picker should still render the
        // tool list even if /api/devices returns an error or 401.
        devicesService.list(token).catch(() => ({ devices: [] })),
      ]);
      if (!toolsResponse.ok) throw new Error('Failed to fetch tools');
      const data = await toolsResponse.json();
      const devicesById = new Map<
        string,
        { online: boolean; last_seen_at: string | null | undefined }
      >();
      const onlineWindowMs = 30_000;
      (devicesResult.devices || []).forEach((d) => {
        const seen = d.last_seen_at ? Date.parse(d.last_seen_at) : NaN;
        const online =
          !Number.isNaN(seen) && Date.now() - seen < onlineWindowMs;
        devicesById.set(d.id, { online, last_seen_at: d.last_seen_at });
      });
      // Group ordering: builtins -> defaults -> user tools (sorted via the
      // MultiSelectPopover first-appearance grouping).
      const groupFor = (tool: UserToolType): string => {
        if (tool.builtin) return t('agents.form.toolsPopup.groupBuiltin');
        if (tool.default) return t('agents.form.toolsPopup.groupDefault');
        return t('agents.form.toolsPopup.groupCustom');
      };
      const tools: MultiSelectPopoverItem[] = data.tools.map(
        (tool: UserToolType) => {
          const base: MultiSelectPopoverItem = {
            id: tool.id,
            label: getToolDisplayName(tool),
            icon: `/toolIcons/tool_${tool.name}.svg`,
            group: groupFor(tool),
          };
          if (tool.name === 'remote_device') {
            const deviceId = (tool.config?.device_id as string) || '';
            const meta = devicesById.get(deviceId);
            const online = meta?.online ?? false;
            base.descriptionNode = (
              <span
                className={`mt-0.5 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
                  online
                    ? 'bg-green-100 text-green-900 dark:bg-green-900/30 dark:text-green-300'
                    : 'bg-gray-200 text-gray-700 dark:bg-gray-700/40 dark:text-gray-300'
                }`}
              >
                {online
                  ? t('settings.devices.online')
                  : t('settings.devices.offline')}
              </span>
            );
          }
          return base;
        },
      );
      const groupOrder = [
        t('agents.form.toolsPopup.groupBuiltin'),
        t('agents.form.toolsPopup.groupDefault'),
        t('agents.form.toolsPopup.groupCustom'),
      ];
      tools.sort(
        (a, b) =>
          groupOrder.indexOf(a.group || '') - groupOrder.indexOf(b.group || ''),
      );
      setUserTools(tools);
      setRawUserTools(data.tools as UserToolType[]);
    };
    const getModels = async () => {
      const response = await modelService.getModels(token);
      if (!response.ok) throw new Error('Failed to fetch models');
      const data = await response.json();
      const transformed = modelService.transformModels(data.models || []);
      setAvailableModels(transformed);

      if (mode === 'new' && transformed.length > 0) {
        const preferredDefaultModelId =
          transformed.find((model) => model.id === data.default_model_id)?.id ||
          transformed[0].id;

        if (preferredDefaultModelId) {
          setSelectedModelIds((prevSelectedModelIds) =>
            prevSelectedModelIds.size > 0
              ? prevSelectedModelIds
              : new Set([preferredDefaultModelId]),
          );
        }
      }
    };
    getTools();
    getModels();
  }, [token, mode]);

  // Validate folder_id from URL against user's folders
  useEffect(() => {
    const validateAndSetFolder = async () => {
      if (!folderIdFromUrl) {
        setValidatedFolderId(null);
        return;
      }

      let folders = agentFolders;
      if (!folders) {
        try {
          const response = await userService.getAgentFolders(token);
          if (response.ok) {
            const data = await response.json();
            folders = data.folders || [];
            dispatch(setAgentFolders(folders));
          }
        } catch {
          setValidatedFolderId(null);
          return;
        }
      }

      const folderExists = folders?.some((f) => f.id === folderIdFromUrl);
      setValidatedFolderId(folderExists ? folderIdFromUrl : null);
    };

    validateAndSetFolder();
  }, [folderIdFromUrl, agentFolders, token, dispatch]);

  // Auto-select default source if none selected
  useEffect(() => {
    if (sourceDocs && sourceDocs.length > 0 && selectedSourceIds.size === 0) {
      const defaultSource = sourceDocs.find((s) => s.name === 'Default');
      const fallback = defaultSource || sourceDocs[0];
      setSelectedSourceIds(
        new Set([String(fallback.id || fallback.retriever || fallback.name)]),
      );
    }
  }, [sourceDocs, selectedSourceIds.size]);

  useEffect(() => {
    if ((mode === 'edit' || mode === 'draft') && agentId) {
      const getAgent = async () => {
        const response = await userService.getAgent(agentId, token);
        if (!response.ok) {
          navigate('/agents');
          throw new Error('Failed to fetch agent');
        }
        const data = await response.json();

        if (data.sources && data.sources.length > 0) {
          const mappedSources = data.sources.map((sourceId: string) => {
            if (sourceId === 'default') {
              const defaultSource = sourceDocs?.find(
                (source) => source.name === 'Default',
              );
              return defaultSource?.retriever || 'classic';
            }
            return sourceId;
          });
          setSelectedSourceIds(new Set(mappedSources));
        } else if (data.source) {
          if (data.source === 'default') {
            const defaultSource = sourceDocs?.find(
              (source) => source.name === 'Default',
            );
            setSelectedSourceIds(
              new Set([defaultSource?.retriever || 'classic']),
            );
          } else {
            setSelectedSourceIds(new Set([data.source]));
          }
        } else if (data.retriever) {
          setSelectedSourceIds(new Set([data.retriever]));
        }

        if (data.tool_details) setSelectedTools(data.tool_details);
        if (data.status === 'draft') setEffectiveMode('draft');
        if (data.json_schema) {
          const jsonText = JSON.stringify(data.json_schema, null, 2);
          setJsonSchemaText(jsonText);
          setJsonSchemaValid(true);
        }
        // Backfill required fields so older agents (created before
        // agent_type / prompt_id / models existed) don't fail
        // ``isPublishable()`` and leave Save permanently disabled.
        const normalized = {
          ...data,
          agent_type: data.agent_type || 'classic',
          prompt_id: data.prompt_id || 'default',
          retriever: data.retriever || 'classic',
          chunks: data.chunks || '2',
          tools: data.tools || [],
          sources: data.sources || [],
          models: data.models || [],
          default_model_id: data.default_model_id || '',
        };
        setAgent(normalized);
        initialAgentRef.current = normalized;
      };
      getAgent();
    }
  }, [agentId, mode, token]);

  useEffect(() => {
    if (agent.models && agent.models.length > 0 && availableModels.length > 0) {
      const agentModelIds = new Set(agent.models);
      if (agentModelIds.size > 0 && selectedModelIds.size === 0) {
        setSelectedModelIds(agentModelIds);
      }
    }
  }, [agent.models, availableModels.length]);

  useEffect(() => {
    const modelsArray = Array.from(selectedModelIds);
    if (modelsArray.length > 0) {
      setAgent((prev) => ({
        ...prev,
        models: modelsArray,
        default_model_id: modelsArray.includes(prev.default_model_id || '')
          ? prev.default_model_id
          : modelsArray[0],
      }));
    } else {
      setAgent((prev) => ({
        ...prev,
        models: [],
        default_model_id: '',
      }));
    }
  }, [selectedModelIds]);

  useEffect(() => {
    const selectedSources = Array.from(selectedSourceIds)
      .map((id) =>
        sourceDocs?.find(
          (source) =>
            source.id === id || source.retriever === id || source.name === id,
        ),
      )
      .filter(Boolean);

    if (selectedSources.length > 0) {
      // Handle multiple sources
      if (selectedSources.length > 1) {
        // Multiple sources selected - store in sources array
        const sourceIds = selectedSources
          .map((source) => source?.id)
          .filter((id): id is string => Boolean(id));
        setAgent((prev) => ({
          ...prev,
          sources: sourceIds,
          source: '', // Clear single source for multiple sources
          retriever: '',
        }));
      } else {
        // Single source selected - maintain backward compatibility
        const selectedSource = selectedSources[0];
        if (selectedSource && 'id' in selectedSource) {
          setAgent((prev) => ({
            ...prev,
            source: selectedSource?.id || 'default',
            sources: [], // Clear sources array for single source
            retriever: '',
          }));
        } else {
          setAgent((prev) => ({
            ...prev,
            source: '',
            sources: [], // Clear sources array
            retriever: selectedSource?.retriever || 'classic',
          }));
        }
      }
    } else {
      // No sources selected
      setAgent((prev) => ({
        ...prev,
        source: '',
        sources: [],
        retriever: '',
      }));
    }
  }, [selectedSourceIds]);

  useEffect(() => {
    setAgent((prev) => ({
      ...prev,
      tools: Array.from(selectedTools)
        .map((tool) => tool?.id)
        .filter((id): id is string => typeof id === 'string'),
    }));
  }, [selectedTools]);

  useEffect(() => {
    if (isPublishable()) dispatch(setSelectedAgent(agent));

    if (!modeConfig[effectiveMode].trackChanges) {
      setHasChanges(true);
      return;
    }
    if (!initialAgentRef.current) {
      setHasChanges(false);
      return;
    }

    const initialJsonSchemaText = initialAgentRef.current.json_schema
      ? JSON.stringify(initialAgentRef.current.json_schema, null, 2)
      : '';

    const isChanged =
      !isEqual(agent, initialAgentRef.current) ||
      imageFile !== null ||
      jsonSchemaText !== initialJsonSchemaText;
    setHasChanges(isChanged);
  }, [agent, dispatch, effectiveMode, imageFile, jsonSchemaText]);
  // Only show the agent sub-nav once the agent has an id (i.e. not the bare
  // ``new`` mode). The sub-nav links to Logs/Schedules which require an id.
  const showAgentNav = effectiveMode === 'edit' && Boolean(agent.id);

  return (
    <div className="flex flex-col px-4 pt-4 pb-2 max-[1179px]:min-h-dvh min-[1180px]:h-dvh md:px-12 md:pt-4 md:pb-3">
      {agent.agent_type === 'workflow' && (
        <div className="mt-4 w-full">
          <WorkflowBuilder />
        </div>
      )}
      <div className="flex w-full flex-wrap items-center justify-between gap-2 px-4">
        {showAgentNav ? (
          <AgentPageHeader
            agentId={agent.id}
            agentName={agent.name}
            agentEditPath={`/agents/edit/${agent.id}`}
            currentPage="overview"
          />
        ) : (
          <span aria-hidden />
        )}
        <div className="flex flex-wrap items-center gap-2">
          {hasChanges && (
            <Button
              type="button"
              variant="ghost"
              onClick={handleCancel}
              className="text-primary dark:text-foreground rounded-3xl px-2 hover:bg-transparent"
            >
              {t('agents.form.buttons.cancel')}
            </Button>
          )}
          {modeConfig[effectiveMode].showSaveDraft && (
            <Button
              type="button"
              disabled={isJsonSchemaInvalid()}
              onClick={handleSaveDraft}
              className={`border-primary text-primary hover:bg-primary/90 min-w-28 rounded-3xl border border-solid bg-transparent px-5 whitespace-nowrap hover:text-white ${
                isJsonSchemaInvalid() ? 'disabled:opacity-30' : ''
              }`}
            >
              <span className="flex items-center justify-center transition-all duration-200">
                {draftLoading ? (
                  <Spinner size="small" />
                ) : (
                  t('agents.form.buttons.saveDraft')
                )}
              </span>
            </Button>
          )}
          <Button
            type="button"
            disabled={!isPublishable() || !hasChanges}
            onClick={handlePublish}
            className={`${!isPublishable() || !hasChanges ? 'disabled:opacity-30' : ''} min-w-28 rounded-3xl px-5 whitespace-nowrap text-white`}
          >
            <span className="flex items-center justify-center transition-all duration-200">
              {publishLoading ? (
                <Spinner size="small" />
              ) : (
                modeConfig[effectiveMode].buttonText
              )}
            </span>
          </Button>
          {modeConfig[effectiveMode].showAccessDetails && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t('agents.form.buttons.moreActions')}
                  title={t('agents.form.buttons.moreActions')}
                >
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => setAgentDetails('ACTIVE')}>
                  {t('agents.form.buttons.accessDetails')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>
      <div className="bg-muted dark:bg-background mt-3 flex w-full flex-1 grid-cols-5 flex-col gap-10 rounded-2xl p-5 max-[1179px]:overflow-visible min-[1180px]:grid min-[1180px]:gap-5 min-[1180px]:overflow-hidden">
        <div className="scrollbar-overlay col-span-2 flex flex-col gap-5 max-[1179px]:overflow-visible min-[1180px]:max-h-full min-[1180px]:overflow-y-auto min-[1180px]:pr-3">
          <div className="bg-card rounded-2xl px-6 py-3">
            <h2 className="text-lg font-semibold">
              {t('agents.form.sections.meta')}
            </h2>
            <Input
              className="bg-card mt-3 h-auto rounded-3xl px-5 py-3 text-sm placeholder:text-gray-400 md:text-sm"
              type="text"
              value={agent.name}
              placeholder={t('agents.form.placeholders.agentName')}
              onChange={(e) => setAgent({ ...agent, name: e.target.value })}
            />
            <textarea
              className="border-border text-foreground dark:text-foreground dark:placeholder:text-muted-foreground bg-card dark:border-border focus-visible:ring-ring/50 focus-visible:border-ring mt-3 h-32 w-full rounded-xl border px-5 py-4 text-sm outline-hidden placeholder:text-gray-400 focus-visible:ring-[3px]"
              placeholder={t('agents.form.placeholders.describeAgent')}
              value={agent.description}
              onChange={(e) =>
                setAgent({ ...agent, description: e.target.value })
              }
            />
            <div className="mt-3">
              <FileUpload
                showPreview
                className="bg-card"
                onUpload={handleUpload}
                onRemove={() => setImageFile(null)}
                uploadText={[
                  {
                    text: t('agents.form.upload.clickToUpload'),
                    colorClass: 'text-primary',
                  },
                  {
                    text: t('agents.form.upload.dragAndDrop'),
                    colorClass: 'text-[#525252]',
                  },
                ]}
              />
            </div>
          </div>
          <div className="bg-card rounded-2xl px-6 py-3">
            <h2 className="text-lg font-semibold">
              {t('agents.form.sections.source')}
            </h2>
            <div className="mt-3">
              <div className="flex flex-wrap items-center gap-1">
                <MultiSelectPopover
                  open={isSourcePopupOpen}
                  onOpenChange={setIsSourcePopupOpen}
                  title={t('agents.form.sourcePopup.title')}
                  items={
                    sourceDocs?.map((doc: Doc) => ({
                      id: String(doc.id || doc.retriever || doc.name),
                      label: doc.name,
                      icon: <img src={SourceIcon} alt="" />,
                    })) || []
                  }
                  selectedIds={Array.from(selectedSourceIds)}
                  onToggle={(id) => {
                    const next = new Set(selectedSourceIds);
                    if (next.has(id)) next.delete(id);
                    else next.add(id);
                    if (
                      next.size === 0 &&
                      sourceDocs &&
                      sourceDocs.length > 0
                    ) {
                      const defaultSource = sourceDocs.find(
                        (s) => s.name === 'Default',
                      );
                      const fallback = defaultSource || sourceDocs[0];
                      setSelectedSourceIds(
                        new Set([
                          String(
                            fallback.id || fallback.retriever || fallback.name,
                          ),
                        ]),
                      );
                    } else {
                      setSelectedSourceIds(next);
                    }
                  }}
                  searchPlaceholder={t(
                    'agents.form.sourcePopup.searchPlaceholder',
                  )}
                  emptyMessage={t('agents.form.sourcePopup.noOptionsMessage')}
                  trigger={
                    <Button
                      type="button"
                      variant="outline"
                      ref={sourceAnchorButtonRef}
                      className={`bg-card h-auto w-full justify-start truncate rounded-3xl px-5 py-3 text-left text-sm font-normal ${
                        selectedSourceIds.size > 0
                          ? 'text-foreground dark:text-foreground'
                          : 'dark:text-muted-foreground text-gray-400'
                      }`}
                    >
                      {selectedSourceIds.size > 0
                        ? Array.from(selectedSourceIds)
                            .map((id) => {
                              const matchedDoc = sourceDocs?.find(
                                (source) =>
                                  source.id === id ||
                                  source.name === id ||
                                  source.retriever === id,
                              );
                              return (
                                matchedDoc?.name || t('agents.form.externalKb')
                              );
                            })
                            .filter(Boolean)
                            .join(', ')
                        : t('agents.form.placeholders.selectSources')}
                    </Button>
                  }
                />
              </div>
              <div className="mt-3">
                <Select
                  value={agent.chunks || undefined}
                  onValueChange={(value) =>
                    setAgent({ ...agent, chunks: value })
                  }
                >
                  <SelectTrigger
                    className="w-full rounded-3xl px-5 py-3 text-sm"
                    size="lg"
                  >
                    <SelectValue
                      placeholder={t('agents.form.placeholders.chunksPerQuery')}
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {chunks.map((c) => (
                      <SelectItem key={c} value={c}>
                        {c}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
          <div className="bg-card rounded-2xl px-6 py-3">
            <div className="flex flex-wrap items-end gap-1">
              <div className="min-w-20 grow basis-full sm:basis-0">
                <Prompts
                  prompts={prompts}
                  selectedPrompt={
                    prompts.find((prompt) => prompt.id === agent.prompt_id) ||
                    prompts[0] || {
                      name: 'default',
                      id: 'default',
                      type: 'public',
                    }
                  }
                  onSelectPrompt={(name, id, type) =>
                    setAgent({ ...agent, prompt_id: id })
                  }
                  setPrompts={(newPrompts) => dispatch(setPrompts(newPrompts))}
                  title={t('agents.form.sections.prompt')}
                  titleClassName="text-lg font-semibold"
                  showAddButton={false}
                  dropdownProps={{ className: 'w-full' }}
                />
              </div>
              <Button
                type="button"
                onClick={() => setAddPromptModal('ACTIVE')}
                className="border-primary text-primary hover:bg-primary/90 h-auto min-w-20 shrink-0 basis-full rounded-3xl border border-solid bg-transparent px-5 py-3 whitespace-nowrap hover:text-white sm:basis-auto"
              >
                {t('agents.form.buttons.add')}
              </Button>
            </div>
          </div>
          <div className="bg-card rounded-2xl px-6 py-3">
            <h2 className="text-lg font-semibold">
              {t('agents.form.sections.tools')}
            </h2>
            <div className="mt-3 flex flex-wrap items-center gap-1">
              <MultiSelectPopover
                open={isToolsPopupOpen}
                onOpenChange={setIsToolsPopupOpen}
                title={t('agents.form.toolsPopup.title')}
                items={userTools}
                selectedIds={selectedTools.map((tool) => tool.id)}
                onToggle={(id) => {
                  const exists = selectedTools.find((t) => t.id === id);
                  if (exists) {
                    setSelectedTools(selectedTools.filter((t) => t.id !== id));
                    return;
                  }
                  const item = userTools.find((t) => t.id === id);
                  const raw = rawUserTools.find((t) => t.id === id);
                  if (!item) return;
                  setSelectedTools([
                    ...selectedTools,
                    {
                      id: item.id,
                      name: raw?.name || item.label,
                      display_name: item.label,
                    },
                  ]);
                }}
                searchPlaceholder={t(
                  'agents.form.toolsPopup.searchPlaceholder',
                )}
                emptyMessage={t('agents.form.toolsPopup.noOptionsMessage')}
                trigger={
                  <Button
                    type="button"
                    variant="outline"
                    ref={toolAnchorButtonRef}
                    className={`bg-card h-auto w-full justify-start truncate rounded-3xl px-5 py-3 text-left text-sm font-normal ${
                      selectedTools.length > 0
                        ? 'text-foreground dark:text-foreground'
                        : 'dark:text-muted-foreground text-gray-400'
                    }`}
                  >
                    {selectedTools.length > 0
                      ? selectedTools
                          .map((tool) => getToolDisplayName(tool))
                          .filter(Boolean)
                          .join(', ')
                      : t('agents.form.placeholders.selectTools')}
                  </Button>
                }
              />
            </div>
          </div>
          <div className="bg-card rounded-2xl px-6 py-3">
            <h2 className="text-lg font-semibold">
              {t('agents.form.sections.agentType')}
            </h2>
            <div className="mt-3">
              <Select
                value={agent.agent_type || undefined}
                onValueChange={(value) =>
                  setAgent({ ...agent, agent_type: value })
                }
              >
                <SelectTrigger
                  className="w-full rounded-3xl px-5 py-3 text-sm"
                  size="lg"
                >
                  <SelectValue
                    placeholder={t('agents.form.placeholders.selectType')}
                  />
                </SelectTrigger>
                <SelectContent>
                  {agentTypes.map((type) => (
                    <SelectItem key={type.value} value={type.value}>
                      {type.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="bg-card rounded-2xl px-6 py-3">
            <h2 className="text-lg font-semibold">
              {t('agents.form.sections.models')}
            </h2>
            <div className="mt-3 flex flex-col gap-3">
              <MultiSelectPopover
                open={isModelsPopupOpen}
                onOpenChange={setIsModelsPopupOpen}
                title={t('agents.form.modelsPopup.title')}
                items={(() => {
                  const builtinLabel = t(
                    'settings.customModels.modelsGroup.builtin',
                  );
                  const userLabel = t('settings.customModels.modelsGroup.user');
                  const builtin: MultiSelectPopoverItem[] = [];
                  const user: MultiSelectPopoverItem[] = [];
                  availableModels.forEach((model) => {
                    const opt: MultiSelectPopoverItem = {
                      id: model.id,
                      label: model.display_name,
                      group: model.source === 'user' ? userLabel : builtinLabel,
                    };
                    if (model.source === 'user') user.push(opt);
                    else builtin.push(opt);
                  });
                  return [...builtin, ...user];
                })()}
                selectedIds={Array.from(selectedModelIds)}
                onToggle={(id) => {
                  const next = new Set(selectedModelIds);
                  if (next.has(id)) next.delete(id);
                  else next.add(id);
                  setSelectedModelIds(next);
                }}
                searchPlaceholder={t(
                  'agents.form.modelsPopup.searchPlaceholder',
                )}
                emptyMessage={t('agents.form.modelsPopup.noOptionsMessage')}
                trigger={
                  <Button
                    type="button"
                    variant="outline"
                    ref={modelAnchorButtonRef}
                    className={`bg-card h-auto w-full justify-start truncate rounded-3xl px-5 py-3 text-left text-sm font-normal ${
                      selectedModelIds.size > 0
                        ? 'text-foreground dark:text-foreground'
                        : 'dark:text-muted-foreground text-gray-400'
                    }`}
                  >
                    {selectedModelIds.size > 0
                      ? availableModels
                          .filter((m) => selectedModelIds.has(m.id))
                          .map((m) => m.display_name)
                          .join(', ')
                      : t('agents.form.placeholders.selectModels')}
                  </Button>
                }
              />
              {selectedModelIds.size > 0 && (
                <div>
                  <label className="mb-2 block text-sm font-medium">
                    {t('agents.form.labels.defaultModel')}
                  </label>
                  <Select
                    value={agent.default_model_id || undefined}
                    onValueChange={(value) =>
                      setAgent({ ...agent, default_model_id: value })
                    }
                  >
                    <SelectTrigger
                      className="w-full rounded-3xl px-5 py-3 text-sm"
                      size="lg"
                    >
                      <SelectValue
                        placeholder={t(
                          'agents.form.placeholders.selectDefaultModel',
                        )}
                      />
                    </SelectTrigger>
                    <SelectContent>
                      {availableModels
                        .filter((m) => selectedModelIds.has(m.id))
                        .map((m) => (
                          <SelectItem key={m.id} value={m.id}>
                            {m.display_name}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
          </div>
          <div className="bg-card rounded-2xl px-6 py-3">
            <Button
              type="button"
              variant="ghost"
              onClick={() =>
                setIsAdvancedSectionExpanded(!isAdvancedSectionExpanded)
              }
              className="h-auto w-full justify-between px-0 py-0 text-left hover:bg-transparent"
            >
              <div>
                <h2 className="text-lg font-semibold">
                  {t('agents.form.sections.advanced')}
                </h2>
              </div>
              <div className="ml-4 flex items-center">
                <svg
                  className={`size-5 transform transition-transform duration-200 ${
                    isAdvancedSectionExpanded ? 'rotate-180' : ''
                  }`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M19 9l-7 7-7-7"
                  />
                </svg>
              </div>
            </Button>
            {isAdvancedSectionExpanded && (
              <div className="mt-3">
                <div>
                  <h2 className="text-sm font-medium">
                    {t('agents.form.advanced.jsonSchema')}
                  </h2>
                  <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
                    {t('agents.form.advanced.jsonSchemaDescription')}
                  </p>
                </div>
                <textarea
                  value={jsonSchemaText}
                  onChange={(e) => validateAndSetJsonSchema(e.target.value)}
                  placeholder={`{
  "type": "object",
  "properties": {
    "name": {"type": "string"},
    "email": {"type": "string"}
  },
  "required": ["name", "email"],
  "additionalProperties": false
}`}
                  rows={9}
                  className={`border-border text-foreground dark:text-foreground bg-card dark:border-border focus-visible:ring-ring/50 focus-visible:border-ring mt-2 w-full rounded-2xl border px-4 py-3 font-mono text-sm outline-hidden focus-visible:ring-[3px]`}
                />
                {jsonSchemaText.trim() !== '' && (
                  <div
                    className={`mt-2 flex items-center gap-2 text-sm ${
                      jsonSchemaValid
                        ? 'text-green-600 dark:text-green-400'
                        : 'text-red-600 dark:text-red-400'
                    }`}
                  >
                    <span
                      className={`h-4 w-4 bg-contain bg-center bg-no-repeat ${
                        jsonSchemaValid
                          ? "bg-[url('/src/assets/circle-check.svg')]"
                          : "bg-[url('/src/assets/circle-x.svg')]"
                      }`}
                    />
                    {jsonSchemaValid
                      ? t('agents.form.advanced.validJson')
                      : t('agents.form.advanced.invalidJson')}
                  </div>
                )}

                <div className="mt-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <h2 className="text-sm font-medium">
                        {t('agents.form.advanced.tokenLimiting')}
                      </h2>
                      <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
                        {t('agents.form.advanced.tokenLimitingDescription')}
                      </p>
                    </div>
                    <Switch
                      checked={agent.limited_token_mode}
                      onCheckedChange={(checked) => {
                        setAgent({
                          ...agent,
                          limited_token_mode: checked,
                          limited_request_mode: checked
                            ? false
                            : agent.limited_request_mode,
                        });
                      }}
                    />
                  </div>
                  <Input
                    type="number"
                    min="0"
                    value={agent.token_limit || ''}
                    onChange={(e) =>
                      setAgent({
                        ...agent,
                        token_limit: e.target.value
                          ? parseInt(e.target.value)
                          : undefined,
                      })
                    }
                    disabled={!agent.limited_token_mode}
                    placeholder={t('agents.form.placeholders.enterTokenLimit')}
                    className={`bg-card mt-2 h-auto rounded-3xl px-5 py-3 text-sm placeholder:text-gray-400 md:text-sm ${
                      !agent.limited_token_mode
                        ? 'cursor-not-allowed opacity-50'
                        : ''
                    }`}
                  />
                </div>

                <div className="mt-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <h2 className="text-sm font-medium">
                        {t('agents.form.advanced.requestLimiting')}
                      </h2>
                      <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
                        {t('agents.form.advanced.requestLimitingDescription')}
                      </p>
                    </div>
                    <Switch
                      checked={agent.limited_request_mode}
                      onCheckedChange={(checked) => {
                        setAgent({
                          ...agent,
                          limited_request_mode: checked,
                          limited_token_mode: checked
                            ? false
                            : agent.limited_token_mode,
                        });
                      }}
                    />
                  </div>
                  <Input
                    type="number"
                    min="0"
                    value={agent.request_limit || ''}
                    onChange={(e) =>
                      setAgent({
                        ...agent,
                        request_limit: e.target.value
                          ? parseInt(e.target.value)
                          : undefined,
                      })
                    }
                    disabled={!agent.limited_request_mode}
                    placeholder={t(
                      'agents.form.placeholders.enterRequestLimit',
                    )}
                    className={`bg-card mt-2 h-auto rounded-3xl px-5 py-3 text-sm placeholder:text-gray-400 md:text-sm ${
                      !agent.limited_request_mode
                        ? 'cursor-not-allowed opacity-50'
                        : ''
                    }`}
                  />
                </div>

                <div className="mt-6">
                  <div className="flex items-center justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <h2 className="text-sm font-medium">
                        {t('agents.form.advanced.systemPromptOverride')}
                      </h2>
                      <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
                        {t(
                          'agents.form.advanced.systemPromptOverrideDescription',
                        )}
                      </p>
                    </div>
                    <Switch
                      className="shrink-0"
                      checked={agent.allow_system_prompt_override}
                      onCheckedChange={(checked) =>
                        setAgent({
                          ...agent,
                          allow_system_prompt_override: checked,
                        })
                      }
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
          {modeConfig[effectiveMode].showDelete && agent.id && (
            <div className="border-destructive/40 bg-destructive/5 rounded-2xl border px-6 py-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <h2 className="text-destructive text-lg font-semibold">
                    {t('agents.form.dangerZone.heading')}
                  </h2>
                  <p className="text-muted-foreground mt-1 text-xs">
                    {t('agents.form.dangerZone.description')}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="destructive-outline"
                  size="sm"
                  onClick={() => setDeleteConfirmation('ACTIVE')}
                  className="shrink-0"
                >
                  {t('agents.form.dangerZone.deleteButton')}
                </Button>
              </div>
            </div>
          )}
        </div>
        <div className="col-span-3 flex flex-col gap-2 max-[1179px]:h-auto max-[1179px]:px-0 max-[1179px]:py-0 min-[1180px]:h-full min-[1180px]:py-2">
          <div className="flex-1 max-[1179px]:overflow-visible min-[1180px]:min-h-0 min-[1180px]:overflow-hidden">
            <AgentPreviewArea />
          </div>
        </div>
      </div>
      <ConfirmationModal
        message={t('agents.deleteConfirmation')}
        modalState={deleteConfirmation}
        setModalState={setDeleteConfirmation}
        submitLabel={t('agents.form.buttons.delete')}
        handleSubmit={() => {
          handleDelete(agent.id || '');
          setDeleteConfirmation('INACTIVE');
        }}
        cancelLabel={t('agents.form.buttons.cancel')}
        variant="danger"
      />
      <AgentDetailsModal
        agent={agent}
        mode={effectiveMode}
        modalState={agentDetails}
        setModalState={setAgentDetails}
      />
      <AddPromptModal
        prompts={prompts}
        isOpen={addPromptModal}
        onClose={() => setAddPromptModal('INACTIVE')}
        onSelect={(name: string, id: string, type: string) => {
          setAgent({ ...agent, prompt_id: id });
        }}
      />
    </div>
  );
}

function AgentPreviewArea() {
  const { t } = useTranslation();
  const selectedAgent = useSelector(selectSelectedAgent);
  return (
    <div className="bg-card border-border w-full rounded-2xl border max-[1179px]:h-[600px] min-[1180px]:h-full">
      {selectedAgent?.status === 'published' ? (
        <div className="flex h-full w-full flex-col overflow-hidden rounded-2xl">
          <AgentPreview />
        </div>
      ) : (
        <div className="flex h-full w-full flex-col items-center justify-center gap-2">
          <span className="block h-12 w-12 bg-[url('/src/assets/science-spark.svg')] bg-contain bg-center bg-no-repeat transition-all dark:bg-[url('/src/assets/science-spark-dark.svg')]" />{' '}
          <p className="text-muted-foreground text-xs">
            {t('agents.form.preview.publishedPreview')}
          </p>
        </div>
      )}
    </div>
  );
}

function AddPromptModal({
  prompts,
  isOpen,
  onClose,
  onSelect,
}: {
  prompts: Prompt[];
  isOpen: ActiveState;
  onClose: () => void;
  onSelect?: (name: string, id: string, type: string) => void;
}) {
  const dispatch = useDispatch();
  const token = useSelector(selectToken);

  const [newPromptName, setNewPromptName] = useState('');
  const [newPromptContent, setNewPromptContent] = useState('');

  const handleAddPrompt = async () => {
    try {
      const response = await userService.createPrompt(
        {
          name: newPromptName,
          content: newPromptContent,
        },
        token,
      );
      if (!response.ok) {
        throw new Error('Failed to add prompt');
      }
      const newPrompt = await response.json();
      // Update Redux store with new prompt
      dispatch(
        setPrompts([
          ...prompts,
          { name: newPromptName, id: newPrompt.id, type: 'private' },
        ]),
      );
      onClose();
      setNewPromptName('');
      setNewPromptContent('');
      onSelect?.(newPromptName, newPrompt.id, newPromptContent);
    } catch (error) {
      console.error('Error adding prompt:', error);
    }
  };
  return (
    <PromptsModal
      modalState={isOpen}
      setModalState={onClose}
      type="ADD"
      existingPrompts={prompts}
      newPromptName={newPromptName}
      setNewPromptName={setNewPromptName}
      newPromptContent={newPromptContent}
      setNewPromptContent={setNewPromptContent}
      editPromptName={''}
      setEditPromptName={() => undefined}
      editPromptContent={''}
      setEditPromptContent={() => undefined}
      currentPromptEdit={{ id: '', name: '', type: '' }}
      handleAddPrompt={handleAddPrompt}
    />
  );
}
