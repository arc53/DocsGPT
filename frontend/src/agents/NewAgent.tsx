import isEqual from 'lodash/isEqual';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import modelService from '../api/services/modelService';
import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import SourceIcon from '../assets/source.svg';
import Dropdown from '../components/Dropdown';
import { FileUpload } from '../components/FileUpload';
import MultiSelectPopup, { OptionType } from '../components/MultiSelectPopup';
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
    models: [],
    default_model_id: '',
  });
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [userTools, setUserTools] = useState<OptionType[]>([]);
  const [availableModels, setAvailableModels] = useState<Model[]>([]);
  const [isSourcePopupOpen, setIsSourcePopupOpen] = useState(false);
  const [isToolsPopupOpen, setIsToolsPopupOpen] = useState(false);
  const [isModelsPopupOpen, setIsModelsPopupOpen] = useState(false);
  const [selectedSourceIds, setSelectedSourceIds] = useState<
    Set<string | number>
  >(new Set());
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
      showLogs: false,
      showAccessDetails: false,
      trackChanges: false,
    },
    edit: {
      heading: t('agents.form.headings.edit'),
      buttonText: t('agents.form.buttons.save'),
      showDelete: true,
      showSaveDraft: false,
      showLogs: true,
      showAccessDetails: true,
      trackChanges: true,
    },
    draft: {
      heading: t('agents.form.headings.draft'),
      buttonText: t('agents.form.buttons.publish'),
      showDelete: true,
      showSaveDraft: true,
      showLogs: false,
      showAccessDetails: false,
      trackChanges: false,
    },
  };
  const chunks = ['0', '2', '4', '6', '8', '10'];
  const agentTypes = [
    { label: t('agents.form.agentTypes.classic'), value: 'classic' },
    { label: t('agents.form.agentTypes.react'), value: 'react' },
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
      const response = await userService.getUserTools(token);
      if (!response.ok) throw new Error('Failed to fetch tools');
      const data = await response.json();
      const tools: OptionType[] = data.tools.map((tool: UserToolType) => ({
        id: tool.id,
        label: tool.customName ? tool.customName : tool.displayName,
        icon: `/toolIcons/tool_${tool.name}.svg`,
      }));
      setUserTools(tools);
    };
    const getModels = async () => {
      const response = await modelService.getModels(null);
      if (!response.ok) throw new Error('Failed to fetch models');
      const data = await response.json();
      const transformed = modelService.transformModels(data.models || []);
      setAvailableModels(transformed);
    };
    getTools();
    getModels();
  }, [token]);

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
      if (defaultSource) {
        setSelectedSourceIds(
          new Set([
            defaultSource.id || defaultSource.retriever || defaultSource.name,
          ]),
        );
      } else {
        setSelectedSourceIds(
          new Set([
            sourceDocs[0].id || sourceDocs[0].retriever || sourceDocs[0].name,
          ]),
        );
      }
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
        setAgent(data);
        initialAgentRef.current = data;
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
  return (
    <div className="flex flex-col px-4 pt-4 pb-2 max-[1179px]:min-h-dvh min-[1180px]:h-dvh md:px-12 md:pt-12 md:pb-3">
      <div className="flex items-center gap-3 px-4">
        <button
          className="rounded-full border p-3 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
          onClick={handleCancel}
        >
          <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
        </button>
        <p className="text-eerie-black dark:text-bright-gray mt-px text-sm font-semibold">
          {t('agents.backToAll')}
        </p>
      </div>
      <div className="mt-5 flex w-full flex-wrap items-center justify-between gap-2 px-4">
        <h1 className="text-eerie-black m-0 text-[32px] font-bold lg:text-[40px] dark:text-white">
          {modeConfig[effectiveMode].heading}
        </h1>
        {agent.agent_type === 'workflow' && (
          <div className="mt-4 w-full">
            <WorkflowBuilder />
          </div>
        )}
        <div className="flex flex-wrap items-center gap-1">
          <button
            className="text-purple-30 dark:text-light-gray mr-4 rounded-3xl py-2 text-sm font-medium dark:bg-transparent"
            onClick={handleCancel}
          >
            {t('agents.form.buttons.cancel')}
          </button>
          {modeConfig[effectiveMode].showDelete && agent.id && (
            <button
              className="group border-red-2000 text-red-2000 hover:bg-red-2000 flex items-center gap-2 rounded-3xl border border-solid px-5 py-2 text-sm font-medium transition-colors hover:text-white"
              onClick={() => setDeleteConfirmation('ACTIVE')}
            >
              <span className="block h-4 w-4 bg-[url('/src/assets/red-trash.svg')] bg-contain bg-center bg-no-repeat transition-all group-hover:bg-[url('/src/assets/white-trash.svg')]" />
              {t('agents.form.buttons.delete')}
            </button>
          )}
          {modeConfig[effectiveMode].showSaveDraft && (
            <button
              disabled={isJsonSchemaInvalid()}
              className={`border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue w-28 rounded-3xl border border-solid py-2 text-sm font-medium transition-colors hover:text-white ${
                isJsonSchemaInvalid() ? 'cursor-not-allowed opacity-30' : ''
              }`}
              onClick={handleSaveDraft}
            >
              <span className="flex items-center justify-center transition-all duration-200">
                {draftLoading ? (
                  <Spinner size="small" color="#976af3" />
                ) : (
                  t('agents.form.buttons.saveDraft')
                )}
              </span>
            </button>
          )}
          {modeConfig[effectiveMode].showAccessDetails && (
            <button
              className="group border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue flex items-center gap-2 rounded-3xl border border-solid px-5 py-2 text-sm font-medium transition-colors hover:text-white"
              onClick={() => navigate(`/agents/logs/${agent.id}`)}
            >
              <span className="block h-5 w-5 bg-[url('/src/assets/monitoring-purple.svg')] bg-contain bg-center bg-no-repeat transition-all group-hover:bg-[url('/src/assets/monitoring-white.svg')]" />
              {t('agents.form.buttons.logs')}
            </button>
          )}
          {modeConfig[effectiveMode].showAccessDetails && (
            <button
              className="hover:bg-vi</button>olets-are-blue border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue rounded-3xl border border-solid px-5 py-2 text-sm font-medium transition-colors hover:text-white"
              onClick={() => setAgentDetails('ACTIVE')}
            >
              {t('agents.form.buttons.accessDetails')}
            </button>
          )}
          <button
            disabled={!isPublishable() || !hasChanges}
            className={`${!isPublishable() || !hasChanges ? 'cursor-not-allowed opacity-30' : ''} bg-purple-30 hover:bg-violets-are-blue flex w-28 items-center justify-center rounded-3xl py-2 text-sm font-medium text-white`}
            onClick={handlePublish}
          >
            <span className="flex items-center justify-center transition-all duration-200">
              {publishLoading ? (
                <Spinner size="small" color="white" />
              ) : (
                modeConfig[effectiveMode].buttonText
              )}
            </span>
          </button>
        </div>
      </div>
      <div className="mt-3 flex w-full flex-1 grid-cols-5 flex-col gap-10 rounded-[30px] bg-[#F6F6F6] p-5 max-[1179px]:overflow-visible min-[1180px]:grid min-[1180px]:gap-5 min-[1180px]:overflow-hidden dark:bg-[#383838]">
        <div className="scrollbar-overlay col-span-2 flex flex-col gap-5 max-[1179px]:overflow-visible min-[1180px]:max-h-full min-[1180px]:overflow-y-auto min-[1180px]:pr-3">
          <div className="dark:bg-raisin-black rounded-[30px] bg-white px-6 py-3 dark:text-[#E0E0E0]">
            <h2 className="text-lg font-semibold">
              {t('agents.form.sections.meta')}
            </h2>
            <input
              className="border-silver text-jet dark:bg-raisin-black dark:text-bright-gray dark:placeholder:text-silver mt-3 w-full rounded-3xl border bg-white px-5 py-3 text-sm outline-hidden placeholder:text-gray-400 dark:border-[#7E7E7E]"
              type="text"
              value={agent.name}
              placeholder={t('agents.form.placeholders.agentName')}
              onChange={(e) => setAgent({ ...agent, name: e.target.value })}
            />
            <textarea
              className="border-silver text-jet dark:bg-raisin-black dark:text-bright-gray dark:placeholder:text-silver mt-3 h-32 w-full rounded-xl border bg-white px-5 py-4 text-sm outline-hidden placeholder:text-gray-400 dark:border-[#7E7E7E]"
              placeholder={t('agents.form.placeholders.describeAgent')}
              value={agent.description}
              onChange={(e) =>
                setAgent({ ...agent, description: e.target.value })
              }
            />
            <div className="mt-3">
              <FileUpload
                showPreview
                className="dark:bg-raisin-black"
                onUpload={handleUpload}
                onRemove={() => setImageFile(null)}
                uploadText={[
                  {
                    text: t('agents.form.upload.clickToUpload'),
                    colorClass: 'text-[#7D54D1]',
                  },
                  {
                    text: t('agents.form.upload.dragAndDrop'),
                    colorClass: 'text-[#525252]',
                  },
                ]}
              />
            </div>
          </div>
          <div className="dark:bg-raisin-black rounded-[30px] bg-white px-6 py-3 dark:text-[#E0E0E0]">
            <h2 className="text-lg font-semibold">
              {t('agents.form.sections.source')}
            </h2>
            <div className="mt-3">
              <div className="flex flex-wrap items-center gap-1">
                <button
                  ref={sourceAnchorButtonRef}
                  onClick={() => setIsSourcePopupOpen(!isSourcePopupOpen)}
                  className={`border-silver dark:bg-raisin-black w-full truncate rounded-3xl border bg-white px-5 py-3 text-left text-sm dark:border-[#7E7E7E] ${
                    selectedSourceIds.size > 0
                      ? 'text-jet dark:text-bright-gray'
                      : 'dark:text-silver text-gray-400'
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
                </button>
                <MultiSelectPopup
                  isOpen={isSourcePopupOpen}
                  onClose={() => setIsSourcePopupOpen(false)}
                  anchorRef={sourceAnchorButtonRef}
                  options={
                    sourceDocs?.map((doc: Doc) => ({
                      id: doc.id || doc.retriever || doc.name,
                      label: doc.name,
                      icon: <img src={SourceIcon} alt="" />,
                    })) || []
                  }
                  selectedIds={selectedSourceIds}
                  onSelectionChange={(newSelectedIds: Set<string | number>) => {
                    if (
                      newSelectedIds.size === 0 &&
                      sourceDocs &&
                      sourceDocs.length > 0
                    ) {
                      const defaultSource = sourceDocs.find(
                        (s) => s.name === 'Default',
                      );
                      if (defaultSource) {
                        setSelectedSourceIds(
                          new Set([
                            defaultSource.id ||
                              defaultSource.retriever ||
                              defaultSource.name,
                          ]),
                        );
                      } else {
                        setSelectedSourceIds(
                          new Set([
                            sourceDocs[0].id ||
                              sourceDocs[0].retriever ||
                              sourceDocs[0].name,
                          ]),
                        );
                      }
                    } else {
                      setSelectedSourceIds(newSelectedIds);
                    }
                  }}
                  title={t('agents.form.sourcePopup.title')}
                  searchPlaceholder={t(
                    'agents.form.sourcePopup.searchPlaceholder',
                  )}
                  noOptionsMessage={t(
                    'agents.form.sourcePopup.noOptionsMessage',
                  )}
                />
              </div>
              <div className="mt-3">
                <Dropdown
                  options={chunks}
                  selectedValue={agent.chunks ? agent.chunks : null}
                  onSelect={(value: string) =>
                    setAgent({ ...agent, chunks: value })
                  }
                  size="w-full"
                  rounded="3xl"
                  border="border"
                  buttonClassName="bg-white dark:bg-[#222327] border-silver dark:border-[#7E7E7E]"
                  optionsClassName="bg-white dark:bg-[#383838] border-silver dark:border-[#7E7E7E]"
                  placeholder={t('agents.form.placeholders.chunksPerQuery')}
                  placeholderClassName="text-gray-400 dark:text-silver"
                  contentSize="text-sm"
                />
              </div>
            </div>
          </div>
          <div className="dark:bg-raisin-black rounded-[30px] bg-white px-6 py-3 dark:text-[#E0E0E0]">
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
                  titleClassName="text-lg font-semibold dark:text-[#E0E0E0]"
                  showAddButton={false}
                  dropdownProps={{
                    size: 'w-full',
                    rounded: '3xl',
                    border: 'border',
                    buttonClassName:
                      'bg-white dark:bg-[#222327] border-silver dark:border-[#7E7E7E]',
                    optionsClassName:
                      'bg-white dark:bg-[#383838] border-silver dark:border-[#7E7E7E]',
                    placeholderClassName: 'text-gray-400 dark:text-silver',
                    contentSize: 'text-sm',
                  }}
                />
              </div>
              <button
                className="border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue w-20 shrink-0 basis-full rounded-3xl border-2 border-solid px-5 py-[11px] text-sm transition-colors hover:text-white sm:basis-auto"
                onClick={() => setAddPromptModal('ACTIVE')}
              >
                {t('agents.form.buttons.add')}
              </button>
            </div>
          </div>
          <div className="dark:bg-raisin-black rounded-[30px] bg-white px-6 py-3 dark:text-[#E0E0E0]">
            <h2 className="text-lg font-semibold">
              {t('agents.form.sections.tools')}
            </h2>
            <div className="mt-3 flex flex-wrap items-center gap-1">
              <button
                ref={toolAnchorButtonRef}
                onClick={() => setIsToolsPopupOpen(!isToolsPopupOpen)}
                className={`border-silver dark:bg-raisin-black w-full truncate rounded-3xl border bg-white px-5 py-3 text-left text-sm dark:border-[#7E7E7E] ${
                  selectedTools.length > 0
                    ? 'text-jet dark:text-bright-gray'
                    : 'dark:text-silver text-gray-400'
                }`}
              >
                {selectedTools.length > 0
                  ? selectedTools
                      .map((tool) => tool.display_name || tool.name)
                      .filter(Boolean)
                      .join(', ')
                  : t('agents.form.placeholders.selectTools')}
              </button>
              <MultiSelectPopup
                isOpen={isToolsPopupOpen}
                onClose={() => setIsToolsPopupOpen(false)}
                anchorRef={toolAnchorButtonRef}
                options={userTools}
                selectedIds={new Set(selectedTools.map((tool) => tool.id))}
                onSelectionChange={(newSelectedIds: Set<string | number>) =>
                  setSelectedTools(
                    userTools
                      .filter((tool) => newSelectedIds.has(tool.id))
                      .map((tool) => ({
                        id: String(tool.id),
                        name: tool.label,
                        display_name: tool.label,
                      })),
                  )
                }
                title={t('agents.form.toolsPopup.title')}
                searchPlaceholder={t(
                  'agents.form.toolsPopup.searchPlaceholder',
                )}
                noOptionsMessage={t('agents.form.toolsPopup.noOptionsMessage')}
              />
            </div>
          </div>
          <div className="dark:bg-raisin-black rounded-[30px] bg-white px-6 py-3 dark:text-[#E0E0E0]">
            <h2 className="text-lg font-semibold">
              {t('agents.form.sections.agentType')}
            </h2>
            <div className="mt-3">
              <Dropdown
                options={agentTypes}
                selectedValue={
                  agent.agent_type
                    ? agentTypes.find((type) => type.value === agent.agent_type)
                        ?.label || null
                    : null
                }
                onSelect={(option: { label: string; value: string }) =>
                  setAgent({ ...agent, agent_type: option.value })
                }
                size="w-full"
                rounded="3xl"
                border="border"
                buttonClassName="bg-white dark:bg-[#222327] border-silver dark:border-[#7E7E7E]"
                optionsClassName="bg-white dark:bg-[#383838] border-silver dark:border-[#7E7E7E]"
                placeholder={t('agents.form.placeholders.selectType')}
                placeholderClassName="text-gray-400 dark:text-silver"
                contentSize="text-sm"
              />
            </div>
          </div>
          <div className="dark:bg-raisin-black rounded-[30px] bg-white px-6 py-3 dark:text-[#E0E0E0]">
            <h2 className="text-lg font-semibold">
              {t('agents.form.sections.models')}
            </h2>
            <div className="mt-3 flex flex-col gap-3">
              <button
                ref={modelAnchorButtonRef}
                onClick={() => setIsModelsPopupOpen(!isModelsPopupOpen)}
                className={`border-silver dark:bg-raisin-black w-full truncate rounded-3xl border bg-white px-5 py-3 text-left text-sm dark:border-[#7E7E7E] ${
                  selectedModelIds.size > 0
                    ? 'text-jet dark:text-bright-gray'
                    : 'dark:text-silver text-gray-400'
                }`}
              >
                {selectedModelIds.size > 0
                  ? availableModels
                      .filter((m) => selectedModelIds.has(m.id))
                      .map((m) => m.display_name)
                      .join(', ')
                  : t('agents.form.placeholders.selectModels')}
              </button>
              <MultiSelectPopup
                isOpen={isModelsPopupOpen}
                onClose={() => setIsModelsPopupOpen(false)}
                anchorRef={modelAnchorButtonRef}
                options={availableModels.map((model) => ({
                  id: model.id,
                  label: model.display_name,
                }))}
                selectedIds={selectedModelIds}
                onSelectionChange={(newSelectedIds: Set<string | number>) =>
                  setSelectedModelIds(
                    new Set(Array.from(newSelectedIds).map(String)),
                  )
                }
                title={t('agents.form.modelsPopup.title')}
                searchPlaceholder={t(
                  'agents.form.modelsPopup.searchPlaceholder',
                )}
                noOptionsMessage={t('agents.form.modelsPopup.noOptionsMessage')}
              />
              {selectedModelIds.size > 0 && (
                <div>
                  <label className="mb-2 block text-sm font-medium">
                    {t('agents.form.labels.defaultModel')}
                  </label>
                  <Dropdown
                    options={availableModels
                      .filter((m) => selectedModelIds.has(m.id))
                      .map((m) => ({
                        label: m.display_name,
                        value: m.id,
                      }))}
                    selectedValue={
                      availableModels.find(
                        (m) => m.id === agent.default_model_id,
                      )?.display_name || null
                    }
                    onSelect={(option: { label: string; value: string }) =>
                      setAgent({ ...agent, default_model_id: option.value })
                    }
                    size="w-full"
                    rounded="3xl"
                    border="border"
                    buttonClassName="bg-white dark:bg-[#222327] border-silver dark:border-[#7E7E7E]"
                    optionsClassName="bg-white dark:bg-[#383838] border-silver dark:border-[#7E7E7E]"
                    placeholder={t(
                      'agents.form.placeholders.selectDefaultModel',
                    )}
                    placeholderClassName="text-gray-400 dark:text-silver"
                    contentSize="text-sm"
                  />
                </div>
              )}
            </div>
          </div>
          <div className="dark:bg-raisin-black rounded-[30px] bg-white px-6 py-3 dark:text-[#E0E0E0]">
            <button
              onClick={() =>
                setIsAdvancedSectionExpanded(!isAdvancedSectionExpanded)
              }
              className="flex w-full items-center justify-between text-left focus:outline-none"
            >
              <div>
                <h2 className="text-lg font-semibold">
                  {t('agents.form.sections.advanced')}
                </h2>
              </div>
              <div className="ml-4 flex items-center">
                <svg
                  className={`h-5 w-5 transform transition-transform duration-200 ${
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
            </button>
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
                  className={`border-silver text-jet dark:bg-raisin-black dark:text-bright-gray mt-2 w-full rounded-2xl border bg-white px-4 py-3 font-mono text-sm outline-hidden dark:border-[#7E7E7E]`}
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
                    <button
                      onClick={() => {
                        const newTokenMode = !agent.limited_token_mode;
                        setAgent({
                          ...agent,
                          limited_token_mode: newTokenMode,
                          limited_request_mode: newTokenMode
                            ? false
                            : agent.limited_request_mode,
                        });
                      }}
                      className={`relative h-6 w-11 rounded-full transition-colors ${
                        agent.limited_token_mode
                          ? 'bg-purple-30'
                          : 'bg-gray-300 dark:bg-gray-600'
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 h-5 w-5 transform rounded-full bg-white transition-transform ${
                          agent.limited_token_mode ? '' : '-translate-x-5'
                        }`}
                      />
                    </button>
                  </div>
                  <input
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
                    className={`border-silver text-jet dark:bg-raisin-black dark:text-bright-gray dark:placeholder:text-silver mt-2 w-full rounded-3xl border bg-white px-5 py-3 text-sm outline-hidden placeholder:text-gray-400 dark:border-[#7E7E7E] ${
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
                    <button
                      onClick={() => {
                        const newRequestMode = !agent.limited_request_mode;
                        setAgent({
                          ...agent,
                          limited_request_mode: newRequestMode,
                          limited_token_mode: newRequestMode
                            ? false
                            : agent.limited_token_mode,
                        });
                      }}
                      className={`relative h-6 w-11 rounded-full transition-colors ${
                        agent.limited_request_mode
                          ? 'bg-purple-30'
                          : 'bg-gray-300 dark:bg-gray-600'
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 h-5 w-5 transform rounded-full bg-white transition-transform ${
                          agent.limited_request_mode ? '' : '-translate-x-5'
                        }`}
                      />
                    </button>
                  </div>
                  <input
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
                    className={`border-silver text-jet dark:bg-raisin-black dark:text-bright-gray dark:placeholder:text-silver mt-2 w-full rounded-3xl border bg-white px-5 py-3 text-sm outline-hidden placeholder:text-gray-400 dark:border-[#7E7E7E] ${
                      !agent.limited_request_mode
                        ? 'cursor-not-allowed opacity-50'
                        : ''
                    }`}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="col-span-3 flex flex-col gap-2 max-[1179px]:h-auto max-[1179px]:px-0 max-[1179px]:py-0 min-[1180px]:h-full min-[1180px]:py-2 dark:text-[#E0E0E0]">
          <h2 className="text-lg font-semibold">
            {t('agents.form.sections.preview')}
          </h2>
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
    <div className="dark:bg-raisin-black w-full rounded-[30px] border border-[#F6F6F6] bg-white max-[1179px]:h-[600px] min-[1180px]:h-full dark:border-[#7E7E7E]">
      {selectedAgent?.status === 'published' ? (
        <div className="flex h-full w-full flex-col overflow-hidden rounded-[30px]">
          <AgentPreview />
        </div>
      ) : (
        <div className="flex h-full w-full flex-col items-center justify-center gap-2">
          <span className="block h-12 w-12 bg-[url('/src/assets/science-spark.svg')] bg-contain bg-center bg-no-repeat transition-all dark:bg-[url('/src/assets/science-spark-dark.svg')]" />{' '}
          <p className="dark:text-gray-4000 text-xs text-[#18181B]">
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
