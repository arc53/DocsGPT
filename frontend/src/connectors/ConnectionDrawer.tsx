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
import type { TFunction } from 'i18next';
import { useDispatch, useSelector } from 'react-redux';

import connectorsService from '../api/services/connectorsService';
import userService from '../api/services/userService';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Avatar } from '../components/ui/avatar';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { ActionMenu, type MenuOption } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import { FormField } from '../components/ui/form-field';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { ListRow, ListRows } from '../components/ui/list-row';
import { LoadingState } from '../components/ui/loading-state';
import { Modal, ModalActions } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import { Separator } from '../components/ui/separator';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import { Switch } from '../components/ui/switch';
import { PanelBody, PanelHeader, SidePanel } from '../components/ui/side-panel';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import { showActionToast } from '../notifications/actionToastSlice';
import ConfirmationModal from '../modals/ConfirmationModal';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import { formatCount, formatDateTime } from '../utils/dateTimeUtils';
import { ACCOUNT_NAME_MAX } from './accounts';
import { CapabilityBadges } from './ConnectorCard';
import ConnectorIcon from './ConnectorIcon';
import ConnectorSetupNotice from './ConnectorSetupNotice';
import {
  connectionNeedsSignIn,
  loadConnectors,
  selectConnections,
  selectConnectorsFailed,
  selectConnectorsLoaded,
} from './connectorsSlice';
import {
  accountLine,
  connectorDescription,
  connectorName,
  isKeyHint,
} from './i18n';
import ToolPermissions from './ToolPermissions';
import type {
  Capability,
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
  error: 'warning',
  pending: 'neutral',
};

/**
 * An account's state: an expired or failing sign-in is one word, Reconnect,
 * as on every other connector surface.
 */
function StatusBadge({ detail }: { detail: ConnectionDetail }) {
  const { t } = useTranslation();
  return (
    <Badge variant={STATUS_VARIANT[detail.status]}>
      {connectionNeedsSignIn(detail)
        ? t('settings.connectors.status.reconnect')
        : t(`settings.connectors.connectionStatus.${detail.status}`)}
    </Badge>
  );
}

/**
 * What identifies an account under the name it was given, as the Tools
 * card's account line has it (the key hint for pasted credentials, else its
 * label). The status Badge beside it says whether it works.
 */
const accountIdentity = (t: TFunction, detail: ConnectionDetail) =>
  accountLine(t, { ...detail, account_name: null });

/**
 * The account a confirmation names: the name it was given, else its label;
 * a bare key hint reads worse than the service, so that falls back to the
 * account's own service (a part's, not its parent's).
 */
function confirmName(detail: ConnectionDetail, service: string) {
  return (
    detail.account_name ||
    (isKeyHint(detail.account_label) ? '' : detail.account_label) ||
    service
  );
}

/**
 * A tool's heading: the server adds " · account" to tell two accounts'
 * tools apart in pickers; here the account row already says which, so the
 * suffix goes (as on the Tools page's cards).
 */
function toolTitle(tool: ConnectionTool, detail: ConnectionDetail) {
  return detail.name && tool.display_name.startsWith(`${detail.name} · `)
    ? detail.name
    : tool.display_name;
}

/**
 * Whether the drawer can add a connection's tools back (skipped during setup,
 * or deleted from the Tools page since). The setup call recreates built-in
 * tool templates, GitHub's MCP tool and an MCP preset's (Notion, Linear…),
 * rebuilt from its sign-in. A custom server's tool comes only from its own
 * save, so it is not offered here.
 */
