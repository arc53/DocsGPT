import { ChevronRight, CircleAlert, CircleCheck } from 'lucide-react';
import { nanoid } from '@reduxjs/toolkit';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import { envVar } from '@/env';
import { cn } from '@/lib/utils';
import { baseURL } from '../api/client';
import connectorsService from '../api/services/connectorsService';
import userService from '../api/services/userService';
import { useConnectorAuth } from '../components/ConnectorAuth';
import { FilePicker } from '../components/FilePicker';
import GoogleDrivePicker from '../components/GoogleDrivePicker';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Collapsible } from '../components/ui/collapsible';
import { FormField } from '../components/ui/form-field';
import { Input } from '../components/ui/input';
import { Modal, ModalActions } from '../components/ui/modal';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
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
  DEFAULT_RETRIEVAL_OPTIONS,
  isPrescreenConfigValid,
  optionsToConfig,
  type RetrievalOptionsValue,
} from '../settings/components/RetrievalOptions';
import useRetrievalAvailability from '../settings/components/useRetrievalAvailability';
import type { AppDispatch } from '../store';
import { formatCount } from '../utils/dateTimeUtils';
import { ACCOUNT_NAME_MAX } from './accounts';
import ConnectorIcon from './ConnectorIcon';
import CredentialForm, { credentialsComplete } from './CredentialForm';
import { loadConnectors, selectConnections } from './connectorsSlice';
import { connectorDescription, connectorName, isKeyHint } from './i18n';
import { reconnectsInPlace } from './launchRules';
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
 * up, then a summary with Try it in chat. A content connector asks whether to
 * sync into Knowledge (on when opened for Knowledge) and, if so, what to sync
 * and with which retrieval settings. Tool connectors create their tools on
 * sign-in, writes needing approval, so they go from the credentials straight
 * to the summary. Every run that connects something ends on the summary.
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
}: {
  connector: ConnectorDefinition;
  mode?: WizardMode;
  connectionId?: string | null;
  /** Reconnecting an MCP preset: the tool to update rather than add. */
  mcpToolId?: string;
  purpose?: LaunchPurpose;
  onClose: (connected: boolean) => void;
  onFinished?: () => void;
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
  // One key per wizard: a double click on Add source queues one ingest.
  const [idempotencyKey] = useState(() => nanoid());

  // Sync more from Add knowledge names no account when the service has
  // several: the first setup field picks one (the first, until changed).
  const serviceAccounts = connections.filter(
    (c) => c.connector_key === connector.key && c.status === 'connected',
  );
  const pickingAccount = mode === 'sync' && !initialConnectionId;
  const activeConnectionId =
    connectionId ?? (pickingAccount ? (serviceAccounts[0]?.id ?? null) : null);
  const chooseAccount = pickingAccount && serviceAccounts.length > 1;
  const connection = connections.find((c) => c.id === activeConnectionId);
  const canSync = connector.setup.sync !== 'off' && !!connector.sync_ingestor;
  // A first connect asks whether to sync into Knowledge; Sync more is only
  // about syncing, so it never asks.
  const askSync = canSync && mode === 'connect';
  const [syncOn, setSyncOn] = useState(purpose === 'knowledge');
  const syncing = canSync && (mode === 'sync' || syncOn);
  const [retrievalOptions, setRetrievalOptions] =
    useState<RetrievalOptionsValue>(DEFAULT_RETRIEVAL_OPTIONS);
  const { graphRAGAvailable, hybridAvailable, availableModels } =
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
  const mcp = useMcpOAuth();
  const mcpConfig = (): McpOAuthConfig => ({
    server_url: connector.mcp_url ?? '',
    auth_type: 'oauth',
    oauth_scopes: connector.oauth_scopes ?? [],
    timeout: 30,
    redirect_uri: `${baseURL.replace(/\/$/, '')}/api/mcp_server/callback`,
  });

  const saveMcp = async (config: McpOAuthConfig, taskId: string | null) => {
    setPending(true);
    try {
      const response = await userService.saveMCPServer(
        {
          displayName: name,
          config: { ...config, oauth_task_id: taskId ?? '' },
          status: true,
          ...(mcpReconnectToolId && { id: mcpReconnectToolId }),
        },
        token,
      );
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error);
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
      connectedRef.current = true;
      await refresh();
      if (saved) {
        setConnectionId(saved.id);
        const detail = await connectorsService.getConnection(saved.id, token);
        if (detail?.success) {
          setTools(detail.connection.tools ?? []);
          if (detail.connection.account_label)
            setAccountLabel(detail.connection.account_label);
        }
      }
      if (mode === 'reconnect' && resumeAfterReconnect()) return;
      // One sign-in also syncs (Linear): choosing what to sync comes next.
      setStep(canSync && saved && mode === 'connect' ? 'setup' : 'done');
    } catch (err) {
      setError(
        (err instanceof Error && err.message) ||
          t('settings.tools.mcp.errors.saveFailed'),
      );
    } finally {
      setPending(false);
    }
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
        setError(
          data?.code === 'tools_unavailable'
            ? t('settings.connectors.wizard.toolsUnavailable', {
                name,
                interpolation: { escapeValue: false },
              })
            : data?.code === 'writes_forbidden'
              ? t('settings.connectors.github.writesForbidden')
              : data?.error || t('settings.connectors.wizard.syncFailed'),
        );
        return;
      }
      connectedRef.current = true;
      if (wantsTools) setTools(data.tools ?? []);
      setSources(data.sources ?? []);
      refresh();
      setStep('done');
    } catch {
      setError(t('settings.connectors.wizard.syncFailed'));
    } finally {
      setPending(false);
    }
  };

  const tryInChat = () => {
    dispatch(setConversation([]));
    dispatch(updateConversationId({ query: { conversationId: null } }));
    dispatch(setSelectedAgent(null));
    if (sources.length > 0) {
      dispatch(
        setSelectedDocs(
          sources.map((source) => ({
            id: source.id,
            name: source.name,
            date: new Date().toISOString(),
            model: '',
            type: 'connector:file',
            connectionId: activeConnectionId,
          })),
        ),
      );
    }
    onFinished?.();
    close();
    navigate('/c/new');
  };

  const finish = () => {
    onFinished?.();
    close();
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
    setSelectedFiles([]);
    setSelectedFolders([]);
    setSelectedRepo(null);
    setLinearSelection(EMPTY_LINEAR_SELECTION);
    setPickerKey((key) => key + 1);
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
    // A new account that syncs nothing yet: say where syncing starts later.
    const syncLine =
      mode === 'connect' && canSync && sources.length === 0
        ? t('settings.connectors.wizard.syncLater', {
            name,
            interpolation: { escapeValue: false },
          })
        : '';
    return [accountLine, countsLine, syncLine].filter(Boolean).join(' ');
  }, [account, sources, toolCount, mode, canSync, name, t]);

  const renderSignIn = () => (
    <div className="flex flex-col gap-5">
      {error && (
        <Alert variant="destructive">
          <CircleAlert />
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
      {usesOAuth || isMcpPreset ? null : (
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
          <CircleAlert />
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
      {(offerTools || askSync) && (
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
          {askSync && (
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
      {syncing && (
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
            title={t('settings.connectors.wizard.retrievalSettings')}
            value={retrievalOptions}
            onChange={setRetrievalOptions}
            hybridAvailable={hybridAvailable}
            graphRAGAvailable={graphRAGAvailable}
            availableModels={availableModels}
          />
        </>
      )}
    </div>
  );

  const renderDone = () => (
    <div className="flex flex-col gap-5">
      {summary && (
        <Alert variant="success">
          <CircleCheck />
          <AlertDescription>{summary}</AlertDescription>
        </Alert>
      )}
      {toolCount > 0 && activeConnectionId && (
        <div className="flex flex-col gap-3">
          <Button
            type="button"
            variant="link"
            size="sm"
            aria-expanded={toolsOpen}
            aria-controls={toolsId}
            className="-ml-3 w-fit justify-start"
            onClick={() => setToolsOpen(!toolsOpen)}
          >
            <ChevronRight
              aria-hidden
              className={cn(
                'transition-transform duration-200',
                toolsOpen && 'rotate-90',
              )}
            />
            {t('settings.connectors.wizard.toolsHeading', {
              count: toolCount,
              formatted: formatCount(toolCount),
            })}
          </Button>
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

  // The service is in every title, and the setup title stays put while the
  // switches change.
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
  // (unless the first field picks one).
  const description =
    step === 'signin'
      ? connectorDescription(t, connector)
      : step === 'setup' && !chooseAccount && accountText
        ? mode === 'sync'
          ? accountText
          : t('settings.connectors.wizard.signedInAs', {
              account: accountText,
              interpolation: { escapeValue: false },
            })
        : undefined;

  // Cancelling a reconnect a picker asked for goes back to the picker.
  const cancelSignIn = () => {
    mcp.cancel();
    if (!resumeAfterReconnect()) close();
  };

  const footer =
    step === 'signin' ? (
      usesOAuth || isMcpPreset ? (
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={cancelSignIn}
          submitLabel={t('settings.connectors.wizard.signIn', {
            name,
            interpolation: { escapeValue: false },
          })}
          onSubmit={isMcpPreset ? startMcpSignIn : startSignIn}
          pending={isMcpPreset && (mcp.pending || pending)}
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
      <ModalActions
        cancelLabel={t('settings.connectors.wizard.done')}
        onCancel={finish}
        submitLabel={t('settings.connectors.wizard.tryInChat')}
        onSubmit={tryInChat}
      />
    );

  return (
    <Modal
      open
      onOpenChange={(open) => !open && (step === 'done' ? finish() : close())}
      title={title}
      description={description}
      leading={
        <span className="bg-muted flex size-12 shrink-0 items-center justify-center rounded-xl">
          <ConnectorIcon icon={connector.icon} className="size-7" />
        </span>
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
