import { nanoid } from '@reduxjs/toolkit';
import { Database, Plug } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import { envVar } from '@/env';
import { baseURL } from '../api/client';
import connectorsService from '../api/services/connectorsService';
import userService from '../api/services/userService';
import { useConnectorAuth } from '../components/ConnectorAuth';
import { FilePicker } from '../components/FilePicker';
import GoogleDrivePicker from '../components/GoogleDrivePicker';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Avatar } from '../components/ui/avatar';
import { Button } from '../components/ui/button';
import { Collapsible, CollapsibleTrigger } from '../components/ui/collapsible';
import { FormField } from '../components/ui/form-field';
import { Input } from '../components/ui/input';
import { Modal, ModalActions } from '../components/ui/modal';
import { OptionCard } from '../components/ui/option-card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { Separator } from '../components/ui/separator';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import { Switch } from '../components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import {
  setConversation,
  updateConversationId,
} from '../conversation/conversationSlice';
import {
  selectToken,
  setSelectedAgent,
  setSelectedDocs,
} from '../preferences/preferenceSlice';
import RetrievalOptions, {
  isPrescreenConfigValid,
  optionsToConfig,
  sourceHasFileLinks,
} from '../settings/components/RetrievalOptions';
import useNewSourceOptions from '../settings/components/useNewSourceOptions';
import useRetrievalAvailability from '../settings/components/useRetrievalAvailability';
import { knowledgeLink } from '../settings/knowledgeLink';
import type { AppDispatch } from '../store';
import { formatCount } from '../utils/dateTimeUtils';
import { ACCOUNT_NAME_MAX } from './accounts';
import ConnectorIcon from './ConnectorIcon';
import CredentialForm, { credentialsComplete } from './CredentialForm';
import {
  loadConnectors,
  selectConnections,
  syncStarted,
} from './connectorsSlice';
import { connectorDescription, connectorName, isKeyHint } from './i18n';
import { isMcpOpenPreset, reconnectsInPlace } from './launchRules';
import LinearPicker, {
  EMPTY_LINEAR_SELECTION,
  linearSourceName,
  linearSyncItems,
  type LinearSelection,
} from './LinearPicker';
import RepoPicker from './RepoPicker';
import ToolPermissions from './ToolPermissions';
import useMcpOAuth, { type McpOAuthConfig } from './useMcpOAuth';
import type {
  ConnectionTool,
  ConnectorAuthKind,
  ConnectorDefinition,
} from './types';

export type WizardMode = 'connect' | 'reconnect' | 'sync' | 'done';

type McpSaveConfig =
  McpOAuthConfig | { server_url: string; auth_type: 'none'; timeout: number };

/**
 * Why the wizard opened. `knowledge` (Add knowledge, Knowledge's Connect a
 * service) starts a first connect with Sync into Knowledge on; `tools`, or
 * none, leaves it off for the user to choose.
 */
export type LaunchPurpose = 'knowledge' | 'tools';

const FREQUENCIES = ['never', 'daily', 'weekly', 'monthly'] as const;
const PICKER_CONNECTORS = new Set([
  'google_drive',
  'share_point',
  'confluence',
]);

type CreatedSource = { id: string; name: string };

/**
 * The one connect flow every entry point opens: sign in, choose what to set
 * up, then a summary whose footer follows what happened (Open in Knowledge,
 * Try it in chat, Sync content, or Done). A sync-only connector (S3, Drive,
 * SharePoint, Confluence, Reddit) offers two ways on, "Sync content now"
 * (picked) or "Just connect", with what to sync and its retrieval settings
 * under them. A connector with tools
 * and sync (GitHub, Linear) asks with a switch each (sync on when opened for
 * Knowledge). Tool connectors create their tools on sign-in, writes needing
 * approval, so they go from the credentials straight to the summary. Every
 * run that connects something ends on the summary.
 *
 * Args:
 *   onClose: Called as the wizard closes, with whether this run created or
 *     repaired a connection (a saved account, a reconnect, a sync set up);
 *     false on a plain cancel.
 */