function recreatesTools(connector: ConnectorDefinition) {
  const templates = connector.tool_templates ?? [];
  if (connector.publisher === 'custom' || templates.length === 0) return false;
  if (connector.setup.tools === 'ask') return true;
  if (connector.publisher === 'preset') return templates.includes('mcp_tool');
  return (
    connector.setup.tools === 'auto' &&
    templates.some(
      (template) => template !== 'mcp_tool' && template !== 'api_tool',
    )
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

/**
 * Forgets an account's sign-in and keeps the account, its knowledge and its
 * tools, so Reconnect brings it back. Nothing is deleted, so the submit is
 * the primary; it shows pending while the request runs and a failure stays
 * in the modal.
 */
function DisconnectConnectionModal({
  detail,
  name,
  onClose,
  onDisconnected,
}: {
  detail: ConnectionDetail;
  /** The account, as `confirmName` gives it. */
  name: string;
  onClose: () => void;
  onDisconnected: () => void;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const disconnect = () =>
    connectorsService.disconnect(detail.id, token).then((data) => {
      if (!data?.success) throw new Error('disconnect failed');
      onDisconnected();
    });

  // Say only what this account has: a sync-only one has no tools to stop.
  const sources = detail.sources.length;
  const body =
    sources > 0 && detail.tools.length > 0
      ? 'bodyBoth'
      : sources > 0
        ? 'bodySources'
        : detail.tools.length > 0
          ? 'bodyTools'
          : 'bodyNone';

  return (
    <ConfirmationModal
      modalState="ACTIVE"
      setModalState={(state) => state === 'INACTIVE' && onClose()}
      message={t('settings.connectors.disconnect.title', {
        name,
        interpolation: { escapeValue: false },
      })}
      description={t(`settings.connectors.disconnect.${body}`, {
        count: sources,
        formatted: formatCount(sources),
      })}
      submitLabel={t('settings.connectors.detail.disconnect')}
      handleSubmit={disconnect}
      error={t('settings.connectors.disconnect.failed')}
    />
  );
}

function RemoveConnectionModal({
  detail,
  name,
  onClose,
  onRemoved,
}: {
  detail: ConnectionDetail;
  /** The account, as `confirmName` gives it. */
  name: string;
  onClose: () => void;
  onRemoved: () => void;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [sources, setSources] = useState<'keep' | 'delete'>('keep');
  const [tools, setTools] = useState<'keep' | 'delete'>('delete');

  const remove = () =>
    connectorsService
      .remove(detail.id, { sources, tools }, token)
      .then((data) => {
        if (!data?.success) throw new Error('remove failed');
        onRemoved();
      });

  return (
    <ConfirmationModal
      modalState="ACTIVE"
      setModalState={(state) => state === 'INACTIVE' && onClose()}
      message={t('settings.connectors.remove.title', {
        name,
        interpolation: { escapeValue: false },
      })}
      description={t('settings.connectors.remove.description')}
      submitLabel={t('settings.connectors.detail.remove')}
      handleSubmit={remove}
      error={t('settings.connectors.remove.failed')}
      variant="destructive"
    >
      <div className="flex flex-col gap-6">
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
              fill
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
              fill
              value={tools}
              onValueChange={(value) =>
                value && setTools(value as 'keep' | 'delete')
              }
            >
              <ToggleGroupItem value="keep">
                {t('settings.connectors.remove.keepTools')}
              </ToggleGroupItem>
              <ToggleGroupItem value="delete">
                {t('settings.connectors.remove.deleteTools')}
              </ToggleGroupItem>
            </ToggleGroup>
          </FormField>
        )}
      </div>
    </ConfirmationModal>
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

/**
 * A connection tool's "In my chats" switch: the owner's own preference, the
 * same one as on the tool's card. Teammates the tool is shared with keep
 * their own, so it never turns the tool off for them.
 */
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
  const id = `connection-tool-in-chats-${tool.id}`;
  return (
    <span className="flex shrink-0 items-center gap-2">
      <Label htmlFor={id} className="text-muted-foreground text-xs font-normal">
        {t('settings.tools.inMyChats')}
      </Label>
      <Switch
        id={id}
        checked={on}
        aria-label={t('settings.tools.useInMyChatsAria', {
          toolName: tool.display_name,
          interpolation: { escapeValue: false },
        })}
        onCheckedChange={async (checked) => {
          const next = checked === true;
          setOn(next);
          if (!(await onToggle(tool.id, next))) setOn(!next);
        }}
      />
    </span>
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

/**
 * The account to show from ``accounts``: the one picked, else one that needs
 * signing in again (so a problem is not hidden behind another account), else
 * the first.
 */
function shownAccount(
  accounts: ConnectionDetail[],
  picked: string | undefined,
): ConnectionDetail | undefined {
  return (
    accounts.find((account) => account.id === picked) ??
    accounts.find(connectionNeedsSignIn) ??
    accounts[0]
  );
}

type AccountHandlers = {
  onReconnect: (detail: ConnectionDetail) => void;
  onDisconnect: (detail: ConnectionDetail) => void;
  onRemove: (detail: ConnectionDetail) => void;
  onRename: (detail: ConnectionDetail) => void;
  onSyncMore: (detail: ConnectionDetail) => void;
  onRefreshTools: (detail: ConnectionDetail) => Promise<void>;
  /** Turns a tool of this connection on or off for agents and chat. */
  onToggleTool: (toolId: string, on: boolean) => Promise<boolean>;
  onSyncNow: (source: ConnectionSource) => void;
  /** Creates the tools a connection lacks (skipped at setup, or deleted).
   * Resolves to what went wrong, in plain words, or null. */
  onAddTools: (detail: ConnectionDetail) => Promise<string | null>;
  /** Lets its tool make changes or only read (GitHub's). */
  onSwitchWrites: (detail: ConnectionDetail, allow: boolean) => Promise<void>;
};

/**
 * One account in a service's account list: its name, account line, status
 * and ⋯. With several accounts the row picks which one's knowledge and tools
 * show below: a stretched button covers the row and the ⋯ sits above it, so
 * neither control is inside the other.
 */
function AccountRow({
  detail,
  selectable,
  selected,
  onSelect,
  onReconnect,
  onDisconnect,
  onRemove,
  onRename,
}: {
  detail: ConnectionDetail;
  selectable: boolean;
  selected: boolean;
  onSelect: () => void;
} & Pick<
  AccountHandlers,
  'onReconnect' | 'onDisconnect' | 'onRemove' | 'onRename'
>) {
  const { t } = useTranslation();
  const broken = connectionNeedsSignIn(detail);
  const title = accountLine(t, detail);
  const menu: MenuOption[] = [
    {
      icon: Pencil,
      label: t('settings.connectors.detail.rename'),
      onClick: () => onRename(detail),
    },
  ];
  // Disconnect only forgets the sign-in (Reconnect undoes it), so it is an
  // ordinary item; Remove deletes, after a rule.
  if (detail.status !== 'disconnected') {
    menu.push({
      icon: Unplug,
      label: t('settings.connectors.detail.disconnect'),
      onClick: () => onDisconnect(detail),
    });
  }
  menu.push({
    icon: Trash2,
    label: t('settings.connectors.detail.remove'),
    onClick: () => onRemove(detail),
    variant: 'destructive',
    separatorBefore: true,
  });

  return (
    <ListRow
      interactive={selectable}
      selected={selectable && selected}
      asChild={selectable}
      title={
        selectable ? (
          <button
            type="button"
            data-account-select=""
            aria-current={selected ? 'true' : undefined}
            className="block max-w-full cursor-pointer truncate text-left outline-none after:absolute after:inset-0"
            onClick={onSelect}
          >
            {title}
          </button>
        ) : (
          title
        )
      }
      description={
        detail.account_name ? (
          accountIdentity(t, detail)
        ) : !broken && detail.last_error ? (
          <span title={detail.last_error}>{detail.last_error}</span>
        ) : undefined
      }
      trailing={
        <div className="relative z-10 flex shrink-0 items-center gap-2">
          <StatusBadge detail={detail} />
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
    >
      {/* The row's box: it holds the stretched button, so it draws that
          button's focus ring (DESIGN "A clickable card that holds a link"). */}
      {selectable ? (
        <div className="has-[[data-account-select]:focus-visible]:ring-ring/50 relative has-[[data-account-select]:focus-visible]:ring-3 has-[[data-account-select]:focus-visible]:ring-inset" />
      ) : undefined}
    </ListRow>
  );
}

/** The shown account's knowledge and tools, under the service's account list. */
function AccountContent({
  connector,
  detail,
  onSyncMore,
  onRefreshTools,
  onToggleTool,
  onSyncNow,
  onAddTools,
  onSwitchWrites,
}: {
  connector: ConnectorDefinition;
  detail: ConnectionDetail;
} & Omit<
  AccountHandlers,
  'onReconnect' | 'onDisconnect' | 'onRemove' | 'onRename'
>) {
  const { t } = useTranslation();
  const [refreshing, setRefreshing] = useState(false);
  const [addingTools, setAddingTools] = useState(false);
  const [addToolsError, setAddToolsError] = useState<string | null>(null);
  const canAddTools =
    recreatesTools(connector) &&
    detail.tools.length === 0 &&
    detail.status === 'connected';
  const canSync = connector.setup.sync !== 'off' && !!connector.sync_ingestor;
  const isMcp = detail.tools.some((tool) => tool.name === 'mcp_tool');
  // Hidden once an admin forbids changes; its tool then only reads anyway.
  const canSwitchWrites =
    !!connector.writes_allowed &&
    detail.writes !== null &&
    detail.writes !== undefined;

  return (
    <>
      {canSync && (
        <section className="flex flex-col gap-2">
          <SectionHeader
            as="h4"
            size="xs"
            title={t('settings.connectors.detail.sources')}
            actions={
              detail.status === 'connected' ? (
                <Button
                  type="button"
                  variant="link"
                  size="sm"
                  className="-mr-2.5"
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
            <Card variant="subtle" padding="none" className="overflow-hidden">
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
            as="h4"
            size="xs"
            title={t('settings.connectors.detail.tools')}
            actions={
              <Button
                type="button"
                variant="link"
                size="sm"
                className="-mr-2.5"
                loading={addingTools}
                onClick={() => {
                  setAddingTools(true);
                  setAddToolsError(null);
                  onAddTools(detail)
                    .then(setAddToolsError)
                    .finally(() => setAddingTools(false));
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
          {addToolsError && (
            <Alert variant="destructive">
              <CircleAlert />
              <AlertDescription>{addToolsError}</AlertDescription>
            </Alert>
          )}
        </section>
      )}
      {detail.tools.length > 0 && (
        <section className="flex flex-col gap-2">
          <SectionHeader
            as="h4"
            size="xs"
            title={t('settings.connectors.detail.tools')}
            description={t('settings.connectors.detail.toolsHint')}
            actions={
              isMcp && detail.status === 'connected' ? (
                <Button
                  type="button"
                  variant="link"
                  size="sm"
                  className="-mr-2.5"
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
                as="h5"
                size="xs"
                title={toolTitle(tool, detail)}
                actions={<ToolSwitch tool={tool} onToggle={onToggleTool} />}
              />
              <ToolPermissions
                connectionId={detail.id}
                tool={tool}
                groupHeadingAs="h6"
                variant="subtle"
              >
                {canSwitchWrites && tool.name === 'mcp_tool' ? (
                  <WritesSwitch detail={detail} onSwitch={onSwitchWrites} />
                ) : null}
              </ToolPermissions>
            </div>
          ))}
        </section>
      )}
    </>
  );
}

/**
 * One service in the drawer (the connector, or a part of it such as Jira &
 * Confluence under Confluence): a header row with "Connect another account",
 * every account as a row, then the shown account's knowledge and tools.
 * Each service is the same section, so a part never reads as a subsection
 * of the parent's account.
 */
function ServiceSection({
  service,
  heading,
  description,
  accounts,
  picked,
  onPick,
  onConnect,
  ...handlers
}: {
  service: ConnectorDefinition;
  heading: string;
  /** A part's own description; the parent's is in the panel header. */
  description?: string;
  accounts: ConnectionDetail[];
  picked: string | undefined;
  onPick: (id: string) => void;
  onConnect: () => void;
} & AccountHandlers) {
  const { t } = useTranslation();
  const problem = useProblem();
  const shown = shownAccount(accounts, picked);
  const selectable = accounts.length > 1;

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <SectionHeader
            as="h3"
            size="xs"
            title={heading}
            actions={
              service.available && accounts.length > 0 ? (
                <Button
                  type="button"
                  variant="link"
                  size="sm"
                  className="-mr-2.5"
                  onClick={onConnect}
                >
                  <Plus />
                  {t('settings.connectors.detail.connectAnother')}
                </Button>
              ) : undefined
            }
          />
          {description && (
            <p className="text-muted-foreground text-sm">{description}</p>
          )}
        </div>
        {accounts.length === 0 ? (
          service.needs_setup ? (
            <ConnectorSetupNotice connector={service} />
          ) : (
            <EmptyState
              size="xs"
              illustration="none"
              title={t('settings.connectors.detail.noAccounts')}
              action={
                service.available ? (
                  <Button type="button" shape="pill" onClick={onConnect}>
                    {t('settings.connectors.status.connect')}
                  </Button>
                ) : undefined
              }
            />
          )
        ) : (
          <Card variant="subtle" padding="none" className="overflow-hidden">
            <ListRows>
              {accounts.map((account) => (
                <AccountRow
                  key={account.id}
                  detail={account}
                  selectable={selectable}
                  selected={account.id === shown?.id}
                  onSelect={() => onPick(account.id)}
                  onReconnect={handlers.onReconnect}
                  onDisconnect={handlers.onDisconnect}
                  onRemove={handlers.onRemove}
                  onRename={handlers.onRename}
                />
              ))}
            </ListRows>
          </Card>
        )}
        {/* An expired or failing sign-in gets its own box under the list,
            with room to say what happened at any width. */}
        {shown && connectionNeedsSignIn(shown) && (
          <Alert variant="warning">
            <TriangleAlert />
            {/* The provider's own message stays on hover, for debugging. */}
            <AlertDescription title={shown.last_error ?? undefined}>
              {problem(shown)}
            </AlertDescription>
            <div className="mt-2">
              <Button
                type="button"
                size="sm"
                shape="pill"
                variant="outline"
                onClick={() => handlers.onReconnect(shown)}
              >
                <RefreshCw />
                {t('settings.connectors.status.reconnect')}
              </Button>
            </div>
          </Alert>
        )}
      </div>
      {shown && (
        <AccountContent
          key={shown.id}
          connector={service}
          detail={shown}
          onSyncMore={handlers.onSyncMore}
          onRefreshTools={handlers.onRefreshTools}
          onToggleTool={handlers.onToggleTool}
          onSyncNow={handlers.onSyncNow}
          onAddTools={handlers.onAddTools}
          onSwitchWrites={handlers.onSwitchWrites}
        />
      )}
    </section>
  );
}

/**
 * Everything about one connector: its accounts, the sources each syncs and
 * the tools each provides, with their permissions. Opens from a Connectors
 * page card; `/settings/connectors?connector=<key>&connection=<id>` opens it
 * on one account.
 */
export default function ConnectionDrawer({
  connector,
  parts = [],
  initialConnectionId,
  onClose,
  onConnect,
}: {
  connector: ConnectorDefinition | null;
  /** The same service offered another way, shown here (Jira & Confluence). */
  parts?: ConnectorDefinition[];
  /** The account to show first, e.g. the one behind the tool it opened from. */
  initialConnectionId?: string;
  onClose: () => void;
  onConnect: (connector: ConnectorDefinition, options?: LaunchOptions) => void;
}) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const connections = useSelector(selectConnections);
  const listLoaded = useSelector(selectConnectorsLoaded);
  const listFailed = useSelector(selectConnectorsFailed);
  // The details belong to the connector they were loaded for, so opening
  // another one never shows the last one's accounts (or none) meanwhile.
  const [loaded, setLoaded] = useState<{
    key: string;
    details: ConnectionDetail[];
  } | null>(null);
  const [failedKey, setFailedKey] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [toDisconnect, setToDisconnect] = useState<ConnectionDetail | null>(
    null,
  );
  const [toRemove, setToRemove] = useState<ConnectionDetail | null>(null);
  const [toRename, setToRename] = useState<ConnectionDetail | null>(null);
  // The account shown per service (the connector and each of its parts).
  const [picked, setPicked] = useState<Record<string, string>>({});
  useEffect(() => {
    setPicked({});
  }, [connector?.key, initialConnectionId]);
  const pickedIn = (key: string, accounts: ConnectionDetail[]) =>
    picked[key] ??
    (accounts.some((account) => account.id === initialConnectionId)
      ? initialConnectionId
      : undefined);

  const keys = [connector?.key, ...parts.map((part) => part.key)];
  const accountIds = connections
    .filter((connection) => keys.includes(connection.connector_key))
    .map((connection) => `${connection.id}:${connection.status}`)
    .join(',');

  useEffect(() => {
    // Until the connections list is in, "no account" would be a guess.
    if (!connector || !listLoaded) return;
    const key = connector.key;
    const ids = accountIds
      ? accountIds.split(',').map((entry) => entry.split(':')[0])
      : [];
    let cancelled = false;
    setFailedKey(null);
    Promise.all(ids.map((id) => connectorsService.getConnection(id, token)))
      .then((responses) => {
        if (cancelled) return;
        if (responses.some((response) => !response?.success)) {
          setFailedKey(key);
          return;
        }
        setLoaded({
          key,
          details: responses.map((response) => response.connection),
        });
      })
      .catch(() => !cancelled && setFailedKey(key));
    return () => {
      cancelled = true;
    };
  }, [connector, listLoaded, accountIds, token, reloadKey]);

  const refresh = useCallback(() => {
    dispatch(loadConnectors({ token }));
    setReloadKey((key) => key + 1);
  }, [dispatch, token]);

  const serviceOf = (detail: ConnectionDetail) =>
    parts.find((part) => part.key === detail.connector_key) ?? connector;

  const reconnect = (detail: ConnectionDetail) => {
    if (!connector) return;
    // A part's account (Jira & Confluence under Confluence) reconnects
    // through its own connector.
    const target = serviceOf(detail) ?? connector;
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

  const serviceName = (detail: ConnectionDetail) => {
    const service = serviceOf(detail);
    return service ? connectorName(t, service) : detail.name;
  };

  const addTools = async (detail: ConnectionDetail) => {
    const data = await connectorsService
      .setup(detail.id, { create_tools: true }, token)
      .catch(() => null);
    // Reloaded either way: a rejected sign-in flags the account to reconnect.
    refresh();
    if (data?.success) return null;
    return data?.code === 'tools_unavailable'
      ? t('settings.connectors.detail.toolsUnavailable', {
          name: serviceName(detail),
          interpolation: { escapeValue: false },
        })
      : t('settings.connectors.detail.addToolsFailed');
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
                    name: serviceName(detail),
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
  const ready = loaded?.key === connector.key;
  const failed = failedKey === connector.key || (!listLoaded && listFailed);
  const details = ready ? loaded.details : [];
  // What the service does, all its parts included, once in the header.
  const capabilities = Array.from(
    new Set<Capability>(
      [connector, ...parts].flatMap((service) => service.capabilities),
    ),
  );

  const handlers: AccountHandlers = {
    onReconnect: reconnect,
    onDisconnect: setToDisconnect,
    onRemove: setToRemove,
    onRename: setToRename,
    onSyncMore: (detail) => {
      const service = serviceOf(detail);
      if (service)
        onConnect(service, { mode: 'sync', connectionId: detail.id });
    },
    onRefreshTools: refreshTools,
    onToggleTool: toggleTool,
    onSyncNow: syncNow,
    onAddTools: addTools,
    onSwitchWrites: switchWrites,
  };

  const sections = [connector, ...parts]
    .map((service) => ({
      service,
      accounts: details.filter(
        (detail) => detail.connector_key === service.key,
      ),
    }))
    // A service that still needs admin setup and has no account says so in
    // its setup notice; an empty "Accounts" under it would be a dead end.
    .filter(
      ({ service, accounts }) =>
        !(service === connector && service.needs_setup && !accounts.length),
    )
    .map(({ service, accounts }) => (
      <ServiceSection
        key={service.key}
        service={service}
        // With parts, each service is headed by its own name.
        heading={
          parts.length > 0
            ? connectorName(t, service)
            : t('settings.connectors.detail.accounts')
        }
        description={
          service === connector ? undefined : connectorDescription(t, service)
        }
        accounts={accounts}
        picked={pickedIn(service.key, accounts)}
        onPick={(id) => setPicked((state) => ({ ...state, [service.key]: id }))}
        onConnect={() => onConnect(service)}
        {...handlers}
      />
    ));

  return (
    <>
      <SidePanel open onOpenChange={(open) => !open && onClose()}>
        <PanelHeader
          title={name}
          description={connectorDescription(t, connector)}
          leading={
            <Avatar size="xl" shape="square" variant="icon">
              <ConnectorIcon icon={connector.icon} className="size-7" />
            </Avatar>
          }
        >
          {capabilities.length > 0 && (
            <CapabilityBadges capabilities={capabilities} />
          )}
        </PanelHeader>
        <PanelBody>
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

          {failed ? (
            <EmptyState
              tone="destructive"
              size="sm"
              illustration="none"
              title={t('settings.connectors.detail.failed')}
              onRetry={refresh}
            />
          ) : !ready ? (
            <LoadingState fill="block" />
          ) : (
            sections.flatMap((section, index) =>
              index === 0
                ? [section]
                : [<Separator key={`rule-${section.key}`} />, section],
            )
          )}
        </PanelBody>
      </SidePanel>
      {toDisconnect && (
        <DisconnectConnectionModal
          detail={toDisconnect}
          name={confirmName(toDisconnect, serviceName(toDisconnect))}
          onClose={() => setToDisconnect(null)}
          onDisconnected={() => {
            setToDisconnect(null);
            refresh();
          }}
        />
      )}
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
          name={confirmName(toRemove, serviceName(toRemove))}
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
