import isEqual from 'lodash/isEqual';
import {
  ChevronRight,
  CircleCheck,
  CircleX,
  Database,
  Info,
  Play,
  SquarePen,
} from 'lucide-react';
import React, {
  useCallback,
  useEffect,
  useMemo,
  useId,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ActionMenu } from '@/components/ui/dropdown-menu';
import { EmptyState } from '@/components/ui/empty-state';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { SectionHeader } from '@/components/ui/section-header';
import { SettingRow, SettingRows } from '@/components/ui/setting-row';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

import devicesService from '../api/services/devicesService';
import modelService from '../api/services/modelService';
import userService from '../api/services/userService';
import { FileUpload } from '../components/FileUpload';
import {
  MultiSelectPopover,
  type MultiSelectPopoverItem,
} from '../components/MultiSelectPopover';
import SourcesPopoverFooter from '../components/SourcesPopoverFooter';
import ToolIcon from '../components/ToolIcon';
import connectorsService from '../api/services/connectorsService';
import ConnectorIcon from '../connectors/ConnectorIcon';
import { connectionNeedsSignIn } from '../connectors/connectorsSlice';
import SignInAgainNotice, {
  useSignInAgain,
} from '../connectors/SignInAgainNotice';
import { toolServiceOf } from '../connectors/toolService';
import type { Connection, ConnectorDefinition } from '../connectors/types';
import AgentDetailsModal from '../modals/AgentDetailsModal';
import ShareToTeamModal from '../teams/ShareToTeamModal';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState, Prompt } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
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
import { can } from '../utils/accessUtils';
import Upload from '../upload/Upload';
import {
  selectedSourceIdsFromAgent,
  serializeAgentSources,
  sourceItemId,
  toSourcePickerItems,
} from '../utils/sourceUtils';
import {
  getToolDisplayName,
  isAgentPickerToolVisible,
} from '../utils/toolUtils';
import { agentsListPath } from './paths';
import GuardrailsSection, {
  guardrailsIncomplete,
} from './components/GuardrailsSection';
import AgentPreview from './AgentPreview';
import { resetPreview, selectPreviewStatus } from './agentPreviewSlice';
import AgentPageToolbar, { LastUsedMeta } from './components/AgentPageToolbar';
import AgentPreviewSheet from './components/AgentPreviewSheet';
import SectionShell from '../navigation/SectionShell';
import SponsorConfirmModal from './components/SponsorConfirmModal';
import SponsoredResourcesNotice from './components/SponsoredResourcesNotice';
import {
  readSponsorRefusal,
  type SponsorConfirmation,
  sponsorNotAllowedMessage,
  withAttachedToolRows,
} from './sponsorConsent';
import { Agent, ResourceSponsor, ToolSummary } from './types';
import WorkflowBuilder from './workflow/WorkflowBuilder';

import type { Model } from '../models/types';

/**
 * Pull the backend's own explanation out of a failed response.
 *
 * The agent write endpoints answer a rejected save with
 * `{"success": false, "message": "<why>"}` — e.g. "Invalid chunks value: …"
 * or "Field 'description' cannot be empty". Callers used to test only
 * `response.ok` and throw a fixed string, so the one piece of information
 * that could tell the user what to change was dropped on the floor.
 */
const extractApiError = async (
  response: Response,
  fallback: string,
): Promise<string> => {
  try {
    const body = await response.json();
    if (typeof body?.message === 'string' && body.message.trim())
      return body.message;
  } catch {
    // Non-JSON body (proxy HTML error page, empty 502) — use the fallback.
  }
  return fallback;
};

