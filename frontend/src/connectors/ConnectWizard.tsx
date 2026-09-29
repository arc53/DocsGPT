import { CircleAlert, ExternalLink } from 'lucide-react';
import { nanoid } from '@reduxjs/toolkit';
import { useEffect, useMemo, useState } from 'react';
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
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '../components/ui/accordion';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
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
import type { AppDispatch } from '../store';
import { formatCount } from '../utils/dateTimeUtils';
import { ACCOUNT_NAME_MAX } from './accounts';
import ConnectorIcon from './ConnectorIcon';
import CredentialForm, { credentialsComplete } from './CredentialForm';
import { loadConnectors, selectConnections } from './connectorsSlice';
import { connectorDescription, connectorName, isKeyHint } from './i18n';
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

const FREQUENCIES = ['never', 'daily', 'weekly', 'monthly'] as const;
const PICKER_CONNECTORS = new Set([
  'google_drive',
  'share_point',
  'confluence',
]);
// Where a GitHub user makes a fine-grained token (Contents and Metadata: read;
// Issues and Pull requests: read and write when agents may make changes).
const GITHUB_TOKEN_URL =
  'https://github.com/settings/personal-access-tokens/new';

type CreatedSource = { id: string; name: string };

/**
 * The one connect flow every entry point opens: sign in, choose what to
 * sync (content connectors only, skippable), then a summary with Try it in
 * chat. Tool connectors create their tools on sign-in, writes needing
 * approval, so they go from the credentials straight to the summary.
 */
