import { CircleCheck, CircleX, Play, SquarePen } from 'lucide-react';
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
import { Collapsible, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Combobox, type ComboboxGroup } from '@/components/ui/combobox';
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

import modelService from '../api/services/modelService';
import userService from '../api/services/userService';
import { FileUpload } from '../components/FileUpload';
import {
  MultiSelectPopover,
  type MultiSelectPopoverItem,
} from '../components/MultiSelectPopover';
import PickerFooter from '../components/PickerFooter';
import connectorsService from '../api/services/connectorsService';
import { useSignInAgain } from '../connectors/SignInAgainNotice';
import type { Connection, ConnectorDefinition } from '../connectors/types';
import AgentDetailsModal from '../modals/AgentDetailsModal';
import { ActiveState, Prompt } from '../models/misc';
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
import { usePickerKindFilter } from '../hooks/usePickerKindFilter';
import { useLeaveGuard } from '../hooks/useLeaveGuard';
import { UserToolType } from '../settings/types';
import { can } from '../utils/accessUtils';
import { isReader, personLabel, readerIdFromToken } from '../utils/personLabel';
import {
  selectedSourceIdsFromAgent,
  serializeAgentSources,
  sourceItemId,
} from '../utils/sourceUtils';
import {
  getToolDisplayName,
  isAgentPickerToolVisible,
} from '../utils/toolUtils';
import { agentEditPath, agentsListPath, isWorkflowAgent } from './paths';
import { cleanStarters, MAX_STARTER_LENGTH, MAX_STARTERS } from './starters';
import GuardrailsSection, {
  guardrailsIncomplete,
} from './components/GuardrailsSection';
import AnalyticsSection from './components/AnalyticsSection';
import ContextLimitRows from './components/ContextLimitRows';
import { analyticsOf, configToSave } from './analyticsConfig';
import {
  isContextLimitInvalid,
  isHistoryLimitInvalid,
  largestModelWindow,
} from './contextLimit';
import { useAnalyticsAvailability } from '../settings/insights/useAnalyticsAvailability';
import AgentPreview from './AgentPreview';
import AllowedOriginsSetting, {
  originsIncomplete,
} from './components/AllowedOriginsSetting';
import { resetPreview, selectPreviewStatus } from './agentPreviewSlice';
import AgentPageToolbar, { LastUsedMeta } from './components/AgentPageToolbar';
import AgentPreviewSheet from './components/AgentPreviewSheet';
import KnowledgePicker from './components/KnowledgePicker';
import ToolsPicker from './components/ToolsPicker';
import SectionShell from '../navigation/SectionShell';
import ResourceStatusNotice, {
  type NamedResource,
  unnamedResourceLabel,
} from './components/ResourceStatusNotice';

import { useAgentMenu } from './hooks/useAgentMenu';
import { useAttachAddedTools } from './hooks/useAttachAddedTools';
import { useBuilderDirtyState } from './hooks/useBuilderDirtyState';
import { useSponsoredSave } from './hooks/useSponsoredSave';
import { Agent, ResourceSponsor, ResourceState, ToolSummary } from './types';

import type { Model } from '../models/types';

/** The Prompt picker's kinds (the Prompts page's sections) and their `type`. */
const PROMPT_KIND_TYPES = {
  included: 'public',
  yours: 'private',
  shared: 'team',
} as const;
const PROMPT_KINDS = ['all', 'included', 'yours', 'shared'] as const;
type PromptKind = (typeof PROMPT_KINDS)[number];
const promptOfKind = (kind: PromptKind, prompt: Prompt): boolean =>
  kind === 'all' || prompt.type === PROMPT_KIND_TYPES[kind];
const PROMPT_PRESETS = ['default', 'creative', 'strict'];

/**
 * What a save sends, in a shape two copies compare by: the unsaved-changes
 * baseline. The schema counts as typed; the config reads a missing insights
 * block or limit as its default, as `sameAgent` does.
 */
function agentSavePayload(agent: Agent, jsonSchemaText: string) {
  return {
    name: agent.name ?? '',
    description: agent.description ?? '',
    starters: cleanStarters(agent.starters),
    source: agent.source ?? '',
    sources: agent.sources ?? [],
    chunks: agent.chunks ?? '',
    retriever: agent.retriever ?? '',
    prompt_id: agent.prompt_id ?? '',
    agent_type: agent.agent_type ?? '',
    tools: agent.tools ?? [],
    json_schema: jsonSchemaText,
    limited_token_mode: Boolean(agent.limited_token_mode),
    token_limit: agent.token_limit ?? null,
    limited_request_mode: Boolean(agent.limited_request_mode),
    request_limit: agent.request_limit ?? null,
    allow_system_prompt_override: Boolean(agent.allow_system_prompt_override),
    models: agent.models ?? [],
    default_model_id: agent.default_model_id ?? '',
    config: {
      ...(agent.config ?? {}),
      analytics: analyticsOf(agent.config?.analytics),
      context_window_limit: agent.config?.context_window_limit ?? null,
      history_token_limit: agent.config?.history_token_limit ?? null,
    },
  };
}
type AgentSavePayload = ReturnType<typeof agentSavePayload>;

