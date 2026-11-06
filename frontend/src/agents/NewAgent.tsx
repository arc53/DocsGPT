import {
  ArrowRight,
  BookOpen,
  CircleCheck,
  CircleMinus,
  CircleX,
  Eye,
  MessageSquare,
  Pencil,
  PencilLine,
  Play,
  Scissors,
  ShieldCheck,
  SquarePen,
  type LucideIcon,
} from 'lucide-react';
import React, {
  useCallback,
  useEffect,
  useMemo,
  useId,
  useRef,
  useState,
} from 'react';
import isEqual from 'lodash/isEqual';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import {
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Collapsible, CollapsibleTrigger } from '@/components/ui/collapsible';
import { MetaLine } from '@/components/ui/meta-line';
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
import ConfirmationModal from '../modals/ConfirmationModal';
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
import { canEditPrompt } from '../prompts/promptAccess';
import { PromptView } from '../prompts/PromptView';
import { usePromptDetail } from '../prompts/usePromptDetail';
import { usePickerKindFilter } from '../hooks/usePickerKindFilter';
import { useLeaveGuard } from '../hooks/useLeaveGuard';
import { useMediaQuery } from '../hooks';
import { DraftPanel } from '../drafter/DraftPanel';
import { suggestionIconClass } from '../hero/SuggestionRows';
import { DraftedField } from '../drafter/DraftedBadge';
import { DrafterStepRow, FilledRow } from '../drafter/DrafterStepRow';
import { DRAFTER_STARTERS } from '../drafter/starters';
import {
  ProposalSummary,
  type ProposalReasonRow,
} from '../drafter/ProposalSummary';
import { useDraftedFields } from '../drafter/useDraftedFields';
import { useDrafterConfig } from '../drafter/useDrafterConfig';
import { useDrafterSession } from '../drafter/useDrafterSession';
import { usePromptReview } from '../drafter/usePromptReview';
import { promptAsRead, type PromptEdit } from '../drafter/promptDraft';
import { WandButton } from '../drafter/WandButton';
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
import { cleanStarters } from './starters';
import StartersFields from './components/StartersFields';
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
import { BuildStepStrip } from './components/BuildStepStrip';
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
import {
  AGENT_BUILD_STEPS,
  AGENT_FIELD_LABEL_KEYS,
  AGENT_STEP_FIELDS,
  type AgentBuildStep,
  type AgentDraftField,
  type AgentDraftForm,
  type AgentLimitsValue,
  type PromptDraft,
  agentDraftContext,
  agentDraftValues,
  agentProposalSummary,
  agentStepResult,
  draftValueOf,
  isAgentFormEmpty,
  improveSuggestions,
  type ImproveSuggestion,
  isSafetyUnset,
  parseAgentProposal,
  planAgentPatch,
} from './agentDraft';
import { useAgentBuild } from './useAgentBuild';

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
const IMPROVE_ICONS: Record<ImproveSuggestion, LucideIcon> = {
  safety: ShieldCheck,
  knowledge: BookOpen,
  writePrompt: SquarePen,
  starters: MessageSquare,
  shorter: PencilLine,
  tightenPrompt: Scissors,
};