export default function NewAgent({ mode }: { mode: 'new' | 'edit' | 'draft' }) {
  const { t, i18n } = useTranslation();
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
    chunks: '6',
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
  // Connections behind the picker's tools that need signing in again.
  const [brokenToolConnections, setBrokenToolConnections] = useState<
    { connection: Connection; mcpToolId?: string }[]
  >([]);
  const [toolsReloadKey, setToolsReloadKey] = useState(0);
  const signInAgain = useSignInAgain({
    onConnected: () => setToolsReloadKey((key) => key + 1),
  });
  const [availableModels, setAvailableModels] = useState<Model[]>([]);
  const [isSourcePopupOpen, setIsSourcePopupOpen] = useState(false);
  const [isToolsPopupOpen, setIsToolsPopupOpen] = useState(false);
  const [isModelsPopupOpen, setIsModelsPopupOpen] = useState(false);
  const [uploadModalState, setUploadModalState] =
    useState<ActiveState>('INACTIVE');
  const [selectedSourceIds, setSelectedSourceIds] = useState<Set<string>>(
    new Set(),
  );
  const [selectedTools, setSelectedTools] = useState<ToolSummary[]>([]);
  // Tools on the agent when it loaded: the owner's private ones don't come
  // back in the caller's own tool list, so the picker adds a row for each.
  const [attachedTools, setAttachedTools] = useState<ToolSummary[]>([]);
  // A save the server refused until the caller agrees that what they added
  // runs with their access; ``retry`` repeats it with ``confirm_sponsor``.
  const [sponsorRequest, setSponsorRequest] = useState<{
    confirmation: SponsorConfirmation;
    retry: (keys: string[]) => void;
  } | null>(null);
  const [selectedModelIds, setSelectedModelIds] = useState<Set<string>>(
    new Set(),
  );
  const [deleteConfirmation, setDeleteConfirmation] =
    useState<ActiveState>('INACTIVE');
  const [agentDetails, setAgentDetails] = useState<ActiveState>('INACTIVE');
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [addPromptModal, setAddPromptModal] = useState<ActiveState>('INACTIVE');
  const [hasChanges, setHasChanges] = useState(false);
  const [draftLoading, setDraftLoading] = useState(false);
  const [publishLoading, setPublishLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [jsonSchemaText, setJsonSchemaText] = useState('');
  const [jsonSchemaValid, setJsonSchemaValid] = useState(true);
  const tokenLimitSwitchId = useId();
  const requestLimitSwitchId = useId();
  const promptOverrideSwitchId = useId();
  const sourcesPickerId = useId();
  const toolsPickerId = useId();
  const modelsPickerId = useId();
  const [previewOpen, setPreviewOpen] = useState(false);
  const previewStatus = useSelector(selectPreviewStatus);

  // The preview chat outlives its drawer: closing and reopening keeps the
  // conversation. It starts over on New chat, after a save, and on leaving.
  useEffect(() => {
    dispatch(resetPreview());
    return () => {
      dispatch(resetPreview());
    };
  }, [dispatch]);
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
  const agentTypes = [
    { label: t('agents.form.agentTypes.classic'), value: 'classic' },
    { label: t('agents.form.agentTypes.research'), value: 'research' },
  ];

  const isPublishable = () => {
    const hasRequiredFields =
      agent.name && agent.description && agent.prompt_id && agent.agent_type;
    const isJsonSchemaValidOrEmpty =
      jsonSchemaText.trim() === '' || jsonSchemaValid;
    const guardrailsOk = !guardrailsIncomplete(agent.config?.guardrails);
    // Sources are optional: an agent without one answers from the model and
    // its tools only.
    return hasRequiredFields && isJsonSchemaValidOrEmpty && guardrailsOk;
  };

  const isJsonSchemaInvalid = () => {
    return jsonSchemaText.trim() !== '' && !jsonSchemaValid;
  };

  // Draft saves post the same `config` blob and hit the same server-side
  // validation as publish, so they need the same gate — otherwise an
  // incomplete control 400s the draft behind a message that names no field.
  const isDraftBlocked = () =>
    isJsonSchemaInvalid() || guardrailsIncomplete(agent.config?.guardrails);

  // Resolve a selected source id to its display name. Prefer the caller's own
  // source list; fall back to the owner-resolved name embedded in the agent
  // payload (source_details) so a team member viewing a shared agent sees the
  // source name instead of "External KB"; only then show the generic label.
  const resolveSourceLabel = useCallback(
    (id: string): string => {
      const matchedDoc = sourceDocs?.find(
        (source) => sourceItemId(source) === id,
      );
      if (matchedDoc?.name) return matchedDoc.name;
      const detail = agent.source_details?.find((d) => d.id === id);
      if (detail?.name) return detail.name;
      return t('agents.form.externalKb');
    },
    [agent.source_details, sourceDocs, t],
  );

  // Name of a tool/source/prompt that runs with an editor's access, from the
  // same owner-agnostic details the pickers show.
  const resolveSponsoredName = useCallback(
    (sponsor: ResourceSponsor): string => {
      if (sponsor.name) return sponsor.name;
      if (sponsor.type === 'source') return resolveSourceLabel(sponsor.id);
      if (sponsor.type === 'prompt') {
        return (
          prompts.find((prompt) => prompt.id === sponsor.id)?.name ||
          agent.prompt_name ||
          t('agents.form.sponsors.unknownItem')
        );
      }
      const tool = selectedTools.find((item) => item.id === sponsor.id);
      return tool
        ? getToolDisplayName(tool)
        : t('agents.form.sponsors.unknownItem');
    },
    [agent.prompt_name, prompts, resolveSourceLabel, selectedTools, t],
  );

  const sourceItems = useMemo(() => {
    const items = toSourcePickerItems(
      sourceDocs,
      {
        own: t('agents.form.sourcePopup.groupOwn'),
        team: t('agents.form.sourcePopup.groupTeam'),
      },
      <Database />,
    );
    // An attached source the caller can't list — an owner's private source on
    // a team-shared agent — still needs a row of its own, or it reads as
    // selected with nothing to switch it off.
    const listed = new Set(items.map((item) => item.id));
    const unlisted = Array.from(selectedSourceIds)
      .filter((id) => !listed.has(id))
      .map((id) => ({ id, label: resolveSourceLabel(id), icon: <Database /> }));
    return [...items, ...unlisted];
  }, [resolveSourceLabel, selectedSourceIds, sourceDocs, t]);

  // The caller's tools, plus a remove-only row for each tool on the agent
  // they can't list (the owner's private tools on a shared agent).
  const toolItems = useMemo(
    () =>
      withAttachedToolRows(userTools, attachedTools, {
        group: t('agents.form.toolsPopup.groupAttached'),
        description: t('agents.form.toolsPopup.attachedHint'),
      }),
    [attachedTools, t, userTools],
  );

  const selectedSourceNames = useMemo(
    () =>
      Array.from(selectedSourceIds)
        .map((id) => resolveSourceLabel(id))
        .filter(Boolean),
    [resolveSourceLabel, selectedSourceIds],
  );
  const sourceTriggerLabel =
    selectedSourceIds.size === 0
      ? t('agents.form.placeholders.selectSources')
      : selectedSourceIds.size === 1
        ? selectedSourceNames[0]
        : t('conversation.sources.selectedCount', {
            count: selectedSourceIds.size,
          });

  const handleUploadClick = () => {
    setIsSourcePopupOpen(false);
    setUploadModalState('ACTIVE');
  };

  // Select the source an upload started from this form created. The id comes
  // from the upload itself, so a source that appeared meanwhile for another
  // reason is never picked up by accident.
  const handleUploadedSource = (sourceId?: string) => {
    if (!sourceId) return;
    setSelectedSourceIds((prev) => new Set([...prev, sourceId]));
  };

  // Sources go out as the legacy single ``source`` for one selection and as
  // the ``sources`` list for several; an empty selection sends both empty.
  const appendSourceFields = (formData: FormData) => {
    const { source, sources } = serializeAgentSources(
      selectedSourceIds,
      sourceDocs,
    );
    formData.append('source', source);
    formData.append('sources', JSON.stringify(sources));
  };

  const handleUpload = useCallback((files: File[]) => {
    if (files && files.length > 0) {
      const file = files[0];
      setImageFile(file);
    }
  }, []);

  const navigateBackToAgents = useCallback(() => {
    const targetPath = validatedFolderId
      ? agentsListPath(validatedFolderId)
      : agentsListPath();
    navigate(targetPath);
  }, [navigate, validatedFolderId]);

  const handleCancel = () => {
    if (selectedAgent) dispatch(setSelectedAgent(null));
    navigateBackToAgents();
  };

  const handleDelete = async (agentId: string) => {
    try {
      const response = await userService.deleteAgent(agentId, token);
      if (!response.ok) {
        dispatch(
          showActionToast({
            variant: 'destructive',
            message: await extractApiError(response, t('agents.deleteFailed')),
          }),
        );
        return;
      }
      navigateBackToAgents();
    } catch (error) {
      console.error('Error deleting agent:', error);
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t('agents.deleteFailed'),
        }),
      );
    }
  };

  /**
   * The message for a refused save, or null when the refusal only asks the
   * caller to confirm sponsoring what they added (the dialog then opens and
   * ``retry`` repeats the save with their confirmation).
   */
  const saveFailureMessage = async (
    response: Response,
    fallback: string,
    retry: (keys: string[]) => void,
  ): Promise<string | null> => {
    const refusal = await readSponsorRefusal(response);
    if (refusal?.kind === 'confirm') {
      setSponsorRequest({ confirmation: refusal.confirmation, retry });
      return null;
    }
    if (refusal?.kind === 'notAllowed')
      return sponsorNotAllowedMessage(t, i18n.language, refusal.resources);
    return extractApiError(response, fallback);
  };

  const appendSponsorConfirmation = (
    formData: FormData,
    confirmSponsor?: string[],
  ) => {
    if (confirmSponsor && confirmSponsor.length > 0)
      formData.append('confirm_sponsor', JSON.stringify(confirmSponsor));
  };

  const handleSaveDraft = async (confirmSponsor?: string[]) => {
    const formData = new FormData();
    formData.append('name', agent.name);
    formData.append('description', agent.description);

    appendSourceFields(formData);

    formData.append('chunks', agent.chunks);
    formData.append('retriever', agent.retriever);
    formData.append('prompt_id', agent.prompt_id);
    formData.append('agent_type', agent.agent_type);
    formData.append('status', 'draft');
    formData.append('config', JSON.stringify(agent.config ?? {}));

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
    appendSponsorConfirmation(formData, confirmSponsor);

    try {
      setDraftLoading(true);
      setSubmitError(null);
      const response =
        effectiveMode === 'new'
          ? await userService.createAgent(formData, token)
          : await userService.updateAgent(agent.id || '', formData, token);
      if (!response.ok) {
        const message = await saveFailureMessage(
          response,
          t('agents.form.errors.saveDraftFailed'),
          (keys) => handleSaveDraft(keys),
        );
        if (message) setSubmitError(message);
        return;
      }
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
      setSubmitError(t('agents.form.errors.saveDraftFailed'));
    } finally {
      setDraftLoading(false);
    }
  };

  const handlePublish = async (confirmSponsor?: string[]) => {
    const formData = new FormData();
    formData.append('name', agent.name);
    formData.append('description', agent.description);

    appendSourceFields(formData);

    formData.append('chunks', agent.chunks);
    formData.append('retriever', agent.retriever);
    formData.append('prompt_id', agent.prompt_id);
    formData.append('agent_type', agent.agent_type);
    formData.append('status', 'published');
    formData.append('config', JSON.stringify(agent.config ?? {}));

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
    appendSponsorConfirmation(formData, confirmSponsor);

    try {
      setPublishLoading(true);
      setSubmitError(null);
      const response =
        effectiveMode === 'new'
          ? await userService.createAgent(formData, token)
          : await userService.updateAgent(agent.id || '', formData, token);
      if (!response.ok) {
        const message = await saveFailureMessage(
          response,
          t('agents.form.errors.publishFailed'),
          (keys) => handlePublish(keys),
        );
        if (message) setSubmitError(message);
        return;
      }
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
      // The saved agent is what the preview talks to; start its chat over.
      dispatch(resetPreview());

      if (effectiveMode === 'new' || effectiveMode === 'draft') {
        setEffectiveMode('edit');
        setAgentDetails('ACTIVE');
      }
      setImageFile(null);
    } catch (error) {
      console.error('Error publishing agent:', error);
      setSubmitError(t('agents.form.errors.publishFailed'));
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
      const [toolsResponse, devicesResult, connectionsResult, catalogResult] =
        await Promise.all([
          userService.getUserTools(token),
          // Tolerate failures here: the picker should still render the
          // tool list even if /api/devices returns an error or 401.
          devicesService.list(token).catch(() => ({ devices: [] })),
          connectorsService
            .listConnections(token)
            .catch(() => ({ connections: [] })),
          // Names a teammate's connected tool, whose connection the caller
          // never sees.
          connectorsService.getCatalog(token).catch(() => ({ connectors: [] })),
        ]);
      const ownConnections = (connectionsResult?.connections ??
        []) as Connection[];
      const catalog = (catalogResult?.connectors ??
        []) as ConnectorDefinition[];
      const connectionsById = new Map<string, Connection>(
        ownConnections.map((c) => [c.id, c]),
      );
      if (!toolsResponse.ok) throw new Error('Failed to fetch tools');
      const data = await toolsResponse.json();
      // Hide workflow-only builtins (e.g. read_document) from the classic
      // agent picker; they belong to the workflow-node picker only.
      const visibleTools = (data.tools as UserToolType[]).filter(
        isAgentPickerToolVisible,
      );
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
      // Group ordering: builtins -> defaults -> one group per connection
      // (the service and its account; a teammate's, only the service) ->
      // custom tools, via the MultiSelectPopover first-appearance grouping.
      const serviceOf = (tool: UserToolType) =>
        toolServiceOf(tool, ownConnections, catalog);
      const connectionOf = (tool: UserToolType) => serviceOf(tool)?.connection;
      const rank = (tool: UserToolType) =>
        tool.builtin ? 0 : tool.default ? 1 : tool.connection_id ? 2 : 3;
      const groupFor = (tool: UserToolType): string => {
        if (tool.builtin) return t('agents.form.toolsPopup.groupBuiltin');
        if (tool.default) return t('agents.form.toolsPopup.groupDefault');
        const service = serviceOf(tool);
        if (service?.connection)
          return t('agents.form.toolsPopup.groupConnection', {
            name: service.connection.name,
            account: service.connection.account_label,
            interpolation: { escapeValue: false },
          });
        if (service) return service.name;
        return t('agents.form.toolsPopup.groupCustom');
      };
      const tools: MultiSelectPopoverItem[] = [...visibleTools]
        .sort(
          (a, b) =>
            rank(a) - rank(b) ||
            // Keeps each connection's tools together.
            (rank(a) === 2 ? groupFor(a).localeCompare(groupFor(b)) : 0),
        )
        .map((tool: UserToolType) => {
          const connection = connectionOf(tool);
          const serviceIcon = serviceOf(tool)?.icon;
          const base: MultiSelectPopoverItem = {
            id: tool.id,
            label: getToolDisplayName(tool),
            icon: serviceIcon ? (
              <ConnectorIcon icon={serviceIcon} className="size-5" />
            ) : (
              <ToolIcon name={tool.name} className="size-5" />
            ),
            group: groupFor(tool),
          };
          if (connectionNeedsSignIn(connection)) {
            base.descriptionNode = (
              <p className="text-warning text-xs">
                {t('settings.connectors.health.signInAgain')}
              </p>
            );
          }
          if (tool.name === 'remote_device') {
            const deviceId = (tool.config?.device_id as string) || '';
            const meta = devicesById.get(deviceId);
            const online = meta?.online ?? false;
            base.descriptionNode = (
              <Badge
                variant={online ? 'success' : 'neutral'}
                className="mt-0.5"
              >
                {online
                  ? t('settings.devices.online')
                  : t('settings.devices.offline')}
              </Badge>
            );
          }
          return base;
        });
      setUserTools(tools);
      setRawUserTools(visibleTools);
      setBrokenToolConnections(
        Array.from(connectionsById.values())
          .filter(connectionNeedsSignIn)
          .flatMap((connection) => {
            const own = visibleTools.filter(
              (tool) => tool.connection_id === connection.id,
            );
            if (own.length === 0) return [];
            return [
              {
                connection,
                mcpToolId: own.find((tool) => tool.name === 'mcp_tool')?.id,
              },
            ];
          }),
      );
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
  }, [token, mode, toolsReloadKey]);

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

  useEffect(() => {
    if ((mode === 'edit' || mode === 'draft') && agentId) {
      const getAgent = async () => {
        const response = await userService.getAgent(agentId, token);
        if (!response.ok) {
          navigate(agentsListPath());
          throw new Error('Failed to fetch agent');
        }
        const data = await response.json();

        const agentSourceIds = selectedSourceIdsFromAgent(data);
        setSelectedSourceIds(new Set(agentSourceIds));

        if (data.tool_details) {
          setSelectedTools(data.tool_details);
          setAttachedTools(data.tool_details);
        }
        if (data.status === 'draft') setEffectiveMode('draft');
        if (data.json_schema) {
          const jsonText = JSON.stringify(data.json_schema, null, 2);
          setJsonSchemaText(jsonText);
          setJsonSchemaValid(true);
        }
        // Backfill required fields so older agents (created before
        // agent_type / prompt_id / models existed) don't fail
        // ``isPublishable()`` and leave Save permanently disabled.
        // Normalise exactly as the source and model effects below will, or the
        // form compares unequal to this snapshot and reports unsaved changes
        // before the user has touched anything.
        const agentModels: string[] = data.models || [];
        const normalized = {
          ...data,
          agent_type: data.agent_type || 'classic',
          prompt_id: data.prompt_id || 'default',
          retriever: agentSourceIds.length === 0 ? 'classic' : '',
          chunks: data.chunks || '6',
          tools: data.tools || [],
          ...serializeAgentSources(agentSourceIds, sourceDocs),
          models: agentModels,
          default_model_id: agentModels.includes(data.default_model_id || '')
            ? data.default_model_id
            : agentModels[0] || '',
          config: data.config || {},
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
    const { source, sources } = serializeAgentSources(
      selectedSourceIds,
      sourceDocs,
    );
    setAgent((prev) => ({
      ...prev,
      source,
      sources,
      // A source-less agent keeps the default retriever name so its runtime
      // config stays valid; real sources carry their own retriever.
      retriever: selectedSourceIds.size === 0 ? 'classic' : '',
    }));
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
    // Editing a published agent: the preview talks to the saved version, so
    // Redux keeps that snapshot (the preview reads its model from it).
    const saved = effectiveMode === 'edit' ? initialAgentRef.current : null;
    if (saved) dispatch(setSelectedAgent(saved));
    else if (isPublishable()) dispatch(setSelectedAgent(agent));

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

  const isPublished = agent.status === 'published';
  // What the caller's role allows on this agent (`allowed_actions` from the
  // API). A new agent carries no access fields, so it reads as the owner's.
  const canEditPolicy = can(agent, 'edit_policy');
  // Save on a published agent is an edit; on a draft or a new agent the main
  // button publishes it.
  const canSubmit = can(agent, effectiveMode === 'edit' ? 'edit' : 'publish');
  const agentDisplayName =
    agent.name?.trim() || t('agents.pageHeader.fallbackName');

  // Page-level actions live in the ⋯ beside the title. Until the agent is
  // published the preview can only say "Publish to preview", so Preview is a
  // menu item then and a toolbar button after.
  const menuOptions = [
    ...(isPublished
      ? []
      : [
          {
            label: t('agents.form.sections.preview'),
            icon: Play,
            onClick: () => setPreviewOpen(true),
          },
        ]),
    ...(modeConfig[effectiveMode].showAccessDetails &&
    can(agent, 'manage_access_details')
      ? [
          {
            label: t('agents.form.buttons.accessDetails'),
            onClick: () => setAgentDetails('ACTIVE'),
          },
        ]
      : []),
    // Sharing is the owner's, unless the owner lets editors share.
    ...(modeConfig[effectiveMode].showAccessDetails &&
    can(agent, 'share') &&
    agent.id
      ? [
          {
            label: t('agents.shareWithTeam'),
            onClick: () => setShareModalOpen(true),
          },
        ]
      : []),
  ];

  // At most three buttons, so the row fits a phone; the main one stretches
  // across it there.
  const headerActions = (
    <div className="flex flex-wrap items-center gap-2">
      {hasChanges && (
        <Button
          type="button"
          variant="ghost"
          size="field"
          shape="pill"
          onClick={handleCancel}
        >
          {t('agents.form.buttons.cancel')}
        </Button>
      )}
      {modeConfig[effectiveMode].showSaveDraft && can(agent, 'edit') && (
        <Button
          type="button"
          variant="outline"
          size="field"
          shape="pill"
          disabled={isDraftBlocked()}
          loading={draftLoading}
          onClick={() => handleSaveDraft()}
        >
          {t('agents.form.buttons.saveDraft')}
        </Button>
      )}
      {isPublished && (
        <Button
          type="button"
          variant="outline"
          size="field"
          shape="pill"
          onClick={() => setPreviewOpen(true)}
        >
          <Play />
          {t('agents.form.sections.preview')}
        </Button>
      )}
      {canSubmit && (
        <Button
          type="button"
          size="field"
          shape="pill"
          disabled={!isPublishable() || !hasChanges}
          loading={publishLoading}
          onClick={() => handlePublish()}
          className="flex-1 sm:flex-none"
        >
          {modeConfig[effectiveMode].buttonText}
        </Button>
      )}
    </div>
  );

  return (
    <SectionShell
      title={effectiveMode === 'new' ? t('agents.newAgent') : undefined}
      titleAction={
        <ActionMenu
          size="toolbar"
          triggerLabel={t('agents.form.buttons.moreActions')}
          options={menuOptions}
        />
      }
    >
      {signInAgain.modals}
      {agent.agent_type === 'workflow' && <WorkflowBuilder />}
      <AgentPageToolbar
        intro={agent.id ? undefined : t('agents.form.byline.new')}
        name={agentDisplayName}
        status={
          isPublished ? (
            <Badge variant="success">{t('agents.form.status.published')}</Badge>
          ) : (
            <Badge variant="neutral">{t('agents.card.draft')}</Badge>
          )
        }
        meta={
          effectiveMode === 'edit' ? (
            <LastUsedMeta lastUsedAt={agent.last_used_at} />
          ) : undefined
        }
        actions={headerActions}
      >
        {submitError && (
          <Alert variant="destructive" className="mb-6">
            <CircleX aria-hidden="true" />
            <AlertDescription>{submitError}</AlertDescription>
          </Alert>
        )}
      </AgentPageToolbar>
      <div className="flex flex-col gap-5">
        <Card variant="subtle" padding="lg" className="gap-5">
          <SectionHeader title={t('agents.form.sections.basics')} />
          {/* Phone: the avatar beside Name, Description across the row.
              From sm: the avatar spans both rows beside the fields. */}
          <div className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-5 sm:items-start">
            <FileUpload
              showPreview
              size="tile"
              currentImage={agent.image || undefined}
              onUpload={handleUpload}
              onRemove={() => setImageFile(null)}
              uploadText={t('agents.form.labels.avatar')}
              className="sm:row-span-2"
            />
            <FormField
              labelSurface="background"
              label={t('agents.form.labels.name')}
            >
              <Input
                shape="pill"
                type="text"
                value={agent.name}
                placeholder={t('agents.form.placeholders.agentName')}
                onChange={(e) => setAgent({ ...agent, name: e.target.value })}
              />
            </FormField>
            <FormField
              labelSurface="background"
              label={t('agents.form.labels.description')}
              className="col-span-2 sm:col-span-1 sm:col-start-2"
            >
              <Textarea
                size="lg"
                className="h-32 sm:h-24"
                placeholder={t('agents.form.placeholders.describeAgent')}
                value={agent.description}
                onChange={(e) =>
                  setAgent({ ...agent, description: e.target.value })
                }
              />
            </FormField>
          </div>
        </Card>
        <Card variant="subtle" padding="lg" className="gap-5">
          <SectionHeader title={t('agents.form.sections.knowledge')} />
          <div className="grid grid-cols-1 gap-x-4 gap-y-5 sm:grid-cols-2">
            <FormField
              id={sourcesPickerId}
              labelSurface="background"
              label={t('agents.form.labels.sources')}
              hint={
                selectedSourceIds.size === 0
                  ? t('agents.form.sourcePopup.noSourceHint')
                  : undefined
              }
            >
              <MultiSelectPopover
                open={isSourcePopupOpen}
                onOpenChange={setIsSourcePopupOpen}
                title={t('agents.form.sourcePopup.title')}
                items={sourceItems}
                selectedIds={Array.from(selectedSourceIds)}
                onToggle={(id) => {
                  const next = new Set(selectedSourceIds);
                  if (next.has(id)) next.delete(id);
                  else next.add(id);
                  setSelectedSourceIds(next);
                }}
                searchPlaceholder={t(
                  'agents.form.sourcePopup.searchPlaceholder',
                )}
                emptyMessage={t('agents.form.sourcePopup.noOptionsMessage')}
                footer={
                  <SourcesPopoverFooter
                    onNavigate={() => setIsSourcePopupOpen(false)}
                    onUploadClick={handleUploadClick}
                  />
                }
                trigger={
                  <Button
                    type="button"
                    variant="combobox"
                    size="field"
                    shape="pill"
                    id={sourcesPickerId}
                    ref={sourceAnchorButtonRef}
                    data-placeholder={
                      selectedSourceIds.size > 0 ? undefined : ''
                    }
                    className="w-full justify-start text-left"
                  >
                    <span
                      className="truncate"
                      title={selectedSourceNames.join(', ')}
                    >
                      {sourceTriggerLabel}
                    </span>
                  </Button>
                }
              />
            </FormField>
            <FormField
              id={toolsPickerId}
              labelSurface="background"
              label={t('agents.form.sections.tools')}
            >
              <MultiSelectPopover
                open={isToolsPopupOpen}
                onOpenChange={setIsToolsPopupOpen}
                title={t('agents.form.toolsPopup.title')}
                items={toolItems}
                selectedIds={selectedTools.map((tool) => tool.id)}
                onToggle={(id) => {
                  const exists = selectedTools.find((t) => t.id === id);
                  if (exists) {
                    setSelectedTools(selectedTools.filter((t) => t.id !== id));
                    return;
                  }
                  const item = toolItems.find((t) => t.id === id);
                  const raw = rawUserTools.find((t) => t.id === id);
                  const attached = attachedTools.find((t) => t.id === id);
                  if (!item) return;
                  setSelectedTools([
                    ...selectedTools,
                    attached ?? {
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
                footer={
                  brokenToolConnections.length > 0 ? (
                    <SignInAgainNotice
                      connections={brokenToolConnections.map(
                        ({ connection }) => connection,
                      )}
                      onReconnect={(connection) => {
                        setIsToolsPopupOpen(false);
                        signInAgain.reconnect(
                          connection,
                          brokenToolConnections.find(
                            (entry) => entry.connection.id === connection.id,
                          )?.mcpToolId,
                        );
                      }}
                    />
                  ) : undefined
                }
                trigger={
                  <Button
                    type="button"
                    variant="combobox"
                    size="field"
                    shape="pill"
                    id={toolsPickerId}
                    ref={toolAnchorButtonRef}
                    data-placeholder={selectedTools.length > 0 ? undefined : ''}
                    className="w-full justify-start text-left"
                  >
                    <span className="truncate">
                      {selectedTools.length > 0
                        ? selectedTools
                            .map((tool) => getToolDisplayName(tool))
                            .filter(Boolean)
                            .join(', ')
                        : t('agents.form.placeholders.selectTools')}
                    </span>
                  </Button>
                }
              />
            </FormField>
            <div className="flex items-center gap-2 sm:col-span-2">
              <div className="min-w-0 flex-1">
                <Prompts
                  prompts={prompts}
                  selectedPrompt={
                    prompts.find((prompt) => prompt.id === agent.prompt_id) ||
                    // Owner-resolved name from the agent payload: lets a team
                    // member see the owner's prompt name (which isn't in their
                    // own prompts list). 'public' hides owner-only edit/share
                    // affordances on a prompt the viewer doesn't own.
                    (agent.prompt_name
                      ? {
                          name: agent.prompt_name,
                          id: agent.prompt_id || 'default',
                          type: 'public',
                        }
                      : prompts[0]) || {
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
                  titleAs="field"
                  labelSurface="background"
                  showAddButton={false}
                />
              </div>
              <Button
                type="button"
                variant="outline-primary"
                size="field"
                shape="pill"
                onClick={() => setAddPromptModal('ACTIVE')}
              >
                {t('agents.form.buttons.add')}
              </Button>
            </div>
            <SponsoredResourcesNotice
              agent={agent}
              resolveName={resolveSponsoredName}
            />
          </div>
        </Card>
        <Card variant="subtle" padding="lg" className="gap-5">
          <SectionHeader title={t('agents.form.sections.model')} />
          <div className="grid grid-cols-1 gap-x-4 gap-y-5 sm:grid-cols-2">
            <FormField
              labelSurface="background"
              label={t('agents.form.sections.agentType')}
            >
              <Select
                value={agent.agent_type || undefined}
                onValueChange={(value) =>
                  setAgent({ ...agent, agent_type: value })
                }
              >
                <SelectTrigger className="w-full" shape="pill" size="field">
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
            </FormField>
            <FormField
              id={modelsPickerId}
              labelSurface="background"
              label={t('agents.form.sections.models')}
            >
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
                    variant="combobox"
                    size="field"
                    shape="pill"
                    id={modelsPickerId}
                    ref={modelAnchorButtonRef}
                    data-placeholder={
                      selectedModelIds.size > 0 ? undefined : ''
                    }
                    className="w-full justify-start text-left"
                  >
                    <span className="truncate">
                      {selectedModelIds.size > 0
                        ? availableModels
                            .filter((m) => selectedModelIds.has(m.id))
                            .map((m) => m.display_name)
                            .join(', ')
                        : t('agents.form.placeholders.selectModels')}
                    </span>
                  </Button>
                }
              />
            </FormField>
            {selectedModelIds.size > 0 && (
              <FormField
                labelSurface="background"
                label={t('agents.form.labels.defaultModel')}
              >
                <Select
                  value={agent.default_model_id || undefined}
                  onValueChange={(value) =>
                    setAgent({ ...agent, default_model_id: value })
                  }
                >
                  <SelectTrigger className="w-full" shape="pill" size="field">
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
              </FormField>
            )}
          </div>
        </Card>
        <Card variant="subtle" padding="lg" className="gap-5">
          {/* The heading wraps the toggle: a button's children are
              presentational, so a heading inside it is lost to screen readers. */}
          <h2>
            <Button
              type="button"
              variant="section-toggle"
              onClick={() =>
                setIsAdvancedSectionExpanded(!isAdvancedSectionExpanded)
              }
              size="sm"
              aria-expanded={isAdvancedSectionExpanded}
              className="-ml-3 w-fit justify-start"
            >
              <ChevronRight
                aria-hidden="true"
                className={cn(
                  'transition-transform duration-200',
                  isAdvancedSectionExpanded && 'rotate-90',
                )}
              />
              <span className="text-lg font-semibold">
                {t('agents.form.sections.advanced')}
              </span>
            </Button>
          </h2>
          {isAdvancedSectionExpanded && (
            <div>
              <FormField
                labelSurface="background"
                label={t('agents.form.advanced.jsonSchema')}
                hint={t('agents.form.advanced.jsonSchemaDescription')}
              >
                <Textarea
                  size="lg"
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
                  className="font-mono"
                />
              </FormField>
              {jsonSchemaText.trim() !== '' && (
                <div
                  className={cn(
                    'mt-2 flex items-center gap-2 text-sm',
                    jsonSchemaValid ? 'text-success' : 'text-destructive',
                  )}
                >
                  {jsonSchemaValid ? (
                    <CircleCheck className="size-4" aria-hidden="true" />
                  ) : (
                    <CircleX className="size-4" aria-hidden="true" />
                  )}
                  {jsonSchemaValid
                    ? t('agents.form.advanced.validJson')
                    : t('agents.form.advanced.invalidJson')}
                </div>
              )}

              <SettingRows className="mt-6">
                <SettingRow
                  label={t('agents.form.advanced.tokenLimiting')}
                  description={t(
                    'agents.form.advanced.tokenLimitingDescription',
                  )}
                  htmlFor={tokenLimitSwitchId}
                  after={
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
                      disabled={!agent.limited_token_mode || !canEditPolicy}
                      placeholder={t(
                        'agents.form.placeholders.enterTokenLimit',
                      )}
                      aria-label={t('agents.form.advanced.tokenLimit')}
                      shape="pill"
                    />
                  }
                >
                  <Switch
                    id={tokenLimitSwitchId}
                    checked={agent.limited_token_mode}
                    disabled={!canEditPolicy}
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
                </SettingRow>
                <SettingRow
                  label={t('agents.form.advanced.requestLimiting')}
                  description={t(
                    'agents.form.advanced.requestLimitingDescription',
                  )}
                  htmlFor={requestLimitSwitchId}
                  after={
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
                      disabled={!agent.limited_request_mode || !canEditPolicy}
                      placeholder={t(
                        'agents.form.placeholders.enterRequestLimit',
                      )}
                      aria-label={t('agents.form.advanced.requestLimit')}
                      shape="pill"
                    />
                  }
                >
                  <Switch
                    id={requestLimitSwitchId}
                    checked={agent.limited_request_mode}
                    disabled={!canEditPolicy}
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
                </SettingRow>
                <SettingRow
                  label={t('agents.form.advanced.systemPromptOverride')}
                  description={t(
                    'agents.form.advanced.systemPromptOverrideDescription',
                  )}
                  htmlFor={promptOverrideSwitchId}
                >
                  <Switch
                    id={promptOverrideSwitchId}
                    checked={agent.allow_system_prompt_override}
                    onCheckedChange={(checked) =>
                      setAgent({
                        ...agent,
                        allow_system_prompt_override: checked,
                      })
                    }
                  />
                </SettingRow>
              </SettingRows>
            </div>
          )}
        </Card>
        <GuardrailsSection
          value={agent.config?.guardrails}
          token={token}
          // Guardrails are policy (`edit_policy`): editors and the owner
          // change them; anyone else sees them read-only.
          disabled={!canEditPolicy}
          onChange={(guardrails) =>
            setAgent({
              ...agent,
              config: { ...(agent.config ?? {}), guardrails },
            })
          }
        />
        {modeConfig[effectiveMode].showDelete &&
          agent.id &&
          can(agent, 'delete') && (
            <Card
              tone="destructive"
              padding="lg"
              className="flex-row flex-wrap items-start justify-between"
            >
              <SectionHeader
                tone="destructive"
                title={t('agents.form.dangerZone.heading')}
                description={t('agents.form.dangerZone.description')}
                className="min-w-0 flex-1"
              />
              <Button
                type="button"
                variant="destructive-outline"
                size="sm"
                onClick={() => setDeleteConfirmation('ACTIVE')}
                className="shrink-0"
              >
                {t('agents.form.dangerZone.deleteButton')}
              </Button>
            </Card>
          )}
      </div>
      <SponsorConfirmModal
        confirmation={sponsorRequest?.confirmation ?? null}
        onCancel={() => setSponsorRequest(null)}
        onConfirm={(keys) => {
          const retry = sponsorRequest?.retry;
          setSponsorRequest(null);
          retry?.(keys);
        }}
      />
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
        variant="destructive"
      />
      <AgentDetailsModal
        agent={agent}
        mode={effectiveMode}
        modalState={agentDetails}
        setModalState={setAgentDetails}
        onKeyRegenerated={(key) => setAgent((prev) => ({ ...prev, key }))}
        onConfigChange={(config) => {
          // The allowlist is saved already: record it on the saved snapshot
          // too, and keep any unsaved form edits to the rest of the config.
          if (initialAgentRef.current)
            initialAgentRef.current = { ...initialAgentRef.current, config };
          setAgent((prev) => ({
            ...prev,
            config: {
              ...(prev.config ?? {}),
              api_write_allowlist: config.api_write_allowlist,
            },
          }));
        }}
        getSavedConfig={() => initialAgentRef.current?.config ?? agent.config}
      />
      {shareModalOpen && agent.id && (
        <ShareToTeamModal
          resourceType="agent"
          resourceId={agent.id}
          resourceName={agent.name}
          onClose={() => setShareModalOpen(false)}
        />
      )}
      {uploadModalState === 'ACTIVE' && (
        <Upload
          receivedFile={[]}
          setModalState={setUploadModalState}
          isOnboarding={false}
          renderTab={null}
          close={() => setUploadModalState('INACTIVE')}
          onSuccessfulUpload={handleUploadedSource}
          selectUploadedDoc={false}
        />
      )}
      <AddPromptModal
        prompts={prompts}
        isOpen={addPromptModal}
        onClose={() => setAddPromptModal('INACTIVE')}
        onSelect={(name: string, id: string, type: string) => {
          setAgent({ ...agent, prompt_id: id });
        }}
      />
      <AgentPreviewSheet
        open={previewOpen}
        onOpenChange={setPreviewOpen}
        title={t('agents.form.sections.preview')}
        description={`${agentDisplayName} · ${
          isPublished
            ? t('agents.form.preview.savedVersion')
            : t('agents.card.draft')
        }`}
        running={previewStatus === 'loading'}
        actions={
          isPublished ? (
            <Button
              type="button"
              variant="ghost-muted"
              size="sm"
              shape="pill"
              onClick={() => dispatch(resetPreview())}
            >
              <SquarePen />
              {t('newChat')}
            </Button>
          ) : undefined
        }
      >
        {isPublished ? (
          <div className="flex min-h-0 flex-1 flex-col">
            {effectiveMode === 'edit' && hasChanges && (
              <div className="px-4 pt-4">
                <Alert role="note">
                  <Info />
                  <AlertDescription>
                    {t('agents.form.preview.unsavedChanges')}
                  </AlertDescription>
                </Alert>
              </div>
            )}
            <div className="relative min-h-0 flex-1">
              <AgentPreview />
            </div>
          </div>
        ) : (
          <div className="flex flex-1 items-center justify-center px-6">
            <EmptyState
              size="sm"
              illustration="none"
              title={t('agents.form.preview.publishTitle')}
              description={t('agents.form.preview.publishDescription')}
              action={
                can(agent, 'publish') ? (
                  <Button
                    type="button"
                    size="sm"
                    shape="pill"
                    disabled={!isPublishable()}
                    loading={publishLoading}
                    onClick={() => handlePublish()}
                  >
                    {t('agents.form.buttons.publish')}
                  </Button>
                ) : undefined
              }
            />
          </div>
        )}
      </AgentPreviewSheet>
    </SectionShell>
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
      onSelect?.(newPromptName, newPrompt.id, 'private');
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