export default function ConnectWizard({
  connector,
  mode: initialMode = 'connect',
  connectionId: initialConnectionId = null,
  mcpToolId,
  purpose,
  onClose,
  onFinished,
  onSynced,
}: {
  connector: ConnectorDefinition;
  mode?: WizardMode;
  connectionId?: string | null;
  /** Reconnecting an MCP preset: the tool to update rather than add. */
  mcpToolId?: string;
  purpose?: LaunchPurpose;
  onClose: (connected: boolean) => void;
  onFinished?: () => void;
  /** The ids of the sources a sync just started, still ingesting. */
  onSynced?: (sourceIds: string[]) => void;
}) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const connections = useSelector(selectConnections);
  const name = connectorName(t, connector);

  // A picker whose sign-in expired switches the wizard to reconnect, then
  // back to the mode it came from (`resumeMode`).
  const [mode, setMode] = useState<WizardMode>(initialMode);
  const [resumeMode, setResumeMode] = useState<WizardMode | null>(null);
  // The account a sync step is fixed to: the opener's, or the one this run
  // connected once its summary offers Sync content. Without one, Sync more
  // from Add knowledge asks which account when there are several.
  const [fixedConnectionId, setFixedConnectionId] = useState<string | null>(
    initialConnectionId,
  );
  const [step, setStep] = useState<'signin' | 'setup' | 'done'>(
    initialMode === 'sync'
      ? 'setup'
      : initialMode === 'done'
        ? 'done'
        : 'signin',
  );
  const [connectionId, setConnectionId] = useState<string | null>(
    initialConnectionId,
  );
  // Whether this run saved, repaired or set up a connection (onClose's
  // argument). A finished MCP save opens the wizard on the summary.
  const connectedRef = useRef(initialMode === 'done');
  // The account as the sign-in reported it, before the connections reload.
  const [accountLabel, setAccountLabel] = useState('');
  // Bumped to remount the pickers after a reconnect or an account switch.
  const [pickerKey, setPickerKey] = useState(0);
  const [mcpReconnectToolId, setMcpReconnectToolId] = useState(mcpToolId);
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [accountName, setAccountName] = useState('');
  const [setupValues, setSetupValues] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [tools, setTools] = useState<ConnectionTool[]>([]);
  const [sources, setSources] = useState<CreatedSource[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [selectedFolders, setSelectedFolders] = useState<string[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string | null>(null);
  const [linearSelection, setLinearSelection] = useState<LinearSelection>(
    EMPTY_LINEAR_SELECTION,
  );
  // A connector that asks about its tools (GitHub) offers them switched on.
  const [toolsOn, setToolsOn] = useState(true);
  const [toolsOpen, setToolsOpen] = useState(false);
  const toolsId = useId();
  // Changes (GitHub's issues, comments, pull requests) are an opt-in on top.
  const [writesOn, setWritesOn] = useState(false);
  const [chosenMethod, setChosenMethod] = useState<ConnectorAuthKind | null>(
    null,
  );
  const [sourceName, setSourceName] = useState('');
  const [nameTouched, setNameTouched] = useState(false);
  const [frequency, setFrequency] = useState(
    connector.default_sync_frequency || 'weekly',
  );
  // One key per setup: a double click on Add source queues one ingest. A
  // sync started from the summary (Sync content) is a new setup.
  const [idempotencyKey, setIdempotencyKey] = useState(() => nanoid());

  // Sync more from Add knowledge names no account when the service has
  // several: the first setup field picks one (the first, until changed).
  const serviceAccounts = connections.filter(
    (c) => c.connector_key === connector.key && c.status === 'connected',
  );
  const pickingAccount = mode === 'sync' && !fixedConnectionId;
  const activeConnectionId =
    connectionId ?? (pickingAccount ? (serviceAccounts[0]?.id ?? null) : null);
  const chooseAccount = pickingAccount && serviceAccounts.length > 1;
  const connection = connections.find((c) => c.id === activeConnectionId);
  const canSync = connector.setup.sync !== 'off' && !!connector.sync_ingestor;
  // A first connect asks whether to sync into Knowledge; Sync more is only
  // about syncing, so it never asks.
  const askSync = canSync && mode === 'connect';
  // Syncing is the only reason to connect it (S3, Drive): the setup step
  // offers Sync content now (picked, from any entry point) or Just connect.
  // A connector with tools too (GitHub, Linear) asks with switches.
  const syncOnly = canSync && connector.setup.tools === 'off';
  const [syncOn, setSyncOn] = useState(syncOnly || purpose === 'knowledge');
  const syncing = canSync && (mode === 'sync' || syncOn);
  const { value: retrievalOptions, setValue: setRetrievalOptions } =
    useNewSourceOptions(token, step === 'setup' && syncing);
  const { graphRAGAvailable, hybridAvailable, availableModels, decision } =
    useRetrievalAvailability(token, step === 'setup' && syncing);
  // Tools the user opts into while choosing what to sync, not on sign-in.
  const offerTools =
    connector.setup.tools === 'ask' &&
    connector.tool_templates.length > 0 &&
    mode !== 'sync';
  // GitHub signs in two ways: Sign in with GitHub (when an admin set up the
  // GitHub App) or a token. Reconnecting keeps the connection's own way.
  const methods = connector.sign_in_methods?.length
    ? connector.sign_in_methods
    : [connector.auth_kind];
  const method: ConnectorAuthKind =
    mode === 'reconnect' && connection?.auth_kind
      ? connection.auth_kind
      : (chosenMethod ?? methods[0]);
  const usesOAuth = method === 'oauth';

  // A finished MCP save or a reconnect lands here with only the connection id.
  useEffect(() => {
    if (initialMode !== 'done' || !initialConnectionId) return;
    connectorsService.getConnection(initialConnectionId, token).then((data) => {
      if (data?.success) setTools(data.connection.tools ?? []);
    });
  }, [initialMode, initialConnectionId, token]);

  const refresh = () => dispatch(loadConnectors({ token }));

  const close = () => onClose(connectedRef.current);

  /** After a reconnect started from a picker: back to what it was doing. */
  const resumeAfterReconnect = () => {
    if (!resumeMode) return false;
    setMode(resumeMode);
    setResumeMode(null);
    // The file pickers keep their selection to themselves and remount
    // empty, so drop what they reported. The repository and Linear pickers
    // are drawn from the wizard's value and show it again.
    setSelectedFiles([]);
    setSelectedFolders([]);
    setPickerKey((key) => key + 1);
    setError('');
    setStep('setup');
    return true;
  };

  // A name tells two accounts of one service apart ("Alerts bot"). It is
  // set once the account exists, so it works the same for keys and sign-ins.
  const canName =
    mode === 'connect' &&
    (connector.auth_kind === 'api_key' || connector.auth_kind === 'oauth');

  const afterSignIn = async (id: string, label = '') => {
    setConnectionId(id);
    connectedRef.current = true;
    if (label) setAccountLabel(label);
    const name = accountName.trim();
    if (canName && name) {
      try {
        await connectorsService.renameConnection(id, name, token);
      } catch {
        // The account works without a name; it can be named in the drawer.
      }
    }
    // The summary names the account: wait for it rather than show a gap.
    await refresh();
    if (mode === 'reconnect') {
      if (!resumeAfterReconnect()) setStep('done');
      return;
    }
    if (connector.setup.tools === 'auto' && connector.tool_templates.length) {
      const setup = await connectorsService.setup(
        id,
        { create_tools: true },
        token,
      );
      if (setup?.success) setTools(setup.tools ?? []);
    }
    setStep(canSync || offerTools ? 'setup' : 'done');
  };

  // MCP presets (Notion, Linear…) sign in over MCP OAuth: no URL or auth
  // form, just "Sign in to Notion". The tool is saved on success, and the
  // done step shows what it can do (for Linear, after choosing what to sync).
  const isMcpPreset =
    connector.auth_kind === 'mcp_oauth' && !!connector.mcp_url;
  const isOpenMcp = isMcpOpenPreset(connector);
  const mcp = useMcpOAuth();
  const mcpConfig = (): McpOAuthConfig => ({
    server_url: connector.mcp_url ?? '',
    auth_type: 'oauth',
    oauth_scopes: connector.oauth_scopes ?? [],
    timeout: 30,
    redirect_uri: `${baseURL.replace(/\/$/, '')}/api/mcp_server/callback`,
  });

  const saveMcp = async (config: McpSaveConfig, taskId: string | null) => {
    setPending(true);
    try {
      const response = await userService.saveMCPServer(
        {
          displayName: name,
          config:
            config.auth_type === 'none'
              ? config
              : { ...config, oauth_task_id: taskId ?? '' },
          status: true,
          ...(mcpReconnectToolId && { id: mcpReconnectToolId }),
        },
        token,
      );
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error);
      connectedRef.current = true;
      let savedConnectionId: string | null = null;
      try {
        const list = await connectorsService.listConnections(token);
        const saved = (
          (list?.connections ?? []) as {
            id: string;
            connector_key: string;
            updated_at: string | null;
          }[]
        )
          .filter((c) => c.connector_key === connector.key)
          .sort((a, b) =>
            (b.updated_at ?? '').localeCompare(a.updated_at ?? ''),
          )[0];
        if (saved) {
          savedConnectionId = saved.id;
          setConnectionId(saved.id);
          const detail = await connectorsService.getConnection(saved.id, token);
          if (detail?.success) {
            setTools(detail.connection.tools ?? []);
            if (detail.connection.account_label)
              setAccountLabel(detail.connection.account_label);
          }
        }
      } catch {
        // The server is saved; summary fetches must not turn that into a failure.
      }
      await refresh();
      if (mode === 'reconnect' && resumeAfterReconnect()) return;
      // One sign-in also syncs (Linear): choosing what to sync comes next.
      setStep(
        canSync && savedConnectionId && mode === 'connect' ? 'setup' : 'done',
      );
    } catch (err) {
      setError(
        (err instanceof Error && err.message) ||
          t('settings.tools.mcp.errors.saveFailed'),
      );
    } finally {
      setPending(false);
    }
  };

  const connectOpenMcp = () => {
    setError('');
    saveMcp(
      {
        server_url: connector.mcp_url ?? '',
        auth_type: 'none',
        timeout: 30,
      },
      null,
    );
  };

  const startMcpSignIn = () => {
    setError('');
    const config = mcpConfig();
    mcp.start(config, {
      onDone: ({ taskId }) => saveMcp(config, taskId),
      onError: (message) =>
        setError(message || t('settings.tools.mcp.errors.oauthFailed')),
    });
  };

  const startSignIn = useConnectorAuth({
    provider: connector.key,
    connectionId:
      mode === 'reconnect' ? (activeConnectionId ?? undefined) : undefined,
    onSuccess: (data) => afterSignIn(data.connection_id),
    onError: setError,
  });

  const submitCredentials = async () => {
    setPending(true);
    setError('');
    try {
      const data =
        mode === 'reconnect' && activeConnectionId
          ? await connectorsService.reconnect(
              activeConnectionId,
              { credentials },
              token,
            )
          : await connectorsService.createConnection(
              { connector_key: connector.key, credentials },
              token,
            );
      if (!data?.success) {
        setError(
          data?.code === 'encryption_key_default'
            ? t('settings.connectors.error.defaultKey')
            : data?.code === 'invalid_credentials'
              ? t('settings.connectors.wizard.credentialsRejected', {
                  name,
                  interpolation: { escapeValue: false },
                })
              : t('settings.connectors.wizard.connectFailed'),
        );
        return;
      }
      await afterSignIn(
        data.connection.id,
        data.connection.account_label ?? '',
      );
    } catch {
      setError(t('settings.connectors.wizard.connectFailed'));
    } finally {
      setPending(false);
    }
  };

  const prefillName = (picked: string) => {
    if (!nameTouched && picked) setSourceName((current) => current || picked);
  };

  const isRepoPicker = connector.key === 'github';
  const isLinearPicker = connector.sync_ingestor === 'linear';
  const syncItems = (): Record<string, unknown> =>
    PICKER_CONNECTORS.has(connector.key)
      ? { file_ids: selectedFiles, folder_ids: selectedFolders }
      : isRepoPicker
        ? { repo_url: selectedRepo }
        : isLinearPicker
          ? linearSyncItems(linearSelection)
          : setupValues;

  const hasSyncSelection = PICKER_CONNECTORS.has(connector.key)
    ? selectedFiles.length + selectedFolders.length > 0
    : isRepoPicker
      ? !!selectedRepo
      : isLinearPicker
        ? linearSelection.teams.length + linearSelection.projects.length > 0
        : credentialsComplete(connector.setup_fields, setupValues);
  const wantsTools = offerTools && toolsOn;
  const offerWrites = wantsTools && !!connector.writes_allowed;
  const wantsWrites = offerWrites && writesOn;
  const syncReady = syncing && hasSyncSelection;
  // Off, there is nothing to pick: the button only finishes setting up.
  // On, it reads Add to Knowledge, so something must be picked, and an
  // incoherent prescreen config blocks it as in Upload; the backend would
  // refuse it.
  const canAddSource =
    !syncing || (hasSyncSelection && isPrescreenConfigValid(retrievalOptions));

  const toggleSync = (on: boolean) => {
    setSyncOn(on);
    // The file pickers start over when shown again; drop what they reported.
    if (!on) {
      setSelectedFiles([]);
      setSelectedFolders([]);
    }
  };

  /**
   * A refused setup in the user's language, by its code: the server's own
   * words are English, so a code without a key reads as the generic failure.
   */
  const setupRefusal = (code: unknown): string => {
    const named = { name, interpolation: { escapeValue: false } };
    switch (code) {
      case 'tools_unavailable':
        return t('settings.connectors.wizard.toolsUnavailable', named);
      case 'writes_forbidden':
        return t('settings.connectors.github.writesForbidden');
      // The account's sign-in stopped working since the wizard opened.
      case 'reconnect':
        return t('settings.connectors.wizard.setupReconnect', named);
      // An admin turned the connector (an MCP preset) off meanwhile.
      case 'disabled':
        return t('settings.connectors.wizard.setupDisabled', named);
      default:
        return t('settings.connectors.detail.syncFailed');
    }
  };

  const addSource = async () => {
    if (!activeConnectionId) return;
    if (!wantsTools && !syncReady) {
      // Connected, nothing more to set up.
      setStep('done');
      return;
    }
    setPending(true);
    setError('');
    try {
      const data = await connectorsService.setup(
        activeConnectionId,
        {
          create_tools: wantsTools,
          ...(wantsWrites && { allow_writes: true }),
          ...(syncReady && {
            sync: {
              items: syncItems(),
              frequency,
              name: sourceName.trim() || undefined,
              config: optionsToConfig(retrievalOptions),
            },
          }),
        },
        token,
        idempotencyKey,
      );
      if (!data?.success) {
        setError(setupRefusal(data?.code));
        return;
      }
      connectedRef.current = true;
      if (wantsTools) setTools(data.tools ?? []);
      const created: CreatedSource[] = data.sources ?? [];
      setSources(created);
      if (created.length) {
        // The drawer lists them as indexing until the server does.
        const startedAt = new Date().toISOString();
        dispatch(
          syncStarted(
            created.map((source) => ({
              id: source.id,
              name: source.name,
              connectionId: activeConnectionId,
              startedAt,
            })),
          ),
        );
        onSynced?.(created.map((source) => source.id));
      }
      refresh();
      setStep('done');
    } catch {
      setError(t('settings.connectors.detail.syncFailed'));
    } finally {
      setPending(false);
    }
  };

  // Offered only when the run turned tools on and synced nothing (a new
  // source opens in Knowledge instead), so the chat starts over no sources:
  // never the ones the last chat had picked.
  const tryInChat = () => {
    dispatch(setConversation([]));
    dispatch(updateConversationId({ query: { conversationId: null } }));
    dispatch(setSelectedAgent(null));
    dispatch(setSelectedDocs([]));
    onFinished?.();
    close();
    navigate('/c/new');
  };

  const finish = () => {
    onFinished?.();
    close();
  };

  /** Opens the first source this run created in Knowledge. */
  const openInKnowledge = () => {
    const [first] = sources;
    onFinished?.();
    close();
    if (first) navigate(knowledgeLink({ sourceId: first.id }));
  };

  /** Drops what the pickers hold and remounts them empty. */
  const clearPicks = () => {
    setSelectedFiles([]);
    setSelectedFolders([]);
    setSelectedRepo(null);
    setLinearSelection(EMPTY_LINEAR_SELECTION);
    setPickerKey((key) => key + 1);
  };

  /** From a summary with nothing synced: the sync step, in place. */
  const syncContent = () => {
    setFixedConnectionId(activeConnectionId);
    setMode('sync');
    setSyncOn(true);
    setSources([]);
    // A new setup over pickers that remount empty: anything picked before
    // Just connect folded the form away is dropped, not synced unseen.
    clearPicks();
    setError('');
    setIdempotencyKey(nanoid());
    setStep('setup');
  };

  /** A picker's sign-in expired: sign the same account in again. */
  const reconnectFromPicker = async () => {
    if (!activeConnectionId) return;
    setConnectionId(activeConnectionId);
    setResumeMode(mode);
    setMode('reconnect');
    setError('');
    setStep('signin');
    // An MCP preset's reconnect updates its saved tool rather than adding one.
    if (isMcpPreset && !mcpReconnectToolId) {
      const detail = await connectorsService.getConnection(
        activeConnectionId,
        token,
      );
      const tool = (
        detail?.connection?.tools as ConnectionTool[] | undefined
      )?.find((item) => item.name === 'mcp_tool');
      if (tool) setMcpReconnectToolId(tool.id);
    }
  };
  const onReconnect = reconnectsInPlace(connector)
    ? reconnectFromPicker
    : undefined;

  const switchAccount = (id: string) => {
    setConnectionId(id);
    clearPicks();
  };

  // The account in words: its name, the key it was made with, or its label.
  const account = connection?.account_label || accountLabel;
  const accountText = (() => {
    const named = connection?.account_name;
    if (named) return named;
    if (!account) return '';
    return isKeyHint(account)
      ? t('settings.connectors.detail.keyEnding', {
          hint: account,
          interpolation: { escapeValue: false },
        })
      : account;
  })();

  // The account as a sentence: the key a pasted-key account was made with
  // ("Connected with the key ending …1c26."), else who signed in.
  const accountSentence = !accountText
    ? ''
    : !connection?.account_name && isKeyHint(account)
      ? t('settings.connectors.wizard.connectedWithKey', {
          hint: account,
          interpolation: { escapeValue: false },
        })
      : mode === 'sync'
        ? accountText
        : t('settings.connectors.wizard.signedInAs', {
            account: accountText,
            interpolation: { escapeValue: false },
          });

  const toolCount = tools.length;
  const summary = useMemo(() => {
    // Never "Connected as ." while the account is unknown: say nothing.
    const accountLine = !account
      ? ''
      : isKeyHint(account)
        ? t('settings.connectors.wizard.connectedWithKey', {
            hint: account,
            interpolation: { escapeValue: false },
          })
        : t('settings.connectors.wizard.doneSummaryNone', {
            account,
            interpolation: { escapeValue: false },
          });
    const sourcesText = t('settings.connectors.wizard.sourcesCount', {
      count: sources.length,
      formatted: formatCount(sources.length),
    });
    const toolsText = t('settings.connectors.wizard.toolsCount', {
      count: toolCount,
      formatted: formatCount(toolCount),
    });
    const countsLine =
      sources.length && toolCount
        ? t('settings.connectors.wizard.doneCounts', {
            sources: sourcesText,
            tools: toolsText,
          })
        : sources.length
          ? t('settings.connectors.wizard.doneSources', {
              sources: sourcesText,
            })
          : toolCount
            ? t('settings.connectors.wizard.doneTools', { tools: toolsText })
            : '';
    // A new account that syncs nothing yet says so; the footer's Sync
    // content is the way on, so the line gives no directions.
    const syncLine =
      mode === 'connect' && canSync && sources.length === 0
        ? t('settings.connectors.wizard.syncLater')
        : '';
    return [accountLine, countsLine, syncLine].filter(Boolean).join(' ');
  }, [account, sources, toolCount, mode, canSync, t]);

  const renderSignIn = () => (
    <div className="flex flex-col gap-5">
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {isMcpPreset && mcp.pending && (
        <p className="text-muted-foreground text-sm">
          {t('settings.connectors.wizard.waiting', {
            name,
            interpolation: { escapeValue: false },
          })}
        </p>
      )}
      {isMcpPreset && mcp.blockedUrl && (
        <Button variant="link" size="inline" asChild className="w-fit">
          <a href={mcp.blockedUrl} target="_blank" rel="noopener noreferrer">
            {t('settings.connectors.wizard.openSignIn', {
              name,
              interpolation: { escapeValue: false },
            })}
          </a>
        </Button>
      )}
      {mode !== 'reconnect' && methods.length > 1 && (
        <ToggleGroup
          type="single"
          fill
          value={method}
          onValueChange={(value) =>
            value && setChosenMethod(value as ConnectorAuthKind)
          }
          aria-label={t('settings.connectors.wizard.methodLabel')}
        >
          {methods.map((value) => (
            <ToggleGroupItem key={value} value={value}>
              {value === 'oauth'
                ? t('settings.connectors.wizard.methodOauth', {
                    name,
                    interpolation: { escapeValue: false },
                  })
                : t('settings.connectors.wizard.methodToken')}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      )}
      {usesOAuth || isMcpPreset || isOpenMcp ? null : (
        <CredentialForm
          connectorKey={connector.key}
          idPrefix={`connect-${connector.key}`}
          fields={connector.credential_fields}
          values={credentials}
          onChange={setCredentials}
        />
      )}
      {canName && (
        <FormField
          label={t('settings.connectors.wizard.accountName')}
          hint={t('settings.connectors.wizard.accountNameHint')}
        >
          <Input
            id="connect-account-name"
            autoComplete="off"
            maxLength={ACCOUNT_NAME_MAX}
            value={accountName}
            onChange={(e) => setAccountName(e.target.value)}
          />
        </FormField>
      )}
    </div>
  );

  const renderSetup = () => (
    <div className="flex flex-col gap-5">
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {chooseAccount && (
        <FormField label={t('settings.connectors.wizard.account')}>
          <Select
            value={activeConnectionId ?? undefined}
            onValueChange={switchAccount}
          >
            <SelectTrigger size="field" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {serviceAccounts.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  {item.account_name || item.account_label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      )}
      {(offerTools || (askSync && !syncOnly)) && (
        <SettingRows>
          {offerTools && (
            <SettingRow
              label={t('settings.connectors.wizard.addTools', {
                name,
                interpolation: { escapeValue: false },
              })}
              description={t(
                `settings.connectors.wizard.addToolsDescription.${
                  connector.capabilities.includes('write') || wantsWrites
                    ? 'readWrite'
                    : 'read'
                }`,
              )}
              htmlFor={`tools-${connector.key}`}
              alignStart
            >
              <Switch
                id={`tools-${connector.key}`}
                checked={toolsOn}
                onCheckedChange={(checked) => setToolsOn(checked === true)}
              />
            </SettingRow>
          )}
          {offerWrites && (
            <SettingRow
              label={t('settings.connectors.github.writes')}
              description={t('settings.connectors.github.writesDescription')}
              htmlFor={`tools-${connector.key}-writes`}
              alignStart
            >
              <Switch
                id={`tools-${connector.key}-writes`}
                checked={writesOn}
                onCheckedChange={(checked) => setWritesOn(checked === true)}
              />
            </SettingRow>
          )}
          {askSync && !syncOnly && (
            <SettingRow
              label={t('settings.connectors.wizard.syncToKnowledge')}
              description={t(
                'settings.connectors.wizard.syncToKnowledgeDescription',
                { name, interpolation: { escapeValue: false } },
              )}
              htmlFor={`knowledge-${connector.key}`}
              alignStart
            >
              <Switch
                id={`knowledge-${connector.key}`}
                checked={syncOn}
                onCheckedChange={(checked) => toggleSync(checked === true)}
              />
            </SettingRow>
          )}
        </SettingRows>
      )}
      {askSync && syncOnly ? (
        // No gap on the wrapper: a closed Collapsible is still a flex item.
        <div className="flex flex-col">
          <div
            role="radiogroup"
            aria-label={t('settings.connectors.wizard.syncChoice', {
              name,
              interpolation: { escapeValue: false },
            })}
            className="flex flex-col gap-3"
          >
            <OptionCard
              icon={<Database />}
              title={t('settings.connectors.wizard.syncNow')}
              description={t('settings.connectors.wizard.syncNowDescription', {
                name,
                interpolation: { escapeValue: false },
              })}
              selected={syncOn}
              onClick={() => setSyncOn(true)}
            />
            <OptionCard
              icon={<Plug />}
              title={t('settings.connectors.wizard.justConnect')}
              description={t(
                'settings.connectors.wizard.justConnectDescription',
              )}
              selected={!syncOn}
              onClick={() => setSyncOn(false)}
            />
          </div>
          {/* Folded, not dropped, on Just connect: what was typed or picked
              is still there on the way back. */}
          <Collapsible open={syncOn}>
            <div className="flex flex-col gap-5 pt-5">
              <Separator />
              {renderSyncForm()}
            </div>
          </Collapsible>
        </div>
      ) : (
        syncing && renderSyncForm()
      )}
    </div>
  );

  /** What to sync, its name and schedule, and its retrieval settings. */
  const renderSyncForm = () => (
    <>
      {isRepoPicker && activeConnectionId ? (
        <RepoPicker
          key={`${activeConnectionId}-${pickerKey}`}
          connectionId={activeConnectionId}
          token={token}
          value={selectedRepo}
          onChange={(fullName) => {
            setSelectedRepo(fullName);
            if (!nameTouched) setSourceName(fullName);
          }}
          onReconnect={onReconnect}
        />
      ) : isLinearPicker && activeConnectionId ? (
        <LinearPicker
          key={`${activeConnectionId}-${pickerKey}`}
          connectionId={activeConnectionId}
          token={token}
          value={linearSelection}
          onChange={(selection) => {
            setLinearSelection(selection);
            if (!nameTouched) setSourceName(linearSourceName(selection));
          }}
          onReconnect={onReconnect}
        />
      ) : connector.key === 'google_drive' &&
        envVar('VITE_GOOGLE_CLIENT_ID') ? (
        activeConnectionId ? (
          <GoogleDrivePicker
            key={`${activeConnectionId}-${pickerKey}`}
            token={token}
            connectionId={activeConnectionId}
            onFirstPickName={prefillName}
            onSelectionChange={(fileIds, folderIds = []) => {
              setSelectedFiles(fileIds);
              setSelectedFolders(folderIds);
            }}
            onReconnect={onReconnect}
          />
        ) : null
      ) : PICKER_CONNECTORS.has(connector.key) ? (
        activeConnectionId ? (
          <FilePicker
            key={`${activeConnectionId}-${pickerKey}`}
            provider={connector.key}
            token={token}
            connectionId={activeConnectionId}
            onFirstPickName={prefillName}
            onSelectionChange={(fileIds, folderIds = []) => {
              setSelectedFiles(fileIds);
              setSelectedFolders(folderIds);
            }}
            onReconnect={onReconnect}
          />
        ) : null
      ) : (
        <CredentialForm
          connectorKey={connector.key}
          idPrefix={`sync-${connector.key}`}
          fields={connector.setup_fields}
          values={setupValues}
          onChange={(values) => {
            setSetupValues(values);
            const first = Object.values(values).find(Boolean);
            if (first) prefillName(first);
          }}
        />
      )}
      <div className="grid grid-cols-1 gap-x-4 gap-y-5 sm:grid-cols-2">
        <Input
          label={t('modals.uploadDoc.name')}
          value={sourceName}
          onChange={(e) => {
            setNameTouched(true);
            setSourceName(e.target.value);
          }}
        />
        <FormField label={t('settings.connectors.wizard.syncFrequency')}>
          <Select value={frequency} onValueChange={setFrequency}>
            <SelectTrigger size="field" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FREQUENCIES.map((value) => (
                <SelectItem key={value} value={value}>
                  {t(`settings.sources.syncFrequency.${value}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      </div>
      <RetrievalOptions
        variant="create"
        title={t('settings.connectors.wizard.retrievalSettings')}
        value={retrievalOptions}
        onChange={setRetrievalOptions}
        hybridAvailable={hybridAvailable}
        graphRAGAvailable={graphRAGAvailable}
        availableModels={availableModels}
        decision={decision}
        linksAvailable={sourceHasFileLinks(connector.key)}
      />
    </>
  );

  const renderDone = () => (
    <div className="flex flex-col gap-5">
      {summary && (
        <Alert variant="success">
          <AlertDescription>{summary}</AlertDescription>
        </Alert>
      )}
      {toolCount > 0 && activeConnectionId && (
        <div className="flex flex-col gap-3">
          <CollapsibleTrigger
            open={toolsOpen}
            onOpenChange={setToolsOpen}
            controls={toolsId}
          >
            {t('settings.connectors.wizard.toolsHeading', {
              count: toolCount,
              formatted: formatCount(toolCount),
            })}
          </CollapsibleTrigger>
          <Collapsible open={toolsOpen} id={toolsId}>
            <div className="flex flex-col gap-3">
              {tools.map((tool) => (
                <ToolPermissions
                  key={tool.id}
                  connectionId={activeConnectionId}
                  tool={tool}
                />
              ))}
            </div>
          </Collapsible>
        </div>
      )}
    </div>
  );

  /**
   * The summary's footer follows what happened: a reconnect ends on Done; a
   * new source opens in Knowledge; tools are tried in chat; with nothing
   * synced and no tools, Sync content starts the sync step in place.
   */
  const renderDoneFooter = () => {
    const done = (
      <Button
        type="button"
        variant="default"
        size="lg"
        shape="pill"
        onClick={finish}
      >
        {t('settings.connectors.wizard.done')}
      </Button>
    );
    if (mode === 'reconnect') return done;
    const next =
      sources.length > 0
        ? {
            label: t('settings.connectors.openInKnowledge'),
            onSubmit: openInKnowledge,
          }
        : toolCount > 0
          ? {
              label: t('settings.connectors.wizard.tryInChat'),
              onSubmit: tryInChat,
            }
          : null;
    if (next)
      return (
        <ModalActions
          cancelLabel={t('settings.connectors.wizard.done')}
          onCancel={finish}
          submitLabel={next.label}
          onSubmit={next.onSubmit}
        />
      );
    if (canSync && activeConnectionId)
      return (
        <>
          <Button
            type="button"
            variant="outline"
            size="lg"
            shape="pill"
            onClick={syncContent}
          >
            {t('settings.connectors.syncContent')}
          </Button>
          {done}
        </>
      );
    return done;
  };

  // The service is in every title, and the setup title stays put while the
  // choice changes.
  const title =
    step === 'signin'
      ? t(
          mode === 'reconnect'
            ? 'settings.connectors.wizard.reconnectTitle'
            : 'settings.connectors.wizard.connectTitle',
          { name, interpolation: { escapeValue: false } },
        )
      : step === 'setup'
        ? t(
            offerTools
              ? 'settings.connectors.wizard.chooseWhatToSetUpFor'
              : 'settings.connectors.wizard.chooseWhatToSyncFrom',
            { name, interpolation: { escapeValue: false } },
          )
        : t('settings.connectors.wizard.doneTitle', {
            name,
            interpolation: { escapeValue: false },
          });

  // Sign-in says what the service does; setup names the account it sets up
  // (unless the first field picks one). A sync-only service's choice also
  // says what the service does, since that is what the choice is about.
  const setupDescription =
    askSync && syncOnly
      ? [connectorDescription(t, connector), accountSentence]
          .filter(Boolean)
          .join(' ')
      : accountSentence;
  const description =
    step === 'signin'
      ? connectorDescription(t, connector)
      : step === 'setup' && !chooseAccount && setupDescription
        ? setupDescription
        : undefined;

  // Cancelling a reconnect a picker asked for goes back to the picker.
  const cancelSignIn = () => {
    mcp.cancel();
    if (!resumeAfterReconnect()) close();
  };

  const footer =
    step === 'signin' ? (
      usesOAuth || isMcpPreset || isOpenMcp ? (
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={cancelSignIn}
          submitLabel={
            isOpenMcp
              ? t(
                  mode === 'reconnect'
                    ? 'settings.connectors.status.reconnect'
                    : 'settings.connectors.status.connect',
                )
              : t('settings.connectors.wizard.signIn', {
                  name,
                  interpolation: { escapeValue: false },
                })
          }
          onSubmit={
            isOpenMcp
              ? connectOpenMcp
              : isMcpPreset
                ? startMcpSignIn
                : startSignIn
          }
          pending={
            isOpenMcp ? pending : isMcpPreset && (mcp.pending || pending)
          }
        />
      ) : (
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={cancelSignIn}
          submitLabel={
            mode === 'reconnect'
              ? t('settings.connectors.status.reconnect')
              : t('settings.connectors.status.connect')
          }
          onSubmit={submitCredentials}
          pending={pending}
          disabled={
            !credentialsComplete(connector.credential_fields, credentials)
          }
        />
      )
    ) : step === 'setup' && mode === 'sync' ? (
      <ModalActions
        cancelLabel={t('cancel')}
        onCancel={close}
        submitLabel={t('modals.uploadDoc.train')}
        onSubmit={addSource}
        pending={pending}
        disabled={!canAddSource}
      />
    ) : step === 'setup' ? (
      // The account exists: nothing to skip, one submit named by what it does.
      <Button
        type="button"
        size="lg"
        shape="pill"
        onClick={addSource}
        loading={pending}
        disabled={!canAddSource}
      >
        {syncing
          ? t('modals.uploadDoc.train')
          : t('settings.connectors.wizard.finishSetup')}
      </Button>
    ) : (
      renderDoneFooter()
    );

  return (
    <Modal
      open
      onOpenChange={(open) => !open && (step === 'done' ? finish() : close())}
      title={title}
      description={description}
      leading={
        <Avatar size="xl" shape="square" variant="icon">
          <ConnectorIcon icon={connector.icon} className="size-7" />
        </Avatar>
      }
      size="lg"
      footer={footer}
    >
      {step === 'signin' && renderSignIn()}
      {step === 'setup' && renderSetup()}
      {step === 'done' && renderDone()}
    </Modal>
  );
}