/** A field a proposal changed: what it held before and what the draft set. */
type AppliedChange = {
  field: AgentDraftField;
  previous: unknown;
  applied: unknown;
};

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

  /** Load the prompts the pickers read again (after a prompt is saved). */
  const reloadPrompts = () =>
    userService
      .getPrompts(token)
      .then((response: Response) => (response.ok ? response.json() : null))
      .then((list: Prompt[] | null) => {
        if (Array.isArray(list)) dispatch(setPrompts(list));
      })
      .catch((error: unknown) => console.error(error));

  // The prompt view (decision 64): a prompt shown in place of the form, the
  // form kept as it is under it. The drafter opens a prompt it wrote there
  // (`drafter`: Use this prompt saves it and sets it on the agent); the
  // picker's Add prompt and each row's Edit or View open one too (`picker`:
  // Save). A history entry makes browser Back return to the form.
  const location = useLocation();
  const [promptOrigin, setPromptOrigin] = useState<'drafter' | 'picker'>(
    'picker',
  );
  // The prompt the drafter wrote and the user hasn't used or turned down
  // yet: kept while the view is closed, so the drawer can open it again.
  const [promptDraft, setPromptDraft] = useState<PromptDraft | null>(null);
  // The prompt Use this prompt saved, with its text: a later draft while the
  // agent still uses it updates it instead of creating another.
  const usedPromptRef = useRef<{ prompt: Prompt; content: string } | null>(
    null,
  );
  // Use this prompt went through and nothing was sent since: the drawer
  // ends that turn with what it set and the step's Next.
  const [promptUsed, setPromptUsed] = useState(false);
  // Leaving the picker's view with unsaved text asks first.
  const [leavingPrompt, setLeavingPrompt] = useState(false);
  const promptDetail = usePromptDetail({
    prompts,
    onSaved: (saved) => handlePromptSaved(saved),
  });
  const promptViewOpen = promptDetail.target !== null;
  const promptValues = useMemo(
    () => ({ name: promptDetail.name, content: promptDetail.content }),
    [promptDetail.name, promptDetail.content],
  );
  const { setName: setPromptName, setContent: setPromptContent } = promptDetail;
  const promptDrafted = useDraftedFields<'name' | 'content'>(
    promptValues,
    (field, previous) =>
      (field === 'name' ? setPromptName : setPromptContent)(
        typeof previous === 'string' ? previous : '',
      ),
  );
  // The drafter's changes to a saved prompt, under review in the view.
  const promptReview = usePromptReview(setPromptContent, promptDrafted);
  // The prompt text the drafter reads: the open view's once loaded, with the
  // id of the saved prompt it shows (opened from a picker row, it needn't be
  // the agent's), else the drafter's unused prompt.
  const viewTargetId =
    promptDetail.target?.kind === 'edit' ? promptDetail.target.prompt.id : null;
  const draftOfPrompt: PromptDraft | null =
    promptViewOpen && promptDetail.status === 'ready'
      ? viewTargetId
        ? { ...promptValues, id: viewTargetId }
        : promptValues
      : promptDraft;

  const viewInHistory =
    (location.state as { promptView?: boolean } | null)?.promptView === true;
  // Each opening pushes the history entry Back pops, unless one is there.
  useEffect(() => {
    if (!promptViewOpen || viewInHistory) return;
    const state =
      location.state && typeof location.state === 'object'
        ? location.state
        : {};
    navigate(
      {
        pathname: location.pathname,
        search: location.search,
        hash: location.hash,
      },
      { state: { ...state, promptView: true } },
    );
  }, [promptDetail.key]);

  /** Close the view and drop its history entry. */
  const closePromptView = () => {
    promptReview.clear();
    promptDetail.close();
    if (viewInHistory) navigate(-1);
    // Back on the form where the prompt is picked.
    requestAnimationFrame(() =>
      document
        .getElementById(promptPickerId)
        ?.scrollIntoView?.({ block: 'center' }),
    );
  };

  /**
   * Back to the form (the crumb, or browser Back with `popped`): the
   * drafter's prompt stays in the step unsaved; unsaved text of the
   * picker's asks first.
   */
  const leavePromptView = (popped = false) => {
    if (promptOrigin === 'drafter') {
      setPromptDraft(promptValues);
      closePromptView();
    } else if (promptDetail.dirty) {
      // Browser Back already left the entry: put it back while asking.
      if (popped)
        navigate(
          {
            pathname: location.pathname,
            search: location.search,
            hash: location.hash,
          },
          { state: { promptView: true } },
        );
      setLeavingPrompt(true);
    } else closePromptView();
  };

  const wasInHistoryRef = useRef(viewInHistory);
  useEffect(() => {
    const was = wasInHistoryRef.current;
    wasInHistoryRef.current = viewInHistory;
    if (was && !viewInHistory && promptViewOpen) leavePromptView(true);
  }, [viewInHistory]);

  /** Open a prompt from the picker: to edit, or to read when the role can't. */
  const openPickerPrompt = (prompt: Prompt) => {
    setPromptOrigin('picker');
    promptDrafted.clear();
    promptDetail.open(prompt);
  };
  /** The picker's Add prompt. */
  const addPickerPrompt = () => {
    setPromptOrigin('picker');
    promptDrafted.clear();
    promptDetail.add();
  };
  /** A copy of a prompt the caller can't change, with the drawer open on it. */
  const improvePromptCopy = (prompt: Prompt) => {
    setPromptOrigin('picker');
    promptDrafted.clear();
    setDrafterOpen(true);
    void promptDetail.duplicate(prompt, { draft: true });
  };

  /**
   * Put a prompt the drafter wrote in the view: into the open one (a saved
   * prompt opened from the picker keeps its name), or a new view, which
   * updates the prompt this conversation already used while the agent
   * still has it. A prompt the caller can only read is never written into
   * (it has no Save): the new view takes its place. Each changed field is
   * marked Drafted with undo.
   */
  const showWrittenPrompt = (written: PromptDraft) => {
    if (promptViewOpen && !promptDetail.readOnly) {
      const keepsName =
        promptOrigin === 'picker' && promptDetail.target?.kind === 'edit';
      if (!keepsName && written.name && written.name !== promptDetail.name) {
        promptDrafted.mark('name', promptDetail.name, written.name);
        setPromptName(written.name);
      }
      if (written.content !== promptDetail.content) {
        promptDrafted.mark('content', promptDetail.content, written.content);
        setPromptContent(written.content);
      }
      return;
    }
    const used = usedPromptRef.current;
    const updates =
      used && draftFormRef.current.prompt === used.prompt.id ? used : null;
    const previous =
      promptDraft ??
      (updates
        ? { name: updates.prompt.name, content: updates.content }
        : { name: '', content: '' });
    setPromptOrigin('drafter');
    promptDetail.openWith(written, updates?.prompt);
    if (written.name !== previous.name)
      promptDrafted.mark('name', previous.name, written.name);
    if (written.content !== previous.content)
      promptDrafted.mark('content', previous.content, written.content);
    setPromptDraft(written);
  };

  // Changes to a saved prompt wait for its text when the view loads it
  // (`raw`: the proposal they came in).
  const [pendingEdits, setPendingEdits] = useState<{
    raw: object;
    id: string;
    edits: PromptEdit[];
  } | null>(null);
  // How many of a proposal's changes fit the text, for its summary.
  const fittingRef = useRef(new WeakMap<object, number>());
  /**
   * Review the drafter's changes on the open prompt's text, those that fit
   * it as the server reads it.
   */
  const reviewPromptEdits = (raw: object, edits: PromptEdit[]) => {
    const fitting = promptReview.start(
      edits,
      promptAsRead(promptDetail.content),
      promptDetail.content,
    );
    fittingRef.current.set(raw, fitting);
    if (fitting === 0)
      drafterSession.addMessage(t('drafter.agent.prompt.editsStale'));
  };
  // They belong to that opening: a view closed or showing another prompt
  // drops them, so opening the prompt later shows no stale review. A load
  // error keeps them for the view's Retry.
  useEffect(() => {
    if (!pendingEdits) return;
    if (viewTargetId !== pendingEdits.id) setPendingEdits(null);
    else if (promptDetail.status === 'ready') {
      setPendingEdits(null);
      reviewPromptEdits(pendingEdits.raw, pendingEdits.edits);
    }
  }, [pendingEdits, promptDetail.status, promptDetail.key, viewTargetId]);

  /**
   * Show the drafter's changes to the agent's own saved prompt: in its view
   * when that is open, else it opens (loading its saved text and version)
   * and the review starts once the text is in. The drawer stays the
   * agent's; nothing is saved until the view's Save.
   */
  const showPromptEdits = (raw: object, id: string, edits: PromptEdit[]) => {
    if (viewTargetId === id && promptDetail.status === 'ready') {
      reviewPromptEdits(raw, edits);
      return;
    }
    const prompt = prompts.find((item) => item.id === id);
    if (!prompt) {
      drafterSession.addMessage(t('drafter.agent.prompt.editsStale'));
      return;
    }
    setPendingEdits({ raw, id, edits });
    setPromptOrigin('picker');
    promptDrafted.clear();
    promptDetail.open(prompt);
  };

  /** Turn the drafter's unused prompt down: the agent keeps its prompt. */
  const dropPromptDraft = () => {
    if (promptViewOpen && promptOrigin === 'drafter') closePromptView();
    setPromptDraft(null);
    promptDrafted.clear();
  };

  /** Open the drafter's unused prompt again (the drawer's Open prompt). */
  const reopenPromptDraft = () => {
    if (!promptDraft) return;
    const used = usedPromptRef.current;
    setPromptOrigin('drafter');
    promptDetail.openWith(
      promptDraft,
      used && draftFormRef.current.prompt === used.prompt.id
        ? used.prompt
        : undefined,
    );
  };

  /**
   * A save in the view went through: the pickers' list has it at once.
   * The drafter's prompt is set on the agent (marked Drafted, undo puts the
   * old one back) and the drawer says so; a prompt added from the picker is
   * picked.
   */
  const handlePromptSaved = ({ id, name }: { id: string; name: string }) => {
    const created = promptDetail.target?.kind === 'new';
    const listed = prompts.find((prompt) => prompt.id === id);
    dispatch(
      setPrompts(
        listed
          ? prompts.map((prompt) =>
              prompt.id === id ? { ...prompt, name } : prompt,
            )
          : [...prompts, { id, name, type: 'private' }],
      ),
    );
    void reloadPrompts();
    if (promptOrigin === 'drafter') {
      usedPromptRef.current = {
        prompt: listed ? { ...listed, name } : { id, name, type: 'private' },
        content: promptDetail.content,
      };
      const previous = draftFormRef.current.prompt;
      if (previous !== id) {
        writeDraftField('prompt', id);
        drafted.mark('prompt', previous, id);
      }
      setPromptDraft(null);
      setPromptUsed(true);
      const starters = drafted.isDrafted('starters')
        ? cleanStarters(draftFormRef.current.starters).length
        : 0;
      drafterSession.addMessage(
        starters > 0
          ? t('drafter.agent.prompt.saved', { count: starters })
          : t('drafter.agent.prompt.savedOnly'),
      );
    } else if (created) setAgent((prev) => ({ ...prev, prompt_id: id }));
    promptDrafted.clear();
    closePromptView();
  };

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

  // The drafter ("Draft with DocsGPT"): it reads the form, and each proposal
  // fills it as unsaved edits, every changed field marked Drafted with undo.
  // On an empty new agent it builds the agent step by step (useAgentBuild).
  const drafterConfig = useDrafterConfig();
  const { isMobile } = useMediaQuery();
  const [drafterOpen, setDrafterOpen] = useState(false);
  const formColumnRef = useRef<HTMLDivElement>(null);
  // Hidden while the server says it is off, and from anyone who can't edit.
  // A saved agent's form holds a stub with no access fields (read as the
  // owner's) until the agent loads: nothing shows before then.
  const accessKnown = mode === 'new' || initialAgentRef.current !== null;
  const drafterEnabled =
    drafterConfig?.enabled === true && accessKnown && can(agent, 'edit');

  const draftForm = useMemo<AgentDraftForm>(
    () => ({
      name: agent.name ?? '',
      description: agent.description ?? '',
      agent_type: agent.agent_type ?? '',
      sources: Array.from(selectedSourceIds),
      tools: selectedTools,
      starters: agent.starters ?? [],
      prompt: agent.prompt_id || 'default',
      limits: {
        limited_request_mode: Boolean(agent.limited_request_mode),
        request_limit: agent.request_limit,
        limited_token_mode: Boolean(agent.limited_token_mode),
        token_limit: agent.token_limit,
      },
      guardrails: agent.config?.guardrails,
      analytics: analyticsOf(agent.config?.analytics),
    }),
    [
      agent.name,
      agent.description,
      agent.agent_type,
      agent.starters,
      agent.prompt_id,
      agent.limited_request_mode,
      agent.request_limit,
      agent.limited_token_mode,
      agent.token_limit,
      agent.config?.guardrails,
      agent.config?.analytics,
      selectedSourceIds,
      selectedTools,
    ],
  );
  // What each message sends and each proposal applies onto: the form now.
  const draftFormRef = useRef(draftForm);
  draftFormRef.current = draftForm;
  const draftValues = useMemo(() => agentDraftValues(draftForm), [draftForm]);

  /** Write one drafted field (a draft's value, or undo's previous one). */
  const writeDraftField = useCallback(
    (field: AgentDraftField, value: unknown) => {
      switch (field) {
        case 'sources':
          setSelectedSourceIds(new Set(value as string[]));
          return;
        case 'tools':
          setSelectedTools(value as ToolSummary[]);
          return;
        case 'prompt':
          setAgent((prev) => ({ ...prev, prompt_id: value as string }));
          return;
        case 'starters':
          setAgent((prev) => ({ ...prev, starters: value as string[] }));
          return;
        case 'limits':
          setAgent((prev) => ({ ...prev, ...(value as AgentLimitsValue) }));
          return;
        case 'guardrails':
        case 'analytics':
          setAgent((prev) => ({
            ...prev,
            config: { ...(prev.config ?? {}), [field]: value },
          }));
          return;
        default:
          setAgent((prev) => ({ ...prev, [field]: value as string }));
      }
    },
    [],
  );
  const drafted = useDraftedFields<AgentDraftField>(
    draftValues,
    writeDraftField,
  );

  // Tools a draft can name: the caller's, and those already on the agent.
  const draftToolOptions = useMemo<ToolSummary[]>(
    () => [
      ...rawUserTools.map((tool) => ({
        id: tool.id,
        name: tool.name,
        display_name: getToolDisplayName(tool),
      })),
      ...attachedTools,
    ],
    [rawUserTools, attachedTools],
  );

  // The fields each proposal changed when it was applied, so its summary
  // gives reasons only for those and notes a later edit by hand (keyed by
  // the session's proposal object).
  const appliedRef = useRef(new WeakMap<object, AppliedChange[]>());
  const appliedFields = (raw: unknown): AgentDraftField[] | undefined =>
    raw && typeof raw === 'object'
      ? appliedRef.current.get(raw)?.map((change) => change.field)
      : undefined;
  // The latest reason for each field a build drafted: a finished step's
  // folded line opens them.
  const buildRowsRef = useRef(new Map<AgentDraftField, ProposalReasonRow>());

  /** Bring the first drafted field into view, after the form has drawn it. */
  const scrollToDrafted = () =>
    requestAnimationFrame(() =>
      formColumnRef.current
        ?.querySelector('[data-drafted]')
        ?.scrollIntoView?.({ block: 'center', behavior: 'smooth' }),
    );

  /** Fill the form from a proposal, marking every field it changed. */
  const applyDraft = (raw: unknown) => {
    const proposal = parseAgentProposal(raw);
    if (!proposal) return;
    const changes = planAgentPatch(
      proposal.fields,
      draftFormRef.current,
      draftToolOptions,
    );
    const changed = changes.map((change) => change.field);
    appliedRef.current.set(
      raw as object,
      changes.map((change) => ({
        field: change.field,
        previous: draftValueOf(change.field, change.previous),
        applied: draftValueOf(change.field, change.next),
      })),
    );
    changes.forEach((change) => {
      writeDraftField(change.field, change.next);
      drafted.mark(
        change.field,
        change.previous,
        draftValueOf(change.field, change.next),
      );
    });
    proposal.reasons.forEach((reason) => {
      const field = reason.field as AgentDraftField;
      if (changed.includes(field))
        buildRowsRef.current.set(field, {
          key: field,
          label: t(AGENT_FIELD_LABEL_KEYS[field]),
          summary: reason.summary,
        });
    });
    // A prompt it wrote opens in the prompt view; one of the caller's picked
    // instead turns a written one down. A drafted limit shows in Advanced.
    const prompt = proposal.fields.prompt;
    if (prompt?.kind === 'new')
      showWrittenPrompt({ name: prompt.name, content: prompt.content });
    else if (prompt?.kind === 'edit')
      showPromptEdits(raw as object, prompt.id, prompt.edits);
    else if (prompt?.kind === 'existing') dropPromptDraft();
    if (changed.includes('limits')) setIsAdvancedSectionExpanded(true);
    if (changed.length > 0 && buildRef.current.guided) scrollToDrafted();
    // An approval while the prompt it wrote is unused isn't the step's
    // Next: the prompt waits for Use this prompt or Keep. (One with parts
    // the server dropped is no approval.)
    const approval =
      Object.keys(proposal.fields).length === 0 &&
      proposal.dropped.length === 0;
    if (approval && promptDraft) return;
    buildRef.current.onProposal(proposal);
  };

  const drafterSession = useDrafterSession({
    recipe: 'agent',
    getContext: () => {
      // A new request ends an open review with the choices so far.
      promptReview.finish(promptDetail.content);
      return agentDraftContext(
        agent.id || null,
        draftFormRef.current,
        buildRef.current.context(),
        draftOfPrompt,
      );
    },
    onProposal: applyDraft,
  });
  // The session as it is now, for a save that ends after a turn began.
  const drafterSessionRef = useRef(drafterSession);
  drafterSessionRef.current = drafterSession;

  // A step can't be drafted when nothing in it is the caller's to set: the
  // limits and guardrails need policy access, the topics need Insights.
  const skippedSteps = useMemo<AgentBuildStep[]>(
    () =>
      !can(agent, 'edit_policy') && !analyticsAvailability.enabled
        ? ['safety']
        : [],
    [agent, analyticsAvailability.enabled],
  );
  const stepName = (step: AgentBuildStep) =>
    t(`drafter.agent.build.steps.${step}`);
  const build = useAgentBuild({
    session: drafterSession,
    skipped: skippedSteps,
    continueText: (step) =>
      t('drafter.agent.build.continue', {
        step: stepName(step),
        interpolation: { escapeValue: false },
      }),
    doneText: t('drafter.agent.build.done'),
    // Changes to a prompt under review, or on their way to it, come first.
    hold: promptReview.review !== null || pendingEdits !== null,
  });
  const buildRef = useRef(build);
  buildRef.current = build;

  const formEmpty = isAgentFormEmpty(draftForm);
  // Draft on an empty new agent builds it step by step; anything else is
  // improve mode, free-form.
  const buildable = formEmpty && !agent.id && !build.guided;
  const finishSetupText = t('drafter.agent.improve.finishSetup');
  // What the panel sends: the first message on an empty new agent starts the
  // build, and Finish setup asks for limits and safety alone.
  const panelSession = {
    ...drafterSession,
    send: (text: string, options?: { hidden?: boolean }) => {
      if (text === finishSetupText) build.focus('safety');
      else if (buildable && drafterSession.items.length === 0) build.start();
      setPromptUsed(false);
      drafterSession.send(text, options);
    },
  };
  /** The step's Next: the saved prompt's turn end goes with the step. */
  const goNext = () => {
    setPromptUsed(false);
    build.next();
  };

  const draftedProps = (field: AgentDraftField) => ({
    drafted: drafted.isDrafted(field),
    onUndo: () => drafted.undo(field),
    fieldLabel: t(AGENT_FIELD_LABEL_KEYS[field]),
  });

  /** Close the drawer and bring the first drafted field into view. */
  const checkForm = () => {
    setDrafterOpen(false);
    scrollToDrafted();
  };

  const nextLabel = build.nextStep
    ? t('drafter.agent.build.next', {
        step: stepName(build.nextStep),
        interpolation: { escapeValue: false },
      })
    : t('drafter.agent.build.finish');

  // The step's Next, and Check the form first when it filled steps ahead.
  const nextActions = (
    <>
      <Button
        type="button"
        size="sm"
        shape="pill"
        disabled={drafterSession.streaming}
        onClick={goNext}
      >
        {nextLabel}
        {build.nextStep && <ArrowRight />}
      </Button>
      {build.filledAhead && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          shape="pill"
          onClick={checkForm}
        >
          {t('drafter.agent.build.checkForm')}
        </Button>
      )}
    </>
  );
  // Next waits while the prompt the drafter wrote is unused, and moves to
  // the end of the turn once Use this prompt saved it.
  const nextOnProposal =
    build.ready && !promptDraft && !promptUsed && !promptReview.review;

  /** "You changed Name in the form.": fields the proposal set, edited since. */
  const editedSince = (raw: unknown) => {
    const changes =
      raw && typeof raw === 'object' ? appliedRef.current.get(raw) : undefined;
    const edited = (changes ?? []).filter(
      ({ field, previous, applied }) =>
        !isEqual(draftValues[field], applied) &&
        !isEqual(draftValues[field], previous),
    );
    return edited.length > 0
      ? t('drafter.agent.formEdited', {
          fields: edited
            .map(({ field }) => t(AGENT_FIELD_LABEL_KEYS[field]))
            .join(', '),
          interpolation: { escapeValue: false },
        })
      : undefined;
  };

  const renderAgentProposal = (raw: unknown, latest: boolean) => {
    const proposal = parseAgentProposal(raw);
    if (!proposal) return null;
    const { rows, dropped } = agentProposalSummary(
      proposal,
      t,
      appliedFields(raw),
      raw && typeof raw === 'object' ? fittingRef.current.get(raw) : undefined,
    );
    const written = proposal.fields.prompt;
    // What a written or changed prompt does to the one it replaces first.
    const notes =
      written?.kind === 'new' || written?.kind === 'edit'
        ? [
            ...written.checks.map((code) => t(`drafter.prompt.checks.${code}`)),
            ...proposal.notes,
            t(
              written.kind === 'new'
                ? 'drafter.agent.prompt.viewHint'
                : 'drafter.agent.prompt.reviewHint',
            ),
          ]
        : proposal.notes;
    const review = promptReview.review;
    // The latest turn ends a review open from its own changes, or from
    // those that waited for the prompt to load.
    const reviewing = latest && review !== null;
    // Fields it changed on the form behind the prompt view.
    const showInAgent =
      latest && promptViewOpen && (appliedFields(raw) ?? []).length > 0 ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          shape="pill"
          onClick={() => {
            leavePromptView();
            scrollToDrafted();
          }}
        >
          {t('drafter.agent.showInAgent')}
        </Button>
      ) : null;
    return (
      <ProposalSummary
        message={proposal.message}
        rows={rows}
        notes={notes}
        dropped={dropped}
        footnote={
          latest && !drafterSession.streaming ? editedSince(raw) : undefined
        }
        actions={
          reviewing ? (
            <>
              <Button
                type="button"
                size="sm"
                shape="pill"
                onClick={promptReview.acceptAll}
              >
                {t('drafter.prompt.acceptAll')}
              </Button>
              {review.current === null && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  shape="pill"
                  onClick={promptReview.reviewOneByOne}
                >
                  {t('drafter.prompt.reviewOneByOne')}
                </Button>
              )}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                shape="pill"
                onClick={promptReview.discard}
              >
                {t('drafter.prompt.discard')}
              </Button>
              {showInAgent}
            </>
          ) : latest && nextOnProposal ? (
            <>
              {nextActions}
              {showInAgent}
            </>
          ) : (
            (showInAgent ?? undefined)
          )
        }
      />
    );
  };

  // What the drawer adds after the conversation: the saved prompt's turn
  // end (what it set, and the step's Next), or the prompt it wrote waiting
  // unsaved while the form shows (Open prompt, or keep the agent's prompt).
  const drawerAfter = promptUsed ? (
    <ProposalSummary
      rows={[
        {
          key: 'prompt',
          label: t(AGENT_FIELD_LABEL_KEYS.prompt),
          summary: pickedPromptLabel,
        },
        ...(drafted.isDrafted('starters')
          ? [
              {
                key: 'starters',
                label: t(AGENT_FIELD_LABEL_KEYS.starters),
                summary: t('drafter.agent.build.result.starters', {
                  count: cleanStarters(agent.starters).length,
                }),
              },
            ]
          : []),
      ]}
      actions={build.ready ? nextActions : undefined}
    />
  ) : promptDraft && !promptViewOpen ? (
    <ProposalSummary
      message={t('drafter.agent.prompt.parked')}
      rows={[]}
      actions={
        <>
          <Button
            type="button"
            size="sm"
            shape="pill"
            onClick={reopenPromptDraft}
          >
            {t('drafter.agent.prompt.open')}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            shape="pill"
            onClick={dropPromptDraft}
          >
            {t('drafter.agent.prompt.keep', {
              name: pickedPromptLabel,
              interpolation: { escapeValue: false },
            })}
          </Button>
        </>
      }
    />
  ) : undefined;

  // After a Stop or an error the step goes on from where it stands.
  const continueAction =
    build.guided && build.step ? (
      <Button
        type="button"
        size="sm"
        shape="pill"
        onClick={() =>
          panelSession.send(
            t('drafter.agent.build.continue', {
              step: stepName(build.step!),
              interpolation: { escapeValue: false },
            }),
            { hidden: true },
          )
        }
      >
        {t('drafter.agent.build.continueStep', {
          step: stepName(build.step),
          interpolation: { escapeValue: false },
        })}
        <ArrowRight />
      </Button>
    ) : undefined;

  const progressLabel = build.done
    ? t('drafter.agent.build.allFilled')
    : [
        t('drafter.agent.build.progress', {
          number: build.number,
          total: build.total,
          step: build.step ? stepName(build.step) : '',
          interpolation: { escapeValue: false },
        }),
        build.filledAtOnce > 0 &&
          t('drafter.agent.build.filledAtOnce', { count: build.filledAtOnce }),
      ]
        .filter(Boolean)
        .join(' · ');
  const progress = build.guided
    ? {
        label: progressLabel,
        value: build.done
          ? 100
          : (build.finished.filter((step) => !build.skipped.includes(step))
              .length /
              build.total) *
            100,
      }
    : null;

  /** A finished step's folded line opens the reasons for its fields. */
  const stepRows = (step: AgentBuildStep) =>
    AGENT_STEP_FIELDS[step].flatMap((field) => {
      const row = buildRowsRef.current.get(field);
      return row ? [row] : [];
    });
  const stepResult = (step: AgentBuildStep) =>
    agentStepResult(step, draftForm, t, pickedPromptLabel);
  // Skipped steps the build has passed, each one line.
  const passedSkips = build.skipped.filter(
    (step) =>
      build.done ||
      (build.step &&
        AGENT_BUILD_STEPS.indexOf(step) <
          AGENT_BUILD_STEPS.indexOf(build.step)),
  );
  const foldedSteps =
    build.guided && (build.finished.length > 0 || passedSkips.length > 0) ? (
      <div className="flex flex-col" data-slot="build-finished">
        {!build.done && build.finished.length >= 3 ? (
          // Three or more steps fold into one line that opens a row each.
          <DrafterStepRow
            icon={CircleCheck}
            label={build.finished.map(stepName).join(', ')}
          >
            {build.finished.map((step) => (
              <FilledRow
                key={step}
                label={stepName(step)}
                value={stepResult(step)}
              />
            ))}
          </DrafterStepRow>
        ) : (
          build.finished.map((step) => {
            const rows = stepRows(step);
            return (
              <DrafterStepRow
                key={step}
                icon={CircleCheck}
                label={t('drafter.agent.build.folded', {
                  step: stepName(step),
                  result: stepResult(step),
                  interpolation: { escapeValue: false },
                })}
              >
                {rows.length > 0
                  ? rows.map((row) => (
                      <FilledRow
                        key={row.key}
                        label={row.label}
                        value={row.summary}
                      />
                    ))
                  : undefined}
              </DrafterStepRow>
            );
          })
        )}
        {passedSkips.map((step) => (
          <DrafterStepRow
            key={step}
            icon={CircleMinus}
            label={t('drafter.agent.build.skipped', {
              step: stepName(step),
              interpolation: { escapeValue: false },
            })}
          />
        ))}
      </div>
    ) : undefined;

  // A phone's sheet covers the form: when a turn ends on a proposal the
  // sheet steps aside (once per proposal), and a step's Next waits in the
  // strip.
  const steppedAsideRef = useRef<number | null>(null);
  useEffect(() => {
    const last = drafterSession.items.at(-1);
    if (
      !isMobile ||
      drafterSession.streaming ||
      last?.kind !== 'proposal' ||
      steppedAsideRef.current === last.id
    )
      return;
    steppedAsideRef.current = last.id;
    const changed = appliedFields(last.proposal);
    // A prompt it wrote is in the view, which the sheet would cover.
    const wrote =
      parseAgentProposal(last.proposal)?.fields.prompt?.kind === 'new';
    if (wrote || (build.guided ? build.ready : (changed?.length ?? 0) > 0))
      setDrafterOpen(false);
  }, [
    drafterSession.streaming,
    drafterSession.items,
    isMobile,
    build.guided,
    build.ready,
  ]);
  const showStepStrip =
    isMobile &&
    !drafterOpen &&
    build.ready &&
    !promptDraft &&
    !drafterSession.streaming;

  /** "Drafted 3 fields…" for a screen reader once a draft is applied. */
  const announceAgentProposal = (raw: unknown) => {
    const count = appliedFields(raw)?.length ?? 0;
    return count > 0 ? t('drafter.agent.draftedCount', { count }) : null;
  };

  const handleSaveDraft = async () => {
    if (savingRef.current) return;
    const saving = savePayload;
    // Drafted values that go with the save lose their marks; a draft that
    // lands while it is out keeps its.
    const savedValues = draftValues;
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
      drafted.clear(savedValues);

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
    const savedValues = draftValues;
    const turnsAtSave = drafterSession.items.length;
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
      drafted.clear(savedValues);
      // Publishing ends a drafting session, unless a turn began while it
      // was out: that conversation and what it drafted stay.
      const session = drafterSessionRef.current;
      if (!session.streaming && session.items.length === turnsAtSave) {
        session.reset();
        build.reset();
        buildRowsRef.current.clear();
        setPromptDraft(null);
        setPromptUsed(false);
        usedPromptRef.current = null;
        promptDrafted.clear();
      }
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
  // The prompt view's unsaved text counts too.
  const leaveGuard = useLeaveGuard(
    hasChanges ||
      promptDraft !== null ||
      (promptViewOpen && promptDetail.dirty),
  );
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

  // A drafted limit marks the row it switched on, or both rows when it
  // turned limits off.
  const limitRowDrafted = (row: 'request' | 'token') =>
    drafted.isDrafted('limits') &&
    (row === 'request'
      ? !!agent.limited_request_mode || !agent.limited_token_mode
      : !!agent.limited_token_mode || !agent.limited_request_mode);

  // The drawer's greeting: the build's plan on an empty new agent; on a
  // filled one what to change, and who a saved change reaches.
  const drafterIntro = buildable
    ? t('drafter.agent.build.intro')
    : t(
        isPublished
          ? 'drafter.agent.improve.introPublished'
          : agent.shared || agent.ownership === 'team'
            ? 'drafter.agent.improve.introShared'
            : 'drafter.agent.improve.intro',
        { name: agentDisplayName, interpolation: { escapeValue: false } },
      );
  const drafterSuggestions = (
    buildable
      ? // Starting points: each sends its title and begins the build from
        // its id, so every step gets that kind of agent's brief.
        DRAFTER_STARTERS.map(({ key, Icon }) => {
          const text = t(`drafter.starters.${key}.title`);
          return {
            key,
            Icon,
            text,
            description: t(`drafter.starters.${key}.description`),
            onSelect: () => {
              build.start(key);
              panelSession.send(text);
            },
          };
        })
      : // What the agent lacks first, then what fits it; Finish setup is
        // offered until limits and safety were ever set.
        improveSuggestions(draftForm, {
          safety: isSafetyUnset(draftForm) && !skippedSteps.includes('safety'),
          promptDraft: !!draftOfPrompt,
        }).map((key) => ({
          key,
          Icon: IMPROVE_ICONS[key],
          text:
            key === 'safety'
              ? finishSetupText
              : t(`drafter.agent.improve.${key}`),
        }))
  ).map(({ Icon, ...suggestion }) => ({
    ...suggestion,
    icon: <Icon className={suggestionIconClass} aria-hidden="true" />,
  }));

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
  // The drawer's entry, on the toolbar and on the prompt view's crumb row.
  const wandProps = {
    mode:
      build.guided && !build.done
        ? ('resume' as const)
        : formEmpty
          ? ('draft' as const)
          : ('improve' as const),
    label:
      build.guided && !build.done
        ? t('drafter.agent.build.resumeLabel', {
            number: build.number,
            total: build.total,
          })
        : undefined,
    open: drafterOpen,
    compactOnPhone: true,
  };

  // The open prompt as the list has it (a built-in says so in the byline).
  const viewTarget = promptDetail.target;
  const viewSaved = viewTarget?.kind === 'edit' ? viewTarget.prompt : null;
  const viewBuiltIn = viewSaved?.type === 'public';
  const promptViewByline =
    promptOrigin === 'picker'
      ? viewBuiltIn
        ? t('modals.prompts.viewDescription')
        : viewTarget?.kind === 'new' && viewTarget.copyOf
          ? t('modals.prompts.duplicateDescription', {
              name: viewTarget.copyOf,
              interpolation: { escapeValue: false },
            })
          : null
      : null;
  const promptView = viewTarget ? (
    <PromptView
      parent={{
        label: agent.name?.trim() || t('agents.newAgent'),
        onClick: () => leavePromptView(),
      }}
      label={
        viewSaved
          ? viewSaved.name
          : promptOrigin === 'drafter'
            ? t('drafter.agent.prompt.newPrompt')
            : viewTarget.kind === 'new' && viewTarget.copyOf
              ? t('modals.prompts.duplicatePrompt')
              : t('modals.prompts.addPrompt')
      }
      actions={
        <>
          {drafterEnabled && (
            <WandButton
              {...wandProps}
              open={promptDetail.readOnly ? undefined : drafterOpen}
              onClick={() =>
                // A prompt the caller can't change is improved as a copy.
                promptDetail.readOnly && viewSaved
                  ? improvePromptCopy(viewSaved)
                  : setDrafterOpen((open) => !open)
              }
            />
          )}
          {!promptDetail.readOnly && (
            <Button
              type="button"
              size="field"
              shape="pill"
              onClick={() => void promptDetail.save()}
              // Mid-review the text holds only the changes chosen so far:
              // the drawer's Accept all or Discard ends it first.
              disabled={
                !promptDetail.canSave ||
                drafterSession.streaming ||
                promptReview.review !== null
              }
              loading={promptDetail.saving}
            >
              {promptOrigin === 'drafter'
                ? t('drafter.agent.prompt.use')
                : t('modals.prompts.save')}
            </Button>
          )}
        </>
      }
      byline={promptViewByline ? <MetaLine>{promptViewByline}</MetaLine> : null}
      loading={promptDetail.status === 'loading'}
      onRetry={promptDetail.status === 'error' ? promptDetail.retry : undefined}
      idPrefix="agent-prompt"
      name={promptDetail.name}
      setName={setPromptName}
      content={promptDetail.content}
      setContent={setPromptContent}
      isReadOnly={promptDetail.readOnly}
      showViewOnlyNotice={promptDetail.readOnly && !viewBuiltIn}
      review={promptReview.review}
      onDecide={promptReview.decide}
      draftedName={{
        drafted: promptDrafted.isDrafted('name'),
        onUndo: () => promptDrafted.undo('name'),
      }}
      draftedContent={{
        drafted: promptDrafted.isDrafted('content'),
        onUndo: () => promptDrafted.undo('content'),
      }}
      nameError={
        promptDetail.nameExists && promptDetail.name
          ? t('modals.prompts.nameExists')
          : undefined
      }
      locked={drafterSession.streaming}
    />
  ) : null;

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
      {drafterEnabled && (
        <WandButton
          {...wandProps}
          onClick={() => setDrafterOpen((open) => !open)}
        />
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
          // Stretched while the toolbar's row is stacked (by its width, so
          // also beside the docked drawer).
          className="flex-1 @2xl:flex-none"
        >
          {modeConfig[effectiveMode].buttonText}
        </Button>
      )}
    </div>
  );

  return (
    // The drafter's docked panel sits beside the page's scroller, not in it.
    <div className="relative flex h-full overflow-hidden">
      <div className="h-full min-w-0 flex-1">
        <SectionShell
          title={effectiveMode === 'new' ? t('agents.newAgent') : undefined}
        >
          {signInAgain.modals}
          {leaveGuard.dialog}
          {promptView}
          {/* Hidden, not unmounted, under the prompt view: the form keeps
          every unsaved part of itself. */}
          <div className={promptViewOpen ? 'hidden' : 'contents'}>
            <AgentPageToolbar
              intro={agent.id ? undefined : t('agents.form.byline.new')}
              name={agentDisplayName}
              status={
                isPublished ? (
                  <Badge variant="success">
                    {t('agents.form.status.published')}
                  </Badge>
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
            <div ref={formColumnRef} className="flex flex-col gap-5">
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
                  <DraftedField {...draftedProps('name')}>
                    <FormField
                      labelSurface="background"
                      label={t('agents.form.labels.name')}
                    >
                      <Input
                        type="text"
                        value={agent.name}
                        placeholder={t('agents.form.placeholders.agentName')}
                        onChange={(e) => {
                          const name = e.target.value;
                          setAgent((prev) => ({ ...prev, name }));
                        }}
                      />
                    </FormField>
                  </DraftedField>
                  <DraftedField
                    {...draftedProps('description')}
                    className="col-span-2 sm:col-span-1 sm:col-start-2"
                  >
                    <FormField
                      labelSurface="background"
                      label={t('agents.form.labels.description')}
                    >
                      <Textarea
                        className="h-32 sm:h-24"
                        placeholder={t(
                          'agents.form.placeholders.describeAgent',
                        )}
                        value={agent.description}
                        onChange={(e) => {
                          const description = e.target.value;
                          setAgent((prev) => ({ ...prev, description }));
                        }}
                      />
                    </FormField>
                  </DraftedField>
                </div>
              </Card>
              <Card variant="subtle" padding="lg" className="gap-5">
                <SectionHeader title={t('agents.form.sections.knowledge')} />
                <div className="grid grid-cols-1 gap-x-4 gap-y-5 sm:grid-cols-2">
                  <DraftedField {...draftedProps('sources')}>
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
                          leaveGuard.leaveTo(
                            '/settings/connectors?capability=sync',
                          )
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
                  </DraftedField>
                  <DraftedField {...draftedProps('tools')}>
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
                          const attached = attachedTools.find(
                            (tool) => tool.id === id,
                          );
                          const raw = rawUserTools.find(
                            (tool) => tool.id === id,
                          );
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
                        onReloadTools={() =>
                          setToolsReloadKey((key) => key + 1)
                        }
                        onToolsCreated={(toolIds) =>
                          void handleToolsCreated(toolIds)
                        }
                        onLeaveTo={leaveGuard.leaveTo}
                        trigger={
                          <Button
                            type="button"
                            variant="combobox"
                            size="field"
                            role="combobox"
                            id={toolsPickerId}
                            ref={toolAnchorButtonRef}
                            data-placeholder={
                              selectedTools.length > 0 ? undefined : ''
                            }
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
                  </DraftedField>
                  <div className="flex flex-col">
                    <DraftedField {...draftedProps('prompt')}>
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
                          // Any listed prompt opens in the prompt view
                          // from its row, without picking it.
                          rowAction={(option) => {
                            const prompt = prompts.find(
                              (item) => item.id === option.value,
                            );
                            if (!prompt) return undefined;
                            const editable = canEditPrompt(prompt);
                            return {
                              label: t(
                                editable
                                  ? 'settings.prompts.editNamed'
                                  : 'settings.prompts.viewNamed',
                                {
                                  name: prompt.name,
                                  interpolation: { escapeValue: false },
                                },
                              ),
                              icon: editable ? <Pencil /> : <Eye />,
                              onSelect: () => openPickerPrompt(prompt),
                            };
                          }}
                          placeholder={t('settings.prompts.select')}
                          searchPlaceholder={t(
                            'settings.prompts.searchPlaceholder',
                          )}
                          emptyText={t('settings.prompts.noPromptsFound')}
                          footer={({ close }) => (
                            <PickerFooter
                              to="/settings/prompts"
                              linkLabel={t('settings.prompts.manage')}
                              onNavigate={leaveGuard.onNavigate(close)}
                              actionLabel={t('settings.prompts.addPrompt')}
                              onAction={() => {
                                close();
                                addPickerPrompt();
                              }}
                            />
                          )}
                        />
                      </FormField>
                    </DraftedField>
                    {/* The mark of the prompt running with an editor's
                  access is a hint, seen without opening the picker. */}
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
                  <DraftedField {...draftedProps('agent_type')}>
                    <FormField
                      labelSurface="background"
                      label={t('agents.form.sections.agentType')}
                    >
                      <Select
                        value={agent.agent_type || undefined}
                        onValueChange={(value) =>
                          setAgent((prev) => ({ ...prev, agent_type: value }))
                        }
                      >
                        <SelectTrigger className="w-full" size="field">
                          <SelectValue
                            placeholder={t(
                              'agents.form.placeholders.selectType',
                            )}
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
                  </DraftedField>
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
                        const userLabel = t(
                          'settings.customModels.modelsGroup.user',
                        );
                        const builtin: MultiSelectPopoverItem[] = [];
                        const user: MultiSelectPopoverItem[] = [];
                        availableModels.forEach((model) => {
                          const opt: MultiSelectPopoverItem = {
                            id: model.id,
                            label: model.display_name,
                            group:
                              model.source === 'user'
                                ? userLabel
                                : builtinLabel,
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
                      emptyMessage={t(
                        'agents.form.modelsPopup.noOptionsMessage',
                      )}
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
                <DraftedField {...draftedProps('starters')}>
                  <StartersFields
                    starters={agent.starters ?? []}
                    onChange={(starters) =>
                      setAgent((prev) => ({ ...prev, starters }))
                    }
                  />
                </DraftedField>
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
                          onChange={(e) =>
                            validateAndSetJsonSchema(e.target.value)
                          }
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
                            jsonSchemaValid
                              ? 'text-success'
                              : 'text-destructive',
                          )}
                        >
                          {jsonSchemaValid ? (
                            <CircleCheck
                              className="size-4"
                              aria-hidden="true"
                            />
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
                          drafted={limitRowDrafted('token')}
                          onUndo={() => drafted.undo('limits')}
                          after={
                            <DraftedField
                              {...draftedProps('limits')}
                              drafted={
                                limitRowDrafted('token') &&
                                !!agent.limited_token_mode
                              }
                            >
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
                                disabled={
                                  !agent.limited_token_mode || !canEditPolicy
                                }
                                placeholder={t(
                                  'agents.form.placeholders.enterTokenLimit',
                                )}
                                aria-label={t(
                                  'agents.form.advanced.tokenLimit',
                                )}
                              />
                            </DraftedField>
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
                          drafted={limitRowDrafted('request')}
                          onUndo={() => drafted.undo('limits')}
                          after={
                            <DraftedField
                              {...draftedProps('limits')}
                              drafted={
                                limitRowDrafted('request') &&
                                !!agent.limited_request_mode
                              }
                            >
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
                                disabled={
                                  !agent.limited_request_mode || !canEditPolicy
                                }
                                placeholder={t(
                                  'agents.form.placeholders.enterRequestLimit',
                                )}
                                aria-label={t(
                                  'agents.form.advanced.requestLimit',
                                )}
                              />
                            </DraftedField>
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
                drafted={drafted.isDrafted('guardrails')}
                onUndo={() => drafted.undo('guardrails')}
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
                drafted={drafted.isDrafted('analytics')}
                onUndo={() => drafted.undo('analytics')}
                onChange={(analytics) =>
                  setAgent((prev) => ({
                    ...prev,
                    config: { ...(prev.config ?? {}), analytics },
                  }))
                }
              />
              {/* Room for the phone's step strip under the last section. */}
              {showStepStrip && <div aria-hidden="true" className="h-20" />}
            </div>
            {showStepStrip && build.step && (
              <BuildStepStrip
                title={t('drafter.agent.build.check', {
                  step: stepName(build.step),
                  interpolation: { escapeValue: false },
                })}
                line={progressLabel}
                nextLabel={
                  build.nextStep
                    ? t('drafter.agent.build.nextShort')
                    : t('drafter.agent.build.finish')
                }
                onOpen={() => setDrafterOpen(true)}
                onNext={goNext}
              />
            )}
          </div>
          {leavingPrompt && (
            <ConfirmationModal
              message={t('settings.prompts.unsavedChanges')}
              modalState="ACTIVE"
              setModalState={(state) => setLeavingPrompt(state === 'ACTIVE')}
              submitLabel={t('settings.prompts.saveAndLeave')}
              // Pending while the save runs; a refused save rejects, so its
              // error stays in this dialog and the view stays. A prompt that
              // can't be saved yet (no name) just stays.
              handleSubmit={async () => {
                if (!promptDetail.canSave || promptReview.review !== null) {
                  setLeavingPrompt(false);
                  return;
                }
                const result = await promptDetail.save({ quiet: true });
                if (result !== 'saved') throw new Error(result);
                setLeavingPrompt(false);
              }}
              error={(reason) =>
                reason instanceof Error && reason.message === 'conflict'
                  ? t('settings.prompts.editConflict')
                  : t('settings.prompts.saveFailed')
              }
              cancelLabel={t('settings.prompts.leaveWithoutSaving')}
              handleCancel={() => {
                setLeavingPrompt(false);
                promptDrafted.clear();
                closePromptView();
              }}
            />
          )}
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
      </div>
      {drafterEnabled && (
        <DraftPanel
          open={drafterOpen}
          onOpenChange={setDrafterOpen}
          session={panelSession}
          modelName={drafterConfig?.model?.display_name ?? null}
          announceProposal={announceAgentProposal}
          intro={drafterIntro}
          placeholder={
            buildable
              ? t('drafter.agent.build.describePlaceholder')
              : promptViewOpen
                ? t('drafter.agent.prompt.changePlaceholder')
                : build.guided && !build.done
                  ? t('drafter.agent.build.changePlaceholder')
                  : undefined
          }
          progress={progress}
          before={foldedSteps}
          suggestions={drafterSuggestions}
          renderProposal={renderAgentProposal}
          continueAction={continueAction}
          after={drawerAfter}
          onNavigate={leaveGuard.onNavigate()}
        />
      )}
    </div>
  );
}
