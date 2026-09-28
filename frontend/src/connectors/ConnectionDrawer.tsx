import {
  CircleAlert,
  ExternalLink,
  Plus,
  RefreshCw,
  Unplug,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import connectorsService from '../api/services/connectorsService';
import { Alert, AlertDescription, AlertTitle } from '../components/ui/alert';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { ActionMenu } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import { ListRow, ListRows } from '../components/ui/list-row';
import { LoadingState } from '../components/ui/loading-state';
import { SectionHeader } from '../components/ui/section-header';
import { Sheet, SheetContent, SheetTitle } from '../components/ui/sheet';
import ConfirmationModal from '../modals/ConfirmationModal';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import { formatDateTime } from '../utils/dateTimeUtils';
import { CapabilityBadges } from './ConnectorCard';
import ConnectorIcon from './ConnectorIcon';
import { selectConnections, loadConnectors } from './connectorsSlice';
import { connectorDescription, connectorName } from './i18n';
import type {
  ConnectionDetail,
  ConnectionStatus,
  ConnectionTool,
  ConnectorDefinition,
} from './types';

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

const PERMISSION_VARIANT = {
  always: 'success',
  ask: 'warning',
  off: 'neutral',
} as const;

function ToolActions({ tool }: { tool: ConnectionTool }) {
  const { t } = useTranslation();
  const groups = (['read', 'write'] as const)
    .map((access) => ({
      access,
      actions: tool.actions.filter((action) => action.access === access),
    }))
    .filter((group) => group.actions.length > 0);
  return (
    <Card padding="sm" className="gap-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-foreground min-w-0 truncate text-sm font-medium">
          {tool.display_name}
        </span>
        <Badge variant={tool.status ? 'success' : 'neutral'}>
          {tool.status
            ? t('settings.connectors.detail.toolOn')
            : t('settings.connectors.detail.toolOff')}
        </Badge>
      </div>
      {groups.map((group) => (
        <div key={group.access} className="flex flex-col gap-2">
          <SectionHeader
            as="h4"
            size="sm"
            title={t(`settings.connectors.capability.${group.access}`)}
          />
          <ul className="flex flex-col gap-2">
            {group.actions.map((action) => (
              <li
                key={action.name}
                className="flex items-center justify-between gap-3"
              >
                <span
                  className="text-foreground min-w-0 truncate font-mono text-xs"
                  title={action.description || action.name}
                >
                  {action.name}
                </span>
                <Badge variant={PERMISSION_VARIANT[action.permission]}>
                  {t(`settings.connectors.permission.${action.permission}`)}
                </Badge>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </Card>
  );
}

function AccountSection({
  detail,
  onReconnect,
  onDisconnect,
}: {
  detail: ConnectionDetail;
  onReconnect: () => void;
  onDisconnect: (detail: ConnectionDetail) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-6">
      <Card padding="none">
        <ListRows>
          <ListRow
            title={t('settings.connectors.detail.connectedAs', {
              account: detail.account_label,
              interpolation: { escapeValue: false },
            })}
            description={
              detail.last_error ? (
                <span title={detail.last_error}>{detail.last_error}</span>
              ) : undefined
            }
            trailing={
              <div className="flex shrink-0 items-center gap-2">
                <Badge variant={STATUS_VARIANT[detail.status]}>
                  {t(`settings.connectors.connectionStatus.${detail.status}`)}
                </Badge>
                {detail.status !== 'connected' && (
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    onClick={onReconnect}
                  >
                    <RefreshCw />
                    {t('settings.connectors.status.reconnect')}
                  </Button>
                )}
                {detail.status !== 'disconnected' && (
                  <ActionMenu
                    triggerLabel={t('settings.connectors.detail.accountMenu')}
                    options={[
                      {
                        icon: Unplug,
                        label: t('settings.connectors.detail.disconnect'),
                        onClick: () => onDisconnect(detail),
                        variant: 'destructive',
                      },
                    ]}
                  />
                )}
              </div>
            }
          />
        </ListRows>
      </Card>
      {detail.sources.length > 0 && (
        <section className="flex flex-col gap-2">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('settings.connectors.detail.sources')}
          />
          <Card padding="none">
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
                    ) : undefined
                  }
                />
              ))}
            </ListRows>
          </Card>
        </section>
      )}
      {detail.tools.length > 0 && (
        <section className="flex flex-col gap-2">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('settings.connectors.detail.tools')}
          />
          {detail.tools.map((tool) => (
            <ToolActions key={tool.id} tool={tool} />
          ))}
        </section>
      )}
    </div>
  );
}

