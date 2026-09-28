import { CircleAlert } from 'lucide-react';
import { nanoid } from '@reduxjs/toolkit';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import { envVar } from '@/env';
import connectorsService from '../api/services/connectorsService';
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
import ConnectorIcon from './ConnectorIcon';
import CredentialForm, { credentialsComplete } from './CredentialForm';
import { loadConnectors, selectConnections } from './connectorsSlice';
import { connectorDescription, connectorName } from './i18n';
import ToolPermissions from './ToolPermissions';
import type { ConnectionTool, ConnectorDefinition } from './types';

export type WizardMode = 'connect' | 'reconnect' | 'sync' | 'done';

const FREQUENCIES = ['never', 'daily', 'weekly', 'monthly'] as const;
const PICKER_CONNECTORS = new Set([
  'google_drive',
  'share_point',
  'confluence',
]);

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
  onClose,
  onFinished,
}: {
  connector: ConnectorDefinition;
  mode?: WizardMode;
  connectionId?: string | null;
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
  const [setupValues, setSetupValues] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [tools, setTools] = useState<ConnectionTool[]>([]);
  const [sources, setSources] = useState<CreatedSource[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [selectedFolders, setSelectedFolders] = useState<string[]>([]);
  const [sourceName, setSourceName] = useState('');
  const [nameTouched, setNameTouched] = useState(false);
  const [frequency, setFrequency] = useState(
    connector.default_sync_frequency || 'weekly',
  );
  // One key per wizard: a double click on Add source queues one ingest.
  const [idempotencyKey] = useState(() => nanoid());

  const connection = connections.find((c) => c.id === connectionId);
  const canSync = connector.setup.sync !== 'off' && !!connector.sync_ingestor;

  // A finished MCP save or a reconnect lands here with only the connection id.
  useEffect(() => {
    if (mode !== 'done' || !connectionId) return;
    connectorsService.getConnection(connectionId, token).then((data) => {
      if (data?.success) setTools(data.connection.tools ?? []);
    });
  }, [mode, connectionId, token]);

  const refresh = () => dispatch(loadConnectors({ token }));

  const afterSignIn = async (id: string) => {
    setConnectionId(id);
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
    setStep(canSync ? 'setup' : 'done');
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

  const syncItems = (): Record<string, unknown> =>
    PICKER_CONNECTORS.has(connector.key)
      ? { file_ids: selectedFiles, folder_ids: selectedFolders }
      : setupValues;

  const canAddSource = PICKER_CONNECTORS.has(connector.key)
    ? selectedFiles.length + selectedFolders.length > 0
    : credentialsComplete(connector.setup_fields, setupValues);

  const addSource = async () => {
    if (!connectionId) return;
    setPending(true);
    setError('');
    try {
      const data = await connectorsService.setup(
        connectionId,
        {
          create_tools: false,
          sync: {
            items: syncItems(),
            frequency,
            name: sourceName.trim() || undefined,
          },
        },
        token,
        idempotencyKey,
      );
      if (!data?.success) {
        setError(data?.error || t('settings.connectors.wizard.syncFailed'));
        return;
      }
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
      connection?.auth_kind === 'api_key'
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
      {connector.auth_kind === 'oauth' ? null : (
        <CredentialForm
          connectorKey={connector.key}
          idPrefix={`connect-${connector.key}`}
          fields={connector.credential_fields}
          values={credentials}
          onChange={setCredentials}
        />
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
      {connector.key === 'google_drive' && envVar('VITE_GOOGLE_CLIENT_ID') ? (
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
        ? t('settings.connectors.wizard.chooseWhatToSync')
        : t('settings.connectors.wizard.doneTitle', {
            name,
            interpolation: { escapeValue: false },
          });

  const footer =
    step === 'signin' ? (
      connector.auth_kind === 'oauth' ? (
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={onClose}
          submitLabel={t('settings.connectors.wizard.signIn', {
            name,
            interpolation: { escapeValue: false },
          })}
          onSubmit={startSignIn}
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
        submitLabel={t('modals.uploadDoc.train')}
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