export default function ConnectWizard({
  connector,
  mode = 'connect',
  connectionId: initialConnectionId = null,
  mcpToolId,
  onClose,
  onFinished,
}: {
  connector: ConnectorDefinition;
  mode?: WizardMode;
  connectionId?: string | null;
  /** Reconnecting an MCP preset: the tool to update rather than add. */
  mcpToolId?: string;
  onClose: () => void;
  onFinished?: () => void;
}) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const connections = useSelector(selectConnections);
  const name = connectorName(t, connector);

  const [step, setStep] = useState<'signin' | 'setup' | 'done'>(
    mode === 'sync' ? 'setup' : mode === 'done' ? 'done' : 'signin',
  );
  const [connectionId, setConnectionId] = useState<string | null>(
    initialConnectionId,
  );
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

  const connection = connections.find((c) => c.id === connectionId);
  const canSync = connector.setup.sync !== 'off' && !!connector.sync_ingestor;
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
    if (mode !== 'done' || !connectionId) return;
    connectorsService.getConnection(connectionId, token).then((data) => {
      if (data?.success) setTools(data.connection.tools ?? []);
    });
  }, [mode, connectionId, token]);

  const refresh = () => dispatch(loadConnectors({ token }));

  // A name tells two accounts of one service apart ("Alerts bot"). It is
  // set once the account exists, so it works the same for keys and sign-ins.
  const canName =
    mode === 'connect' &&
    (connector.auth_kind === 'api_key' || connector.auth_kind === 'oauth');

  const afterSignIn = async (id: string) => {
    setConnectionId(id);
    const name = accountName.trim();
    if (canName && name) {
      try {
        await connectorsService.renameConnection(id, name, token);
      } catch {
        // The account works without a name; it can be named in the drawer.
      }
    }
    refresh();
    if (mode === 'reconnect') {
      setStep('done');
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
  // done step shows what it can do.
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
          ...(mcpToolId && { id: mcpToolId }),
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
      refresh();
      if (saved) {
        setConnectionId(saved.id);
        const detail = await connectorsService.getConnection(saved.id, token);
        if (detail?.success) setTools(detail.connection.tools ?? []);
      }
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
      mode === 'reconnect' ? (connectionId ?? undefined) : undefined,
    onSuccess: (data) => afterSignIn(data.connection_id),
    onError: setError,
  });

  const submitCredentials = async () => {
    setPending(true);
    setError('');
    try {
      const data =
        mode === 'reconnect' && connectionId
          ? await connectorsService.reconnect(
              connectionId,
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
      await afterSignIn(data.connection.id);
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
  const canAddSource = hasSyncSelection || wantsTools;

  const addSource = async () => {
    if (!connectionId) return;
    setPending(true);
    setError('');
    try {
      const data = await connectorsService.setup(
        connectionId,
        {
          create_tools: wantsTools,
          ...(wantsWrites && { allow_writes: true }),
          ...(hasSyncSelection && {
            sync: {
              items: syncItems(),
              frequency,
              name: sourceName.trim() || undefined,
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
            connectionId,
          })),
        ),
      );
    }
    onFinished?.();
    onClose();
    navigate('/c/new');
  };

  const finish = () => {
    onFinished?.();
    onClose();
  };

  const toolCount = tools.length;
  const summary = useMemo(() => {
    const account = connection?.account_label ?? '';
    const accountLine =
      connection?.auth_kind === 'api_key' && isKeyHint(account)
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
    return [accountLine, countsLine].filter(Boolean).join(' ');
  }, [connection, sources, toolCount, t]);

  const renderSignIn = () => (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-4">
        <span className="bg-muted flex size-12 shrink-0 items-center justify-center rounded-xl">
          <ConnectorIcon icon={connector.icon} className="size-7" />
        </span>
        <p className="text-muted-foreground text-sm">
          {connectorDescription(t, connector)}
        </p>
      </div>
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
        <>
          {connector.key === 'github' && (
            <div className="flex flex-col gap-1">
              <p className="text-muted-foreground text-sm">
                {t('settings.connectors.github.tokenHint')}
              </p>
              <Button variant="link" size="inline" asChild className="w-fit">
                <a
                  href={GITHUB_TOKEN_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {t('settings.connectors.github.createToken')}
                  <ExternalLink />
                </a>
              </Button>
            </div>
          )}
          <CredentialForm
            connectorKey={connector.key}
            idPrefix={`connect-${connector.key}`}
            fields={connector.credential_fields}
            values={credentials}
            onChange={setCredentials}
          />
        </>
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
      {offerTools && (
        <SettingRows>
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
        </SettingRows>
      )}
      {isRepoPicker && connectionId ? (
        <RepoPicker
          connectionId={connectionId}
          token={token}
          value={selectedRepo}
          onChange={(fullName) => {
            setSelectedRepo(fullName);
            if (!nameTouched) setSourceName(fullName);
          }}
        />
      ) : isLinearPicker && connectionId ? (
        <LinearPicker
          connectionId={connectionId}
          token={token}
          value={linearSelection}
          onChange={(selection) => {
            setLinearSelection(selection);
            if (!nameTouched) setSourceName(linearSourceName(selection));
          }}
        />
      ) : connector.key === 'google_drive' &&
        envVar('VITE_GOOGLE_CLIENT_ID') ? (
        <GoogleDrivePicker
          token={token}
          connectionId={connectionId}
          onFirstPickName={prefillName}
          onSelectionChange={(fileIds, folderIds = []) => {
            setSelectedFiles(fileIds);
            setSelectedFolders(folderIds);
          }}
        />
      ) : PICKER_CONNECTORS.has(connector.key) ? (
        <FilePicker
          provider={connector.key}
          token={token}
          connectionId={connectionId}
          onFirstPickName={prefillName}
          onSelectionChange={(fileIds, folderIds = []) => {
            setSelectedFiles(fileIds);
            setSelectedFolders(folderIds);
          }}
        />
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
    </div>
  );

  const renderDone = () => (
    <div className="flex flex-col gap-5">
      <p className="text-muted-foreground text-sm">{summary}</p>
      {toolCount > 0 && connectionId && (
        <div className="border-border overflow-hidden rounded-xl border">
          <Accordion type="single" collapsible>
            <AccordionItem value="tools">
              <AccordionTrigger>
                {t('settings.connectors.wizard.toolsHeading', {
                  count: toolCount,
                  formatted: formatCount(toolCount),
                })}
              </AccordionTrigger>
              <AccordionContent>
                <div className="flex flex-col gap-3 px-4 pb-4">
                  {tools.map((tool) => (
                    <ToolPermissions
                      key={tool.id}
                      connectionId={connectionId}
                      tool={tool}
                    />
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </div>
      )}
    </div>
  );

  const title =
    step === 'signin'
      ? mode === 'reconnect'
        ? t('settings.connectors.wizard.reconnectTitle', {
            name,
            interpolation: { escapeValue: false },
          })
        : t('settings.connectors.wizard.connectTitle', {
            name,
            interpolation: { escapeValue: false },
          })
      : step === 'setup'
        ? offerTools
          ? t('settings.connectors.wizard.chooseWhatToSetUp')
          : t('settings.connectors.wizard.chooseWhatToSync')
        : t('settings.connectors.wizard.doneTitle', {
            name,
            interpolation: { escapeValue: false },
          });

  const footer =
    step === 'signin' ? (
      usesOAuth || isMcpPreset ? (
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={() => {
            mcp.cancel();
            onClose();
          }}
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
          onCancel={onClose}
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
    ) : step === 'setup' ? (
      <ModalActions
        cancelLabel={t('settings.connectors.wizard.skip')}
        onCancel={() => (mode === 'sync' ? onClose() : setStep('done'))}
        submitLabel={
          offerTools
            ? t('settings.connectors.wizard.continue')
            : t('modals.uploadDoc.train')
        }
        onSubmit={addSource}
        pending={pending}
        disabled={!canAddSource}
      />
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
      onOpenChange={(open) => !open && (step === 'done' ? finish() : onClose())}
      title={title}
      size={step === 'setup' ? 'xl' : 'lg'}
      mobileVariant="sheet"
      footer={footer}
    >
      {step === 'signin' && renderSignIn()}
      {step === 'setup' && renderSetup()}
      {step === 'done' && renderDone()}
    </Modal>
  );
}