/**
 * Everything about one connector: its accounts, the sources each syncs and
 * the tools each provides. Opens from a Connectors page card.
 */
export default function ConnectionDrawer({
  connector,
  onClose,
  onConnect,
}: {
  connector: ConnectorDefinition | null;
  onClose: () => void;
  onConnect: (connector: ConnectorDefinition) => void;
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

  const accountIds = connections
    .filter((connection) => connection.connector_key === connector?.key)
    .map((connection) => connection.id)
    .join(',');

  useEffect(() => {
    if (!connector) return;
    const ids = accountIds ? accountIds.split(',') : [];
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
    connectorsService.disconnect(toDisconnect.id, token).finally(() => {
      setToDisconnect(null);
      refresh();
    });
  };

  if (!connector) return null;
  const name = connectorName(t, connector);

  return (
    <>
      <Sheet open onOpenChange={(open) => !open && onClose()}>
        <SheetContent
          side="right"
          aria-describedby={undefined}
          className="w-full overflow-y-auto sm:max-w-xl"
        >
          <div className="flex flex-col gap-6 p-6">
            <div className="flex items-start gap-4 pr-8">
              <span className="bg-muted flex size-12 shrink-0 items-center justify-center rounded-xl">
                <ConnectorIcon icon={connector.icon} className="size-7" />
              </span>
              <div className="flex min-w-0 flex-col gap-1">
                <SheetTitle className="truncate">{name}</SheetTitle>
                <p className="text-muted-foreground text-sm">
                  {t(`settings.connectors.publisher.${connector.publisher}`)}
                </p>
              </div>
            </div>
            <p className="text-muted-foreground text-sm">
              {connectorDescription(t, connector)}
            </p>
            <CapabilityBadges capabilities={connector.capabilities} />

            {connector.needs_setup && (
              <Alert variant="warning">
                <CircleAlert />
                <AlertTitle>
                  {t('settings.connectors.status.needsAdminSetup')}
                </AlertTitle>
                <AlertDescription>
                  <div className="flex flex-col gap-2">
                    {connector.missing_settings.length > 0 ? (
                      <>
                        <span>{t('settings.connectors.setupSettings')}</span>
                        <code className="font-mono text-xs wrap-anywhere">
                          {connector.missing_settings.join(', ')}
                        </code>
                      </>
                    ) : (
                      <span>{t('settings.connectors.askAdmin')}</span>
                    )}
                    {connector.docs_url && (
                      <Button
                        variant="link"
                        size="inline"
                        asChild
                        className="w-fit"
                      >
                        <a
                          href={connector.docs_url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {t('settings.connectors.setupGuide')}
                          <ExternalLink />
                        </a>
                      </Button>
                    )}
                  </div>
                </AlertDescription>
              </Alert>
            )}

            <section className="flex flex-col gap-3">
              <SectionHeader
                as="h3"
                size="xs"
                title={t('settings.connectors.detail.accounts')}
                actions={
                  connector.available && details.length > 0 ? (
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
              {loading ? (
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
                      onClick={() => setReloadKey((key) => key + 1)}
                    >
                      {t('retry')}
                    </Button>
                  }
                />
              ) : details.length === 0 ? (
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
                <div className="flex flex-col gap-8">
                  {details.map((detail) => (
                    <AccountSection
                      key={detail.id}
                      detail={detail}
                      onReconnect={() => onConnect(connector)}
                      onDisconnect={setToDisconnect}
                    />
                  ))}
                </div>
              )}
            </section>
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
        })}
        modalState={toDisconnect ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state) => state === 'INACTIVE' && setToDisconnect(null)}
        handleSubmit={confirmDisconnect}
        submitLabel={t('settings.connectors.detail.disconnect')}
        variant="destructive"
      />
    </>
  );
}
