import {
  CircleAlert,
  Pencil,
  Plus,
  RefreshCw,
  RotateCw,
  Trash2,
  TriangleAlert,
  Unplug,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import connectorsService from '../api/services/connectorsService';
import userService from '../api/services/userService';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { ActionMenu, type MenuOption } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import { FormField } from '../components/ui/form-field';
import { Input } from '../components/ui/input';
import { ListRow, ListRows } from '../components/ui/list-row';
import { LoadingState } from '../components/ui/loading-state';
import { Modal, ModalActions } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import { Switch } from '../components/ui/switch';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from '../components/ui/sheet';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import ConfirmationModal from '../modals/ConfirmationModal';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import { formatCount, formatDateTime } from '../utils/dateTimeUtils';
import { ACCOUNT_NAME_MAX } from './accounts';
import { CapabilityBadges } from './ConnectorCard';
import ConnectorIcon from './ConnectorIcon';
import ConnectorSetupNotice from './ConnectorSetupNotice';
import { loadConnectors, selectConnections } from './connectorsSlice';
import { connectorDescription, connectorName, isKeyHint } from './i18n';
import ToolPermissions from './ToolPermissions';
import type {
  ConnectionDetail,
  ConnectionSource,
  ConnectionTool,
  ConnectionStatus,
  ConnectorDefinition,
} from './types';
import type { LaunchOptions } from './useConnectorLauncher';

const STATUS_VARIANT: Record<
  ConnectionStatus,
  'success' | 'warning' | 'neutral' | 'destructive'
> = {
  connected: 'success',
  reconnect_needed: 'warning',
  disconnected: 'neutral',
  error: 'destructive',
  pending: 'neutral',
};

/**
 * "Connected as …", or the key hint for pasted credentials (a GitHub token
 * is named after its account instead). A connection that is not working
 * names its account without claiming it is connected.
 */
function useAccountTitle() {
  const { t } = useTranslation();
  return (detail: ConnectionDetail) =>
    detail.auth_kind === 'api_key' && isKeyHint(detail.account_label)
      ? t('settings.connectors.detail.keyEnding', {
          hint: detail.account_label,
          interpolation: { escapeValue: false },
        })
      : t(
          detail.status === 'connected'
            ? 'settings.connectors.detail.connectedAs'
            : 'settings.connectors.detail.account',
          {
            account: detail.account_label,
            interpolation: { escapeValue: false },
          },
        );
}

/** What is wrong, in plain words rather than the provider's message. */
function useProblem() {
  const { t } = useTranslation();
  return (detail: ConnectionDetail): string | null =>
    detail.status === 'reconnect_needed'
      ? t('settings.connectors.detail.expired')
      : detail.status === 'error'
        ? t('settings.connectors.detail.broken')
        : detail.last_error;
}

function RemoveConnectionModal({
  detail,
  name,
  onClose,
  onRemoved,
}: {
  detail: ConnectionDetail;
  name: string;
  onClose: () => void;
  onRemoved: () => void;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [sources, setSources] = useState<'keep' | 'delete'>('keep');
  const [tools, setTools] = useState<'keep' | 'delete'>('delete');
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

  const remove = () => {
    setPending(true);
    setFailed(false);
    connectorsService
      .remove(detail.id, { sources, tools }, token)
      .then((data) => {
        if (!data?.success) throw new Error('remove failed');
        onRemoved();
      })
      .catch(() => setFailed(true))
      .finally(() => setPending(false));
  };

  return (
    <Modal
      open
      onOpenChange={(open) => !open && onClose()}
      title={t('settings.connectors.remove.title', {
        name,
        interpolation: { escapeValue: false },
      })}
      description={t('settings.connectors.remove.description')}
      footer={
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={onClose}
          submitLabel={t('settings.connectors.detail.remove')}
          onSubmit={remove}
          pending={pending}
          destructive
        />
      }
    >
      <div className="flex flex-col gap-6">
        {failed && (
          <Alert variant="destructive">
            <CircleAlert />
            <AlertDescription>
              {t('settings.connectors.remove.failed')}
            </AlertDescription>
          </Alert>
        )}
        {detail.sources.length > 0 && (
          <FormField
            float={false}
            label={t('settings.connectors.remove.sourcesLabel', {
              count: detail.sources.length,
              formatted: formatCount(detail.sources.length),
            })}
          >
            <ToggleGroup
              type="single"
              value={sources}
              onValueChange={(value) =>
                value && setSources(value as 'keep' | 'delete')
              }
            >
              <ToggleGroupItem value="keep">
                {t('settings.connectors.remove.keepSources')}
              </ToggleGroupItem>
              <ToggleGroupItem value="delete">
                {t('settings.connectors.remove.deleteSources')}
              </ToggleGroupItem>
            </ToggleGroup>
          </FormField>
        )}
        {detail.tools.length > 0 && (
          <FormField
            float={false}
            label={t('settings.connectors.remove.toolsLabel', {
              count: detail.tools.length,
              formatted: formatCount(detail.tools.length),
            })}
          >
            <ToggleGroup
              type="single"
              value={tools}
              onValueChange={(value) =>
                value && setTools(value as 'keep' | 'delete')
              }
            >
              <ToggleGroupItem value="delete">
                {t('settings.connectors.remove.deleteTools')}
              </ToggleGroupItem>
              <ToggleGroupItem value="keep">
                {t('settings.connectors.remove.keepTools')}
              </ToggleGroupItem>
            </ToggleGroup>
          </FormField>
        )}
      </div>
    </Modal>
  );
}

/** Names an account ("Alerts bot"), so two accounts of a service read apart. */
function RenameAccountModal({
  detail,
  onClose,
  onRenamed,
}: {
  detail: ConnectionDetail;
  onClose: () => void;
  onRenamed: () => void;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [name, setName] = useState(detail.account_name ?? '');
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

  const save = () => {
    setPending(true);
    setFailed(false);
    connectorsService
      .renameConnection(detail.id, name.trim(), token)
      .then((data) => {
        if (!data?.success) throw new Error('rename failed');
        onRenamed();
      })
      .catch(() => setFailed(true))
      .finally(() => setPending(false));
  };

  return (
    <Modal
      open
      size="sm"
      onOpenChange={(open) => !open && onClose()}
      title={t('settings.connectors.rename.title')}
      description={t('settings.connectors.rename.description')}
      footer={
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={onClose}
          submitLabel={t('settings.connectors.rename.save')}
          onSubmit={save}
          pending={pending}
          disabled={name.trim() === (detail.account_name ?? '')}
        />
      }
    >
      <div className="flex flex-col gap-5">
        {failed && (
          <Alert variant="destructive">
            <CircleAlert />
            <AlertDescription>
              {t('settings.connectors.rename.failed')}
            </AlertDescription>
          </Alert>
        )}
        <Input
          id="rename-account"
          label={t('settings.connectors.rename.label')}
          autoComplete="off"
          maxLength={ACCOUNT_NAME_MAX}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (
              e.key === 'Enter' &&
              name.trim() !== (detail.account_name ?? '')
            )
              save();
          }}
        />
      </div>
    </Modal>
  );
}

/** A connection tool's on/off switch: the one place it is turned on or off. */
function ToolSwitch({
  tool,
  onToggle,
}: {
  tool: ConnectionTool;
  onToggle: (toolId: string, on: boolean) => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const [on, setOn] = useState(tool.status);
  useEffect(() => setOn(tool.status), [tool.status]);
  return (
    <Switch
      checked={on}
      aria-label={t('settings.connectors.detail.toolSwitch', {
        name: tool.display_name,
        interpolation: { escapeValue: false },
      })}
      onCheckedChange={async (checked) => {
        const next = checked === true;
        setOn(next);
        if (!(await onToggle(tool.id, next))) setOn(!next);
      }}
    />
  );
}

/**
 * Lets agents make changes through a connection (GitHub's issues, comments
 * and pull requests) or only read. Switching re-reads the tool's actions.
 */
function WritesSwitch({
  detail,
  onSwitch,
}: {
  detail: ConnectionDetail;
  onSwitch: (detail: ConnectionDetail, allow: boolean) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [pending, setPending] = useState(false);
  const id = `writes-${detail.id}`;
  return (
    <SettingRows>
      <SettingRow
        label={t('settings.connectors.github.writes')}
        description={t('settings.connectors.github.writesDescription')}
        htmlFor={id}
        alignStart
      >
        <Switch
          id={id}
          checked={!!detail.writes}
          disabled={pending || detail.status !== 'connected'}
          onCheckedChange={(checked) => {
            setPending(true);
            onSwitch(detail, checked === true).finally(() => setPending(false));
          }}
        />
      </SettingRow>
    </SettingRows>
  );
}

function AccountSection({
  connector,
  detail,
  onReconnect,
  onDisconnect,
  onRemove,
  onRename,
  onSyncMore,
  onRefreshTools,
  onToggleTool,
  onSyncNow,
  onAddTools,
  onSwitchWrites,
}: {
  connector: ConnectorDefinition;
  detail: ConnectionDetail;
  onReconnect: (detail: ConnectionDetail) => void;
  onDisconnect: (detail: ConnectionDetail) => void;
  onRemove: (detail: ConnectionDetail) => void;
  onRename: (detail: ConnectionDetail) => void;
  onSyncMore: (detail: ConnectionDetail) => void;
  onRefreshTools: (detail: ConnectionDetail) => Promise<void>;
  /** Turns a tool of this connection on or off for agents and chat. */
  onToggleTool: (toolId: string, on: boolean) => Promise<boolean>;
  onSyncNow: (source: ConnectionSource) => void;
  /** Creates the tools a connection skipped while it was set up (GitHub's). */
  onAddTools: (detail: ConnectionDetail) => Promise<void>;
  /** Lets its tool make changes or only read (GitHub's). */
  onSwitchWrites: (detail: ConnectionDetail, allow: boolean) => Promise<void>;
}) {
  const { t } = useTranslation();
  const accountTitle = useAccountTitle();
  const problem = useProblem();
  const [refreshing, setRefreshing] = useState(false);
  const [addingTools, setAddingTools] = useState(false);
  const canAddTools =
    connector.setup.tools === 'ask' &&
    (connector.tool_templates?.length ?? 0) > 0 &&
    connector.publisher !== 'custom' &&
    detail.tools.length === 0 &&
    detail.status === 'connected';
  const canSync = connector.setup.sync !== 'off' && !!connector.sync_ingestor;
  const isMcp = detail.tools.some((tool) => tool.name === 'mcp_tool');
  // Hidden once an admin forbids changes; its tool then only reads anyway.
  const canSwitchWrites =
    !!connector.writes_allowed &&
    detail.writes !== null &&
    detail.writes !== undefined;
  const menu: MenuOption[] = [
    {
      icon: Pencil,
      label: t('settings.connectors.detail.rename'),
      onClick: () => onRename(detail),
    },
  ];
  if (detail.status !== 'disconnected') {
    menu.push({
      icon: Unplug,
      label: t('settings.connectors.detail.disconnect'),
      onClick: () => onDisconnect(detail),
      variant: 'destructive',
    });
  }
  menu.push({
    icon: Trash2,
    label: t('settings.connectors.detail.remove'),
    onClick: () => onRemove(detail),
    variant: 'destructive',
  });

  // An expired or failing sign-in gets its own box under the account, with
  // room to say what happened at any width.
  const broken =
    detail.status === 'reconnect_needed' || detail.status === 'error';

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Card variant="subtle" padding="none">
          <ListRows>
            <ListRow
              title={detail.account_name || accountTitle(detail)}
              description={
                detail.account_name ? (
                  accountTitle(detail)
                ) : !broken && detail.last_error ? (
                  <span title={detail.last_error}>{detail.last_error}</span>
                ) : undefined
              }
              trailing={
                <div className="flex shrink-0 items-center gap-2">
                  <Badge variant={STATUS_VARIANT[detail.status]}>
                    {t(`settings.connectors.connectionStatus.${detail.status}`)}
                  </Badge>
                  {!broken && detail.status !== 'connected' && (
                    <Button
                      type="button"
                      size="sm"
                      shape="pill"
                      variant="outline"
                      onClick={() => onReconnect(detail)}
                    >
                      <RefreshCw />
                      {t('settings.connectors.status.reconnect')}
                    </Button>
                  )}
                  <ActionMenu
                    triggerLabel={t('settings.connectors.detail.accountMenu')}
                    options={menu}
                  />
                </div>
              }
            />
          </ListRows>
        </Card>
        {broken && (
          <Alert variant="warning">
            <TriangleAlert />
            {/* The provider's own message stays on hover, for debugging. */}
            <AlertDescription title={detail.last_error ?? undefined}>
              {problem(detail)}
            </AlertDescription>
            <div className="mt-2">
              <Button
                type="button"
                size="sm"
                shape="pill"
                variant="outline"
                onClick={() => onReconnect(detail)}
              >
                <RefreshCw />
                {t('settings.connectors.status.reconnect')}
              </Button>
            </div>
          </Alert>
        )}
      </div>
      {canSync && (
        <section className="flex flex-col gap-2">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('settings.connectors.detail.sources')}
            actions={
              detail.status === 'connected' ? (
                <Button
                  type="button"
                  variant="link"
                  size="sm"
                  className="-mr-3"
                  onClick={() => onSyncMore(detail)}
                >
                  <Plus />
                  {t('settings.connectors.detail.syncMore')}
                </Button>
              ) : undefined
            }
          />
          {detail.sources.length === 0 ? (
            <EmptyState
              size="xs"
              illustration="none"
              title={t('settings.connectors.detail.noSources')}
            />
          ) : (
            <Card variant="subtle" padding="none">
              <ListRows>
                {detail.sources.map((source) => (
                  <ListRow
                    key={source.id}
                    title={source.name}
                    description={
                      source.last_sync
                        ? t('settings.connectors.detail.lastSync', {
                            date: formatDateTime(source.last_sync),
                            frequency: t(
                              `settings.sources.syncFrequency.${source.sync_frequency}`,
                              { defaultValue: source.sync_frequency },
                            ),
                            interpolation: { escapeValue: false },
                          })
                        : undefined
                    }
                    trailing={
                      source.sync_state === 'paused_reconnect' ? (
                        <Badge variant="warning">
                          {t('settings.connectors.detail.paused')}
                        </Badge>
                      ) : (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          shape="pill"
                          onClick={() => onSyncNow(source)}
                        >
                          {t('settings.connectors.detail.syncNow')}
                        </Button>
                      )
                    }
                  />
                ))}
              </ListRows>
            </Card>
          )}
        </section>
      )}
      {canAddTools && (
        <section className="flex flex-col gap-2">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('settings.connectors.detail.tools')}
            actions={
              <Button
                type="button"
                variant="link"
                size="sm"
                className="-mr-3"
                loading={addingTools}
                onClick={() => {
                  setAddingTools(true);
                  onAddTools(detail).finally(() => setAddingTools(false));
                }}
              >
                <Plus />
                {t('settings.connectors.detail.addTools')}
              </Button>
            }
          />
          <EmptyState
            size="xs"
            illustration="none"
            title={t('settings.connectors.detail.noTools')}
          />
        </section>
      )}
      {detail.tools.length > 0 && (
        <section className="flex flex-col gap-2">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('settings.connectors.detail.tools')}
            actions={
              isMcp && detail.status === 'connected' ? (
                <Button
                  type="button"
                  variant="link"
                  size="sm"
                  className="-mr-3"
                  loading={refreshing}
                  onClick={() => {
                    setRefreshing(true);
                    onRefreshTools(detail).finally(() => setRefreshing(false));
                  }}
                >
                  <RotateCw />
                  {t('settings.connectors.detail.refreshTools')}
                </Button>
              ) : undefined
            }
          />
          {detail.tools.map((tool) => (
            <div key={tool.id} className="flex flex-col gap-2">
              <SectionHeader
                as="h4"
                size="xs"
                title={tool.display_name}
                actions={<ToolSwitch tool={tool} onToggle={onToggleTool} />}
              />
              {canSwitchWrites && tool.name === 'mcp_tool' && (
                <WritesSwitch detail={detail} onSwitch={onSwitchWrites} />
              )}
              <ToolPermissions
                connectionId={detail.id}
                tool={tool}
                variant="subtle"
              />
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

/**
 * Everything about one connector: its accounts, the sources each syncs and
 * the tools each provides, with their permissions. Opens from a Connectors
 * page card.
 */
export default function ConnectionDrawer({
  connector,
  parts = [],
  onClose,
  onConnect,
}: {
  connector: ConnectorDefinition | null;
  /** The same service offered another way, shown here (Jira & Confluence). */
  parts?: ConnectorDefinition[];
  onClose: () => void;
  onConnect: (connector: ConnectorDefinition, options?: LaunchOptions) => void;
}) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const connections = useSelector(selectConnections);
  const [details, setDetails] = useState<ConnectionDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [toDisconnect, setToDisconnect] = useState<ConnectionDetail | null>(
    null,
  );
  const [toRemove, setToRemove] = useState<ConnectionDetail | null>(null);
  const [toRename, setToRename] = useState<ConnectionDetail | null>(null);

  const keys = [connector?.key, ...parts.map((part) => part.key)];
  const accountIds = connections
    .filter((connection) => keys.includes(connection.connector_key))
    .map((connection) => `${connection.id}:${connection.status}`)
    .join(',');

  useEffect(() => {
    if (!connector) return;
    const ids = accountIds
      ? accountIds.split(',').map((entry) => entry.split(':')[0])
      : [];
    let cancelled = false;
    setLoading(true);
    setFailed(false);
    Promise.all(ids.map((id) => connectorsService.getConnection(id, token)))
      .then((responses) => {
        if (cancelled) return;
        if (responses.some((response) => !response?.success)) {
          setFailed(true);
          return;
        }
        setDetails(responses.map((response) => response.connection));
      })
      .catch(() => !cancelled && setFailed(true))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [connector, accountIds, token, reloadKey]);

  const refresh = useCallback(() => {
    dispatch(loadConnectors({ token }));
    setReloadKey((key) => key + 1);
  }, [dispatch, token]);

  const confirmDisconnect = () => {
    if (!toDisconnect) return;
    connectorsService
      .disconnect(toDisconnect.id, token)
      .then((data) => {
        if (!data?.success) throw new Error('disconnect failed');
      })
      .catch(() =>
        dispatch(
          showActionToast({
            variant: 'destructive',
            message: t('settings.connectors.disconnect.failed'),
          }),
        ),
      )
      .finally(() => {
        setToDisconnect(null);
        refresh();
      });
  };

  const reconnect = (detail: ConnectionDetail) => {
    if (!connector) return;
    // A part's account (Jira & Confluence under Confluence) reconnects
    // through its own connector.
    const target =
      parts.find((part) => part.key === detail.connector_key) ?? connector;
    const mcpTool = detail.tools.find((tool) => tool.name === 'mcp_tool');
    onConnect(target, {
      mode: 'reconnect',
      connectionId: detail.id,
      mcpServer:
        mcpTool && detail.server_url
          ? {
              id: mcpTool.id,
              displayName: mcpTool.display_name,
              server_url: detail.server_url,
              auth_type: detail.auth_kind === 'mcp_oauth' ? 'oauth' : 'none',
            }
          : undefined,
    });
  };

  const toggleTool = async (toolId: string, on: boolean) => {
    try {
      const response = await userService.updateToolStatus(
        { id: toolId, status: on },
        token,
      );
      if (!response.ok) throw new Error('toggle failed');
      return true;
    } catch {
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t('settings.connectors.detail.toolSwitchFailed'),
        }),
      );
      return false;
    }
  };

  const syncNow = async (source: ConnectionSource) => {
    try {
      // Drive, SharePoint and Confluence sources sync through the connector
      // endpoint; S3 and Reddit through the remote-source one.
      const response = source.type?.startsWith('connector')
        ? await userService.syncConnector(source.id, token)
        : await userService.syncSource({ source_id: source.id }, token);
      const data = await response.json();
      if (!data?.success) throw new Error('sync failed');
      dispatch(
        showActionToast({
          variant: 'success',
          message: t('settings.connectors.detail.syncStarted', {
            name: source.name,
            interpolation: { escapeValue: false },
          }),
        }),
      );
    } catch {
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t('settings.connectors.detail.syncFailed'),
        }),
      );
    }
  };

  const addTools = async (detail: ConnectionDetail) => {
    const data = await connectorsService
      .setup(detail.id, { create_tools: true }, token)
      .catch(() => null);
    if (!data?.success) {
      dispatch(
        showActionToast({
          variant: 'destructive',
          message:
            data?.code === 'tools_unavailable'
              ? t('settings.connectors.wizard.toolsUnavailable', {
                  name: connector ? connectorName(t, connector) : detail.name,
                  interpolation: { escapeValue: false },
                })
              : t('settings.connectors.detail.addToolsFailed'),
        }),
      );
    }
    refresh();
  };

  const switchWrites = async (detail: ConnectionDetail, allow: boolean) => {
    const data = await connectorsService
      .setWrites(detail.id, allow, token)
      .catch(() => null);
    if (!data?.success) {
      dispatch(
        showActionToast({
          variant: 'destructive',
          message:
            data?.code === 'writes_forbidden'
              ? t('settings.connectors.github.writesForbidden')
              : data?.code === 'tools_unavailable'
                ? t('settings.connectors.wizard.toolsUnavailable', {
                    name: connector ? connectorName(t, connector) : detail.name,
                    interpolation: { escapeValue: false },
                  })
                : t('settings.connectors.github.writesFailed'),
        }),
      );
    }
    refresh();
  };

  const refreshTools = async (detail: ConnectionDetail) => {
    const data = await connectorsService.refreshTools(detail.id, token);
    dispatch(
      showActionToast(
        data?.success
          ? {
              variant: 'success',
              message: t('settings.connectors.detail.refreshed', {
                added: formatCount(data.added?.length ?? 0),
                removed: formatCount(data.removed?.length ?? 0),
              }),
            }
          : {
              variant: 'destructive',
              message: t('settings.connectors.detail.refreshFailed'),
            },
      ),
    );
    refresh();
  };

  if (!connector) return null;
  const name = connectorName(t, connector);
  const ownDetails = details.filter(
    (detail) => detail.connector_key === connector.key,
  );

  return (
    <>
      <Sheet open onOpenChange={(open) => !open && onClose()}>
        <SheetContent
          side="right"
          size="detail"
          closeLabel={t('agents.close')}
          className="overflow-y-auto"
        >
          <div className="flex flex-col gap-6 p-6">
            {/* pr-12 keeps the header clear of the close X. */}
            <div className="flex items-center gap-4 pr-12">
              <span className="bg-muted flex size-12 shrink-0 items-center justify-center rounded-xl">
                <ConnectorIcon icon={connector.icon} className="size-7" />
              </span>
              <SheetTitle className="min-w-0 truncate">{name}</SheetTitle>
            </div>
            <SheetDescription>
              {connectorDescription(t, connector)}
            </SheetDescription>
            <CapabilityBadges capabilities={connector.capabilities} />

            {connector.publisher === 'custom' && (
              <Alert variant="warning" role="note">
                <TriangleAlert />
                <AlertDescription>
                  {t('settings.connectors.unverified')}
                </AlertDescription>
              </Alert>
            )}

            {connector.needs_setup && (
              <ConnectorSetupNotice connector={connector} />
            )}

            <section className="flex flex-col gap-3">
              <SectionHeader
                as="h3"
                size="xs"
                title={t('settings.connectors.detail.accounts')}
                actions={
                  connector.available && ownDetails.length > 0 ? (
                    <Button
                      type="button"
                      variant="link"
                      size="sm"
                      className="-mr-3"
                      onClick={() => onConnect(connector)}
                    >
                      <Plus />
                      {t('settings.connectors.detail.connectAnother')}
                    </Button>
                  ) : undefined
                }
              />
              {loading && details.length === 0 ? (
                <LoadingState fill="block" />
              ) : failed ? (
                <EmptyState
                  tone="destructive"
                  size="sm"
                  illustration="none"
                  title={t('settings.connectors.detail.failed')}
                  action={
                    <Button
                      variant="outline"
                      size="sm"
                      shape="pill"
                      onClick={() => setReloadKey((key) => key + 1)}
                    >
                      {t('retry')}
                    </Button>
                  }
                />
              ) : ownDetails.length === 0 ? (
                <EmptyState
                  size="xs"
                  illustration="none"
                  title={t('settings.connectors.detail.noAccounts')}
                  action={
                    connector.available ? (
                      <Button
                        type="button"
                        shape="pill"
                        onClick={() => onConnect(connector)}
                      >
                        {t('settings.connectors.status.connect')}
                      </Button>
                    ) : undefined
                  }
                />
              ) : (
                <div className="flex flex-col gap-6">
                  {ownDetails.map((detail) => (
                    <AccountSection
                      key={detail.id}
                      connector={connector}
                      detail={detail}
                      onReconnect={reconnect}
                      onDisconnect={setToDisconnect}
                      onRemove={setToRemove}
                      onRename={setToRename}
                      onSyncMore={(d) =>
                        onConnect(connector, {
                          mode: 'sync',
                          connectionId: d.id,
                        })
                      }
                      onRefreshTools={refreshTools}
                      onToggleTool={toggleTool}
                      onSyncNow={syncNow}
                      onAddTools={addTools}
                      onSwitchWrites={switchWrites}
                    />
                  ))}
                </div>
              )}
            </section>

            {parts.map((part) => {
              const partDetails = details.filter(
                (detail) => detail.connector_key === part.key,
              );
              return (
                <section key={part.key} className="flex flex-col gap-3">
                  <SectionHeader
                    as="h3"
                    size="xs"
                    title={connectorName(t, part)}
                    description={connectorDescription(t, part)}
                    actions={
                      part.available && partDetails.length === 0 ? (
                        <Button
                          type="button"
                          size="sm"
                          shape="pill"
                          onClick={() => onConnect(part)}
                        >
                          {t('settings.connectors.status.connect')}
                        </Button>
                      ) : undefined
                    }
                  />
                  <CapabilityBadges capabilities={part.capabilities} />
                  {partDetails.map((detail) => (
                    <AccountSection
                      key={detail.id}
                      connector={part}
                      detail={detail}
                      onReconnect={reconnect}
                      onDisconnect={setToDisconnect}
                      onRemove={setToRemove}
                      onRename={setToRename}
                      onSyncMore={(d) =>
                        onConnect(part, { mode: 'sync', connectionId: d.id })
                      }
                      onRefreshTools={refreshTools}
                      onToggleTool={toggleTool}
                      onSyncNow={syncNow}
                      onAddTools={addTools}
                      onSwitchWrites={switchWrites}
                    />
                  ))}
                </section>
              );
            })}
          </div>
        </SheetContent>
      </Sheet>
      <ConfirmationModal
        message={t('settings.connectors.disconnect.title', {
          name,
          interpolation: { escapeValue: false },
        })}
        description={t('settings.connectors.disconnect.body', {
          count: toDisconnect?.source_count ?? 0,
          formatted: formatCount(toDisconnect?.source_count ?? 0),
        })}
        modalState={toDisconnect ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state) => state === 'INACTIVE' && setToDisconnect(null)}
        handleSubmit={confirmDisconnect}
        submitLabel={t('settings.connectors.detail.disconnect')}
        variant="destructive"
      />
      {toRename && (
        <RenameAccountModal
          detail={toRename}
          onClose={() => setToRename(null)}
          onRenamed={() => {
            setToRename(null);
            refresh();
          }}
        />
      )}
      {toRemove && (
        <RemoveConnectionModal
          detail={toRemove}
          name={name}
          onClose={() => setToRemove(null)}
          onRemoved={() => {
            setToRemove(null);
            refresh();
          }}
        />
      )}
    </>
  );
}