/** The ids of the picked tools, in their order: what a save sends. */
const toolIdsOf = (tools: ToolSummary[]): string[] =>
  tools
    .map((tool) => tool?.id)
    .filter((id): id is string => typeof id === 'string');

export default function NewAgent({ mode }: { mode: 'new' | 'edit' | 'draft' }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const { agentId } = useParams();

  const [searchParams] = useSearchParams();
  const folderIdFromUrl = searchParams.get('folder_id');

  const token = useSelector(selectToken);
  const readerId = useMemo(() => readerIdFromToken(token), [token]);
  const analyticsAvailability = useAnalyticsAvailability();
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
  const [rawUserTools, setRawUserTools] = useState<UserToolType[]>([]);
  // What the tool rows are drawn from beside the tools themselves.
  const [toolContext, setToolContext] = useState<{
    connections: Connection[];
    catalog: ConnectorDefinition[];
  }>({ connections: [], catalog: [] });
  const [toolsReloadKey, setToolsReloadKey] = useState(0);
  // Bumped after a reconnect so the agent's run state is read again.
  const [detailsReloadKey, setDetailsReloadKey] = useState(0);
  const [availableModels, setAvailableModels] = useState<Model[]>([]);
  // The instance's default model: what an agent with no models of its own
  // answers with.
  const [systemDefaultModelId, setSystemDefaultModelId] = useState('');
  const [isSourcePopupOpen, setIsSourcePopupOpen] = useState(false);
  const [isToolsPopupOpen, setIsToolsPopupOpen] = useState(false);
  const [isPromptPickerOpen, setIsPromptPickerOpen] = useState(false);
  const [isModelsPopupOpen, setIsModelsPopupOpen] = useState(false);
  const [selectedSourceIds, setSelectedSourceIds] = useState<Set<string>>(
    new Set(),
  );
  const [selectedTools, setSelectedTools] = useState<ToolSummary[]>([]);
  // Tools on the agent when it loaded: the owner's private ones don't come
  // back in the caller's own tool list, so the picker adds a row for each.
  const [attachedTools, setAttachedTools] = useState<ToolSummary[]>([]);
  // Saves ask before what the caller added runs with their access, and
  // carry the stopped items the caller chose to keep running (takeovers).
  // A new agent has no sponsors to read again.
  const sponsoredSave = useSponsoredSave({
    refresh: () => void refreshSponsors(agent.id),
  });
  const { takeovers } = sponsoredSave;
  const [selectedModelIds, setSelectedModelIds] = useState<Set<string>>(
    new Set(),
  );
  const [agentDetails, setAgentDetails] = useState<ActiveState>('INACTIVE');
  // Access details opened from Share to allow changes: its allowlist unfolds.
  const [detailsOnApiWrites, setDetailsOnApiWrites] = useState(false);
  const [addPromptModal, setAddPromptModal] = useState<ActiveState>('INACTIVE');
  const [draftLoading, setDraftLoading] = useState(false);
  const [publishLoading, setPublishLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [jsonSchemaText, setJsonSchemaText] = useState('');
  const [jsonSchemaValid, setJsonSchemaValid] = useState(true);
  // Unsaved changes: what a save would send against what was loaded or last
  // saved (a draft save too); a new agent against what it opened with.
  const savePayload = useMemo(
    () => agentSavePayload(agent, jsonSchemaText),
    [agent, jsonSchemaText],
  );
  const { dirty: hasChanges, markSaved } =
    useBuilderDirtyState<AgentSavePayload>(savePayload, {
      ready: mode === 'new',
      extras: imageFile !== null || takeovers.length > 0,
    });
  const tokenLimitSwitchId = useId();
  const requestLimitSwitchId = useId();
  const promptOverrideSwitchId = useId();
  const sourcesPickerId = useId();
  const toolsPickerId = useId();
  const promptPickerId = useId();
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
  const advancedSectionId = React.useId();

  const initialAgentRef = useRef<Agent | null>(null);
  const sourceAnchorButtonRef = useRef<HTMLButtonElement>(null);
  const toolAnchorButtonRef = useRef<HTMLButtonElement>(null);
  const modelAnchorButtonRef = useRef<HTMLButtonElement>(null);

  const modeConfig = {
    new: {
      heading: t('agents.form.headings.new'),
      buttonText: t('agents.form.buttons.publish'),
      showSaveDraft: true,
      showAccessDetails: false,
    },
    edit: {
      heading: t('agents.form.headings.edit'),
      buttonText: t('agents.form.buttons.save'),
      showSaveDraft: false,
      showAccessDetails: true,
    },
    draft: {
      heading: t('agents.form.headings.draft'),
      buttonText: t('agents.form.buttons.publish'),
      showSaveDraft: true,
      showAccessDetails: false,
    },
  };
  const agentTypes = [
    { label: t('agents.form.agentTypes.classic'), value: 'classic' },
    { label: t('agents.form.agentTypes.research'), value: 'research' },
  ];

  // The largest window of the agent's models: a limit past it is noted.
  const modelWindow = useMemo(
    () =>
      largestModelWindow(
        availableModels,
        selectedModelIds.size > 0 ? selectedModelIds : [systemDefaultModelId],
      ),
    [availableModels, selectedModelIds, systemDefaultModelId],
  );
  const contextLimitInvalid =
    isContextLimitInvalid(agent.config?.context_window_limit) ||
    isHistoryLimitInvalid(
      agent.config?.history_token_limit,
      agent.config?.context_window_limit,
    );

  const isPublishable = () => {
    const hasRequiredFields =
      agent.name && agent.description && agent.prompt_id && agent.agent_type;
    const isJsonSchemaValidOrEmpty =
      jsonSchemaText.trim() === '' || jsonSchemaValid;
    const guardrailsOk = !guardrailsIncomplete(agent.config?.guardrails);
    // Sources are optional: an agent without one answers from the model and
    // its tools only.
    return (
      hasRequiredFields &&
      isJsonSchemaValidOrEmpty &&
      guardrailsOk &&
      !originsIncomplete(agent.config) &&
      !contextLimitInvalid
    );
  };

  const isJsonSchemaInvalid = () => {
    return jsonSchemaText.trim() !== '' && !jsonSchemaValid;
  };

  // Draft saves post the same `config` blob and hit the same server-side
  // validation as publish, so they need the same gate — otherwise an
  // incomplete control 400s the draft behind a message that names no field.
  const isDraftBlocked = () =>
    isJsonSchemaInvalid() ||
    guardrailsIncomplete(agent.config?.guardrails) ||
    originsIncomplete(agent.config) ||
    contextLimitInvalid;

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
    (sponsor: NamedResource): string => {
      if (sponsor.name) return sponsor.name;
      if (sponsor.type === 'source') return resolveSourceLabel(sponsor.id);
      if (sponsor.type === 'prompt') {
        return (
          prompts.find((prompt) => prompt.id === sponsor.id)?.name ||
          agent.prompt_name ||
          unnamedResourceLabel(t, sponsor)
        );
      }
      const tool = selectedTools.find((item) => item.id === sponsor.id);
      return tool ? getToolDisplayName(tool) : unnamedResourceLabel(t, sponsor);
    },
    [agent.prompt_name, prompts, resolveSourceLabel, selectedTools, t],
  );

  // "Added by …" for a tool, source or prompt that runs with an editor's
  // access (`resource_sponsors`), shown where it is picked; null otherwise.
  const addedByLabel = useCallback(
    (type: ResourceSponsor['type'], id: string): string | null => {
      const sponsor = (agent.resource_sponsors ?? []).find(
        (item) =>
          item.active &&
          item.type === type &&
          item.id.toLowerCase() === id.toLowerCase(),
      );
      if (!sponsor) return null;
      if (isReader(sponsor, readerId))
        return t('agents.form.sponsors.addedByYou');
      const person = sponsor.user_id ? personLabel(sponsor) : null;
      return person
        ? t('agents.form.sponsors.addedBy', {
            person,
            interpolation: { escapeValue: false },
          })
        : t('agents.form.sponsors.addedByOther');
    },
    [agent.resource_sponsors, readerId, t],
  );

  const promptAddedBy = agent.prompt_id
    ? addedByLabel('prompt', agent.prompt_id)
    : null;

  // The prompt picker's kind filter, back on All each time it opens.
  const promptKinds = usePickerKindFilter(prompts, isPromptPickerOpen, {
    kinds: PROMPT_KINDS,
    matches: promptOfKind,
    labelOf: (kind) =>
      kind === 'all'
        ? t('settings.prompts.filters.all')
        : kind === 'shared'
          ? t('settings.prompts.kinds.shared')
          : t(`settings.prompts.sections.${kind}`),
    ariaLabel: t('settings.prompts.kindFilterLabel'),
  });
  // A row's line, as its Prompts page card says it: a preset's purpose, else
  // the start of the prompt (the list names no sharer for a teammate's).
  const promptLine = (prompt: Prompt): string | undefined =>
    PROMPT_PRESETS.includes(prompt.id) && prompt.type === 'public'
      ? t(`settings.prompts.presets.${prompt.id}`)
      : prompt.preview || undefined;
  // The prompt picker's groups, as the Prompts page has them.
  const promptGroups: ComboboxGroup[] = PROMPT_KINDS.filter(
    (kind) => kind !== 'all',
  )
    .map((kind) => ({
      heading: t(`settings.prompts.sections.${kind}`),
      options: promptKinds.items
        .filter((prompt) => prompt.type === PROMPT_KIND_TYPES[kind])
        .map((prompt) => ({
          value: prompt.id,
          label: prompt.name,
          description: promptLine(prompt),
        })),
    }))
    .filter((group) => group.options.length > 0);
  // The picked prompt's name for the trigger, from the full list, so a kind
  // filter that hides it never shows another; else, for the prompt the agent
  // was loaded with, its name from the agent (a teammate's agent names the
  // owner's prompt); a preset reads as its id before the list loads.
  const pickedPromptId = agent.prompt_id || 'default';
  const pickedPromptLabel =
    prompts.find((prompt) => prompt.id === pickedPromptId)?.name ||
    (pickedPromptId === initialAgentRef.current?.prompt_id
      ? agent.prompt_name
      : '') ||
    (PROMPT_PRESETS.includes(pickedPromptId) ? pickedPromptId : '');
  const promptValueOption = pickedPromptLabel
    ? { value: pickedPromptId, label: pickedPromptLabel }
    : undefined;

  // Who added a source or tool, joined to its picker row's line.
  const sourceAddedBy = useCallback(
    (id: string) => addedByLabel('source', id),
    [addedByLabel],
  );
  const toolAddedBy = useCallback(
    (id: string) => addedByLabel('tool', id),
    [addedByLabel],
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

  // Fresh sponsor details and run state after a save or a reconnect,
  // without touching unsaved fields.
  const refreshSponsors = useCallback(
    async (id?: string) => {
      if (!id) return;
      try {
        const response = await userService.getAgent(id, token);
        if (!response.ok) return;
        const data = await response.json();
        const details: Partial<Agent> = {
          resource_sponsors: data.resource_sponsors ?? [],
          resource_states: data.resource_states ?? [],
          sponsor_audience: data.sponsor_audience,
        };
        setAgent((prev) => ({ ...prev, ...details }));
        if (initialAgentRef.current)
          initialAgentRef.current = { ...initialAgentRef.current, ...details };
      } catch {
        // The notice keeps what it showed.
      }
    },
    [token],
  );

  useEffect(() => {
    if (detailsReloadKey > 0) void refreshSponsors(agent.id);
    // Only a reconnect asks for this; agent.id is read when it does.
  }, [detailsReloadKey, refreshSponsors]);

  /**
   * Create or update the agent, asking whenever the server wants the
   * caller's confirmation to run what they added with their access.
   */
  const sendAgent = (formData: FormData, fallback: string) => {
    // A team editor's update is refused when someone saved in between.
    if (effectiveMode !== 'new' && agent.updated_at)
      formData.set('expected_updated_at', agent.updated_at);
    return sponsoredSave.save((confirm) => {
      if (confirm.length > 0)
        formData.set('confirm_sponsor', JSON.stringify(confirm));
      else formData.delete('confirm_sponsor');
      return effectiveMode === 'new'
        ? userService.createAgent(formData, token)
        : userService.updateAgent(agent.id || '', formData, token);
    }, fallback);
  };
  // One save at a time: Save draft and Publish beside each other would both
  // create a new agent.
  const savingRef = useRef(false);

  const undoTakeover = sponsoredSave.undoTakeover;

  // Stopped items still on the agent in the form: one removed here (not yet
  // saved) leaves the notice.
  const stoppedResources = useMemo(() => {
    const toolIds = new Set(
      selectedTools.map((tool) => String(tool?.id).toLowerCase()),
    );
    const sourceIds = new Set(
      Array.from(selectedSourceIds, (id) => id.toLowerCase()),
    );
    const promptId = String(agent.prompt_id || '').toLowerCase();
    return (agent.resource_states ?? []).filter(
      (item) =>
        item.state === 'stopped' &&
        (item.type === 'tool'
          ? toolIds.has(item.id)
          : item.type === 'source'
            ? sourceIds.has(item.id)
            : promptId === item.id),
    );
  }, [
    agent.resource_states,
    agent.prompt_id,
    selectedSourceIds,
    selectedTools,
  ]);

  /** Take a stopped item off the agent; the next save stores it. */
  const removeResource = (item: ResourceState) => {
    if (item.type === 'tool')
      setSelectedTools((prev) =>
        prev.filter((tool) => String(tool?.id).toLowerCase() !== item.id),
      );
    else if (item.type === 'source')
      setSelectedSourceIds(
        (prev) =>
          new Set(
            Array.from(prev).filter((id) => id.toLowerCase() !== item.id),
          ),
      );
    else setAgent((prev) => ({ ...prev, prompt_id: 'default' }));
    undoTakeover(item.key);
  };

  /**
   * Ask before a stopped item runs with the caller's access, naming who
   * reaches it through the agent; on yes the next save confirms it.
   */
  const takeOverResource = (item: ResourceState) =>
    sponsoredSave.takeOver(
      item,
      resolveSponsoredName(item),
      agent.sponsor_audience,
    );

  /** Sign a stopped tool's connection in again, in place where possible. */
  const reconnectResource = (item: ResourceState) => {
    const connection = item.connection;
    if (!connection?.id || !connection.connector_key) return;
    const isMcp =
      rawUserTools.find((tool) => tool.id === item.id)?.name === 'mcp_tool';
    signInAgain.reconnect(
      { id: connection.id, connector_key: connection.connector_key },
      isMcp ? item.id : undefined,
    );
  };

  const handleSaveDraft = async () => {
    if (savingRef.current) return;
    const saving = savePayload;
    const formData = new FormData();
    formData.append('name', agent.name);
    formData.append('description', agent.description);
    formData.append('starters', JSON.stringify(cleanStarters(agent.starters)));

    appendSourceFields(formData);

    formData.append('chunks', agent.chunks);
    formData.append('retriever', agent.retriever);
    formData.append('prompt_id', agent.prompt_id);
    formData.append('agent_type', agent.agent_type);
    formData.append('status', 'draft');
    formData.append('config', JSON.stringify(configToSave(agent.config)));

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

    if (effectiveMode === 'new' && validatedFolderId) {
      formData.append('folder_id', validatedFolderId);
    }

    try {
      savingRef.current = true;
      setDraftLoading(true);
      setSubmitError(null);
      const result = await sendAgent(
        formData,
        t('agents.form.errors.saveDraftFailed'),
      );
      if (result.status === 'cancelled') return;
      if (result.status === 'failed') {
        setSubmitError(result.message);
        return;
      }
      const data = await result.response.json();
      // What is on the agent now is what the tool picker keeps rows for.
      setAttachedTools(selectedTools);

      const saved = {
        id: data.id || agent.id,
        image: data.image || agent.image,
        // The stamp the next save sends.
        updated_at: data.updated_at ?? agent.updated_at,
      };
      // Edits made while the save was out stay.
      setAgent((prev) => ({ ...prev, ...saved }));
      initialAgentRef.current = { ...agent, ...saved };
      // What was sent is saved: the avatar went with it.
      markSaved(saving);
      setImageFile(null);

      if (effectiveMode === 'new') setEffectiveMode('draft');
    } catch (error) {
      console.error('Error saving draft:', error);
      setSubmitError(t('agents.form.errors.saveDraftFailed'));
    } finally {
      savingRef.current = false;
      setDraftLoading(false);
    }
  };

  const handlePublish = async () => {
    if (savingRef.current) return;
    const saving = savePayload;
    const formData = new FormData();
    formData.append('name', agent.name);
    formData.append('description', agent.description);
    formData.append('starters', JSON.stringify(cleanStarters(agent.starters)));

    appendSourceFields(formData);

    formData.append('chunks', agent.chunks);
    formData.append('retriever', agent.retriever);
    formData.append('prompt_id', agent.prompt_id);
    formData.append('agent_type', agent.agent_type);
    formData.append('status', 'published');
    formData.append('config', JSON.stringify(configToSave(agent.config)));

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

    if (effectiveMode === 'new' && validatedFolderId) {
      formData.append('folder_id', validatedFolderId);
    }

    try {
      savingRef.current = true;
      setPublishLoading(true);
      setSubmitError(null);
      const result = await sendAgent(
        formData,
        t('agents.form.errors.publishFailed'),
      );
      if (result.status === 'cancelled') return;
      if (result.status === 'failed') {
        setSubmitError(result.message);
        return;
      }
      const data = await result.response.json();

      const saved = {
        id: data.id || agent.id,
        key: data.key || agent.key,
        status: 'published',
        image: data.image || agent.image,
        updated_at: data.updated_at ?? agent.updated_at,
      };
      setAgent((prev) => ({ ...prev, ...saved }));
      const updatedAgent = { ...agent, ...saved };
      initialAgentRef.current = updatedAgent;
      markSaved(saving);
      setAttachedTools(selectedTools);
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
      savingRef.current = false;
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
    } catch {
      setJsonSchemaValid(false);
    }
  };

  // The caller's tools as the picker offers them, with what draws their rows;
  // resolves to the tools.
  const loadTools = useCallback(async (): Promise<UserToolType[]> => {
    const [toolsResponse, connectionsResult, catalogResult] = await Promise.all(
      [
        userService.getUserTools(token),
        connectorsService
          .listConnections(token)
          .catch(() => ({ connections: [] })),
        // Names a teammate's connected tool, whose connection the caller
        // never sees.
        connectorsService.getCatalog(token).catch(() => ({ connectors: [] })),
      ],
    );
    const ownConnections = (connectionsResult?.connections ??
      []) as Connection[];
    const catalog = (catalogResult?.connectors ?? []) as ConnectorDefinition[];
    if (!toolsResponse.ok) throw new Error('Failed to fetch tools');
    const data = await toolsResponse.json();
    // Hide workflow-only builtins (e.g. read_document) from the classic
    // agent picker; they belong to the workflow-node picker only.
    const visibleTools = (data.tools as UserToolType[]).filter(
      isAgentPickerToolVisible,
    );
    setRawUserTools(visibleTools);
    setToolContext({ connections: ownConnections, catalog });
    return visibleTools;
  }, [token]);

  useEffect(() => {
    loadTools().catch(() => undefined);
  }, [loadTools, toolsReloadKey]);

  // A tool made from the picker's Add tool goes on the agent.
  const attachCreated = useAttachAddedTools(loadTools);
  const handleToolsCreated = (toolIds: string[]) =>
    attachCreated(toolIds, (created) =>
      setSelectedTools((prev) => [
        ...prev,
        ...created
          .filter((tool) => !prev.some((item) => item.id === tool.id))
          .map((tool) => ({
            id: tool.id,
            name: tool.name,
            display_name: getToolDisplayName(tool),
          })),
      ]),
    );

  useEffect(() => {
    const getModels = async () => {
      const response = await modelService.getModels(token);
      if (!response.ok) throw new Error('Failed to fetch models');
      const data = await response.json();
      const transformed = modelService.transformModels(data.models || []);
      setAvailableModels(transformed);
      setSystemDefaultModelId(data.default_model_id || '');

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
          // The instance's model is where a new agent starts, not an edit.
          markSaved((base) =>
            base.models.length > 0
              ? base
              : {
                  ...base,
                  models: [preferredDefaultModelId],
                  default_model_id: preferredDefaultModelId,
                },
          );
        }
      }
    };
    getModels();
  }, [token, mode, markSaved]);

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

  // A new agent starts from the guardrails an admin set for new agents
  // (Admin › Defaults), unless the form already has some. The server copies
  // the same defaults in at creation, so this shows what the agent gets.
  useEffect(() => {
    if (mode !== 'new') return;
    let cancelled = false;
    userService
      .getAgentDefaults(token)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (cancelled || !data?.guardrails) return;
        setAgent((prev) =>
          prev.config?.guardrails
            ? prev
            : {
                ...prev,
                config: { ...(prev.config ?? {}), guardrails: data.guardrails },
              },
        );
        // Where a new agent starts, not an edit.
        markSaved((base) =>
          base.config.guardrails
            ? base
            : {
                ...base,
                config: { ...base.config, guardrails: data.guardrails },
              },
        );
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [mode, token, markSaved]);

  useEffect(() => {
    if ((mode === 'edit' || mode === 'draft') && agentId) {
      const getAgent = async () => {
        const response = await userService.getAgent(agentId, token);
        if (!response.ok) {
          navigate(agentsListPath());
          throw new Error('Failed to fetch agent');
        }
        const data = await response.json();
        // A workflow belongs in its own editor: this form offers no workflow
        // type, so saving here would turn it into a classic agent.
        if (mode === 'edit' && isWorkflowAgent(data)) {
          navigate(agentEditPath(agentId, true), { replace: true });
          return;
        }

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
          // The picked tools, as the tools effect below writes them: the
          // server's order, with deleted tools left out.
          tools: data.tool_details
            ? toolIdsOf(data.tool_details)
            : data.tools || [],
          ...serializeAgentSources(agentSourceIds, sourceDocs),
          models: agentModels,
          default_model_id: agentModels.includes(data.default_model_id || '')
            ? data.default_model_id
            : agentModels[0] || '',
          config: data.config || {},
        };
        setAgent(normalized);
        initialAgentRef.current = normalized;
        markSaved(
          agentSavePayload(
            normalized,
            data.json_schema ? JSON.stringify(data.json_schema, null, 2) : '',
          ),
        );
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
    setAgent((prev) => ({ ...prev, tools: toolIdsOf(selectedTools) }));
  }, [selectedTools]);

  useEffect(() => {
    // Editing a published agent: the preview talks to the saved version, so
    // Redux keeps that snapshot (the preview reads its model from it).
    const saved = effectiveMode === 'edit' ? initialAgentRef.current : null;
    if (saved) dispatch(setSelectedAgent(saved));
    else if (isPublishable()) dispatch(setSelectedAgent(agent));
  }, [agent, dispatch, effectiveMode, jsonSchemaText]);

  // The builder's own exits (a picker's Go to link, Upload's Browse
  // connectors) ask first while the form has unsaved changes.
  const leaveGuard = useLeaveGuard(hasChanges);
  // A broken connection signs in again in place, or on its connector page,
  // which is an exit like any other.
  const signInAgain = useSignInAgain({
    onConnected: () => {
      setToolsReloadKey((key) => key + 1);
      setDetailsReloadKey((key) => key + 1);
    },
    onNavigate: leaveGuard.leaveTo,
  });

  const isPublished = agent.status === 'published';
  // What the caller's role allows on this agent (`allowed_actions` from the
  // API). A new agent carries no access fields, so it reads as the owner's.
  const canEditPolicy = can(agent, 'edit_policy');
  // Save on a published agent is an edit; on a draft or a new agent the main
  // button publishes it.
  const canSubmit = can(agent, effectiveMode === 'edit' ? 'edit' : 'publish');
  const agentDisplayName =
    agent.name?.trim() || t('agents.pageHeader.fallbackName');

  // Page-level actions live in the ⋯ at the end of the toolbar row. Until the agent is
  // published the preview can only say "Publish to preview", so Preview is a
  // menu item then and a toolbar button after.
  // An agent this form created: the server added the admin's default
  // guardrails under what was sent, which the form may never have had (their
  // read failed, or landed after the save). An allowlist change replaces the
  // stored config whole, so it saves onto the server's copy.
  const readCreatedConfig = useCallback(async () => {
    const response = await userService.getAgent(agent.id ?? '', token);
    if (!response.ok) throw new Error('Failed to fetch agent');
    return ((await response.json()) as Agent).config;
  }, [agent.id, token]);

  const agentMenu = useAgentMenu({
    agent,
    lead: isPublished
      ? []
      : [
          {
            label: t('agents.form.sections.preview'),
            icon: Play,
            onClick: () => setPreviewOpen(true),
          },
        ],
    shareable: modeConfig[effectiveMode].showAccessDetails,
    openAccessDetails: (apiWrites) => {
      setDetailsOnApiWrites(apiWrites);
      setAgentDetails('ACTIVE');
    },
    onDeleted: navigateBackToAgents,
  });

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
          disabled={isDraftBlocked() || publishLoading}
          loading={draftLoading}
          onClick={handleSaveDraft}
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
          // Save on a published agent needs a change; Publish on a draft
          // or a new agent doesn't.
          disabled={
            !isPublishable() ||
            draftLoading ||
            (effectiveMode === 'edit' && !hasChanges)
          }
          loading={publishLoading}
          onClick={handlePublish}
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
    >
      {signInAgain.modals}
      {leaveGuard.dialog}
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
        menu={agentMenu.menu}
      >
        {submitError && (
          <Alert variant="destructive" className="mb-6">
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
              <KnowledgePicker
                open={isSourcePopupOpen}
                onOpenChange={setIsSourcePopupOpen}
                docs={sourceDocs ?? []}
                selectedIds={Array.from(selectedSourceIds)}
                onToggle={(id) => {
                  const next = new Set(selectedSourceIds);
                  if (next.has(id)) next.delete(id);
                  else next.add(id);
                  setSelectedSourceIds(next);
                }}
                connections={toolContext.connections}
                unlistedLabel={resolveSourceLabel}
                unlistedLine={sourceAddedBy}
                addedBy={sourceAddedBy}
                onNavigate={leaveGuard.onNavigate()}
                onUploaded={handleUploadedSource}
                onBrowseConnectors={() =>
                  leaveGuard.leaveTo('/settings/connectors?capability=sync')
                }
                onLeaveTo={leaveGuard.leaveTo}
                trigger={
                  <Button
                    type="button"
                    variant="combobox"
                    size="field"
                    role="combobox"
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
              <ToolsPicker
                open={isToolsPopupOpen}
                onOpenChange={setIsToolsPopupOpen}
                tools={rawUserTools}
                filter={isAgentPickerToolVisible}
                // What was on the agent when it loaded or last saved: the
                // owner's private tools don't come back in the caller's list.
                attached={attachedTools}
                attachedLine={t('agents.form.toolsPopup.attachedHint')}
                selectedIds={selectedTools.map((tool) => tool.id)}
                onToggle={(id) => {
                  if (selectedTools.some((tool) => tool.id === id)) {
                    setSelectedTools(
                      selectedTools.filter((tool) => tool.id !== id),
                    );
                    return;
                  }
                  const attached = attachedTools.find((tool) => tool.id === id);
                  const raw = rawUserTools.find((tool) => tool.id === id);
                  if (!attached && !raw) return;
                  setSelectedTools([
                    ...selectedTools,
                    attached ?? {
                      id,
                      name: raw!.name,
                      display_name: getToolDisplayName(raw!),
                    },
                  ]);
                }}
                connections={toolContext.connections}
                catalog={toolContext.catalog}
                addedBy={toolAddedBy}
                onReconnect={(connection, mcpToolId) =>
                  signInAgain.reconnect(connection, mcpToolId)
                }
                onNavigate={leaveGuard.onNavigate()}
                onReloadTools={() => setToolsReloadKey((key) => key + 1)}
                onToolsCreated={(toolIds) => void handleToolsCreated(toolIds)}
                onLeaveTo={leaveGuard.leaveTo}
                trigger={
                  <Button
                    type="button"
                    variant="combobox"
                    size="field"
                    role="combobox"
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
            <div className="flex flex-col sm:col-span-2">
              <FormField
                id={promptPickerId}
                label={t('agents.form.sections.prompt')}
                labelSurface="background"
              >
                <Combobox
                  open={isPromptPickerOpen}
                  onOpenChange={setIsPromptPickerOpen}
                  title={t('agents.form.sections.prompt')}
                  mobileSheet
                  filters={promptKinds.filters}
                  groups={promptGroups}
                  value={agent.prompt_id || 'default'}
                  valueOption={promptValueOption}
                  onValueChange={(id) =>
                    setAgent((prev) => ({ ...prev, prompt_id: id }))
                  }
                  placeholder={t('settings.prompts.select')}
                  searchPlaceholder={t('settings.prompts.searchPlaceholder')}
                  emptyText={t('settings.prompts.noPromptsFound')}
                  footer={({ close }) => (
                    <PickerFooter
                      to="/settings/prompts"
                      linkLabel={t('settings.prompts.manage')}
                      onNavigate={leaveGuard.onNavigate(close)}
                      actionLabel={t('settings.prompts.addPrompt')}
                      onAction={() => {
                        close();
                        setAddPromptModal('ACTIVE');
                      }}
                    />
                  )}
                />
              </FormField>
              {/* The mark of the picked prompt running with an editor's
                  access is a hint under the picker, seen without opening it. */}
              {promptAddedBy && (
                <p className="text-muted-foreground mt-1.5 text-xs">
                  {promptAddedBy}
                </p>
              )}
            </div>
            <ResourceStatusNotice
              agent={agent}
              readerId={readerId}
              stopped={stoppedResources}
              resolveName={resolveSponsoredName}
              takeovers={takeovers}
              onTakeOver={(item) => void takeOverResource(item)}
              onUndoTakeover={undoTakeover}
              onRemove={removeResource}
              onReconnect={reconnectResource}
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
                <SelectTrigger className="w-full" size="field">
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
                    role="combobox"
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
                  <SelectTrigger className="w-full" size="field">
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
          <SectionHeader
            title={t('agents.form.sections.starters')}
            description={t('agents.form.starters.description')}
          />
          <div className="flex flex-col gap-5">
            {Array.from(
              { length: MAX_STARTERS },
              (_, index) => agent.starters?.[index] ?? '',
            ).map((starter, index) => (
              <FormField
                key={index}
                labelSurface="background"
                label={t('agents.form.starters.label', { number: index + 1 })}
              >
                <Input
                  type="text"
                  value={starter}
                  maxLength={MAX_STARTER_LENGTH}
                  placeholder={
                    index === 0
                      ? t('agents.form.starters.placeholder')
                      : undefined
                  }
                  onChange={(e) => {
                    const next = Array.from(
                      { length: MAX_STARTERS },
                      (_, i) => agent.starters?.[i] ?? '',
                    );
                    next[index] = e.target.value;
                    setAgent({ ...agent, starters: next });
                  }}
                />
              </FormField>
            ))}
          </div>
        </Card>
        <Card variant="subtle" padding="lg" className="gap-5">
          {/* The heading wraps the toggle: a button's children are
              presentational, so a heading inside it is lost to screen readers.
              The card's gap-5 sits inside the body, so it folds away with it. */}
          <div>
            <h2>
              <CollapsibleTrigger
                look="section"
                open={isAdvancedSectionExpanded}
                onOpenChange={setIsAdvancedSectionExpanded}
                controls={advancedSectionId}
              >
                {t('agents.form.sections.advanced')}
              </CollapsibleTrigger>
            </h2>
            <Collapsible
              open={isAdvancedSectionExpanded}
              id={advancedSectionId}
            >
              <div className="pt-5">
                <FormField
                  labelSurface="background"
                  label={t('agents.form.advanced.jsonSchema')}
                  hint={t('agents.form.advanced.jsonSchemaDescription')}
                >
                  <Textarea
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
                  <ContextLimitRows
                    contextLimit={agent.config?.context_window_limit}
                    historyLimit={agent.config?.history_token_limit}
                    window={modelWindow}
                    disabled={!canEditPolicy}
                    onContextLimitChange={(limit) =>
                      setAgent((prev) => ({
                        ...prev,
                        config: {
                          ...(prev.config ?? {}),
                          context_window_limit: limit,
                        },
                      }))
                    }
                    onHistoryLimitChange={(limit) =>
                      setAgent((prev) => ({
                        ...prev,
                        config: {
                          ...(prev.config ?? {}),
                          history_token_limit: limit,
                        },
                      }))
                    }
                  />
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
                  <AllowedOriginsSetting
                    config={agent.config}
                    disabled={!canEditPolicy}
                    onChange={(origins) =>
                      setAgent({
                        ...agent,
                        config: { ...(agent.config ?? {}), ...origins },
                      })
                    }
                  />
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
            </Collapsible>
          </div>
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
        <AnalyticsSection
          value={agent.config?.analytics}
          token={token}
          agentId={agent.id || undefined}
          available={analyticsAvailability.enabled}
          maxTopics={analyticsAvailability.maxTopics}
          maxOverlapping={analyticsAvailability.maxOverlapping}
          // Not policy: anyone who can save the agent changes it.
          disabled={!canSubmit}
          onChange={(analytics) =>
            setAgent((prev) => ({
              ...prev,
              config: { ...(prev.config ?? {}), analytics },
            }))
          }
        />
      </div>
      {sponsoredSave.modal}
      {agentMenu.modals}
      <AgentDetailsModal
        agent={agent}
        mode={effectiveMode}
        modalState={agentDetails}
        setModalState={(state) => {
          setAgentDetails(state);
          if (state === 'INACTIVE') setDetailsOnApiWrites(false);
        }}
        openApiWrites={detailsOnApiWrites}
        onKeyRegenerated={(key) => setAgent((prev) => ({ ...prev, key }))}
        onConfigChange={(config, updatedAt) => {
          // The allowlist is saved already: record it on the saved snapshot
          // too, and keep any unsaved form edits to the rest of the config.
          // The save moved the stamp the next save sends.
          if (initialAgentRef.current)
            initialAgentRef.current = {
              ...initialAgentRef.current,
              config,
              updated_at: updatedAt ?? initialAgentRef.current.updated_at,
            };
          markSaved((base) => ({
            ...base,
            config: {
              ...base.config,
              api_write_allowlist: config.api_write_allowlist,
            },
          }));
          setAgent((prev) => ({
            ...prev,
            updated_at: updatedAt ?? prev.updated_at,
            config: {
              ...(prev.config ?? {}),
              api_write_allowlist: config.api_write_allowlist,
            },
          }));
        }}
        getSavedConfig={
          mode === 'new'
            ? readCreatedConfig
            : () => initialAgentRef.current?.config ?? agent.config
        }
      />
      <AddPromptModal
        prompts={prompts}
        isOpen={addPromptModal}
        onClose={() => setAddPromptModal('INACTIVE')}
        onSelect={(name: string, id: string) => {
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
                <Alert variant="info" role="note">
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
                    onClick={handlePublish}
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
