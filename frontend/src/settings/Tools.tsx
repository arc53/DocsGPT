import { Eye, Pencil, Plug, RefreshCw, Trash2, Users } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';

import devicesService from '../api/services/devicesService';
import userService from '../api/services/userService';
import PageToolbar from '../components/PageToolbar';
import { Pagination, pageRangeParams } from '../components/ui/pagination';
import { SHORT_LIST_PAGE_SIZE, useClientPage } from '../hooks/usePageState';
import SearchInput from '../components/SearchInput';
import RoleBadge from '../components/RoleBadge';
import SkeletonLoader from '../components/SkeletonLoader';
import ToolIcon from '../components/ToolIcon';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { ActionMenu, type MenuOption } from '../components/ui/dropdown-menu';
import { SectionHeader } from '../components/ui/section-header';
import { Switch } from '../components/ui/switch';
import { EmptyState } from '../components/ui/empty-state';
import ConnectorIcon from '../connectors/ConnectorIcon';
import ConnectorTile from '../connectors/ConnectorTile';
import {
  connectionNeedsSignIn,
  loadConnectors,
  selectConnections,
  selectConnectorCatalog,
} from '../connectors/connectorsSlice';
import { accountLine, connectorDescription } from '../connectors/i18n';
import { useSignInAgain } from '../connectors/SignInAgainNotice';
import { toolServiceOf } from '../connectors/toolService';
import { useLoaderState } from '../hooks';
import type { AvailableToolType } from '../modals/types';
import AddToolModal from '../modals/AddToolModal';
import ConfirmationModal from '../modals/ConfirmationModal';
import MCPServerModal from '../modals/MCPServerModal';
import { ActiveState } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import ShareToTeamModal, {
  type ShareCredentials,
} from '../teams/ShareToTeamModal';
import { can, isOwner, roleOf } from '../utils/accessUtils';
import {
  canAddToolToOwn,
  isSharedOAuthMcp,
  toolInChat,
} from '../utils/toolUtils';
import RemoteDeviceConfig from './RemoteDeviceConfig';
import ToolConfig from './ToolConfig';
import { groupTools, type ToolGroup } from './toolGroups';
import { APIToolType, UserToolType } from './types';

export default function Tools() {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const dispatch = useDispatch<AppDispatch>();
  const connections = useSelector(selectConnections);
  const catalog = useSelector(selectConnectorCatalog);
  const location = useLocation();
  const navigate = useNavigate();

  const [searchTerm, setSearchTerm] = React.useState('');
  const [addToolModalState, setAddToolModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [userTools, setUserTools] = React.useState<UserToolType[]>([]);
  const [selectedTool, setSelectedTool] = React.useState<
    UserToolType | APIToolType | null
  >(null);
  const [loading, setLoading] = useLoaderState(false);
  // The first load failed: an error with Retry, not the empty state.
  const [loadFailed, setLoadFailed] = React.useState(false);
  const [deleteModalState, setDeleteModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [toolToDelete, setToolToDelete] = React.useState<UserToolType | null>(
    null,
  );
  const [reconnectModalState, setReconnectModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [reconnectTool, setReconnectTool] = React.useState<any>(null);
  const [toolToShare, setToolToShare] = React.useState<UserToolType | null>(
    null,
  );
  const [mcpStatuses, setMcpStatuses] = React.useState<{
    [toolId: string]: string;
  }>({});

  // A connection-backed tool shares its connection's account or asks each
  // member to connect their own; the share dialog shows that choice. Whose
  // account it is stays the owner's choice: an editor the owner lets share
  // sees it locked, and still confirms before sharing a tool that can act.
  const shareCredentials = (
    tool: UserToolType,
  ): ShareCredentials | undefined => {
    if (!tool.connection_id) return undefined;
    const owner = isOwner(tool);
    const service = toolServiceOf(tool, connections, catalog);
    // The owner's own connection names the account; until it loads there
    // is nothing to show them.
    if (!service || (owner && !service.connection)) return undefined;
    const policy = service.connector?.credential_policy;
    return {
      toolId: tool.id,
      connectorName: service.name,
      account: owner ? (service.connection?.account_label ?? '') : '',
      mode: tool.credential_mode === 'member' ? 'member' : 'owner',
      forcedMode: policy === 'owner' || policy === 'member' ? policy : null,
      hasWrites: (tool.actions ?? []).some(
        (action) => action.access === 'write',
      ),
      readOnly: !owner,
    };
  };

  const handleDeleteTool = (tool: UserToolType) => {
    setToolToDelete(tool);
    setDeleteModalState('ACTIVE');
  };

  // Returned to ConfirmationModal: it stays pending while the delete runs,
  // closes on success and keeps a failure in the dialog.
  const confirmDeleteTool = async () => {
    if (!toolToDelete) return;
    // Remote-device tools front a paired device + live session token. Revoke
    // the device server-side (marks revoked, closes any session, invalidates
    // the token, and drops the user_tools row) instead of deleting only the
    // tool row, which would leave the daemon polling with a live token.
    const deviceId =
      toolToDelete.name === 'remote_device'
        ? toolToDelete.config?.device_id
        : undefined;
    if (deviceId) {
      const result = await devicesService.revoke(deviceId, token);
      if (result?.success === false) {
        throw new Error('Failed to revoke device');
      }
    } else {
      const response: Response = await userService.deleteTool(
        { id: toolToDelete.id },
        token,
      );
      if (!response.ok) throw new Error('Failed to delete tool');
    }
    getUserTools();
    fetchMcpStatuses();
    setToolToDelete(null);
  };

  const handleReconnect = (tool: UserToolType) => {
    const config = tool.config as Record<string, any>;
    const oauthScopes = Array.isArray(config.oauth_scopes)
      ? config.oauth_scopes.join(', ')
      : config.oauth_scopes || '';
    setReconnectTool({
      id: tool.id,
      displayName: tool.customName || tool.displayName,
      server_url: config.server_url || '',
      auth_type: config.auth_type || 'none',
      timeout: config.timeout || 30,
      oauth_scopes: oauthScopes,
      has_encrypted_credentials: !!config.has_encrypted_credentials,
      access: roleOf(tool),
      owner_label: tool.owner_label ?? null,
    });
    setReconnectModalState('ACTIVE');
  };

  const getMenuOptions = (tool: UserToolType): MenuOption[] => {
    const canEdit = can(tool, 'edit') || can(tool, 'edit_credentials');
    const options: MenuOption[] = [];
    const connection = connectionOf(tool);
    // The owner's connected tool is managed with its connection: open the
    // Connectors drawer on that account.
    const connectorKey =
      connection?.connector_key ??
      toolServiceOf(tool, connections, catalog)?.connector?.key;
    if (tool.connection_id && isOwner(tool) && connectorKey) {
      const params = new URLSearchParams({
        connector: connectorKey,
        connection: tool.connection_id,
      });
      options.push({
        icon: Plug,
        label: t('settings.tools.manageInConnectors'),
        onClick: () => navigate(`/settings/connectors?${params.toString()}`),
        variant: 'default',
      });
    }
    // The caller's own connection that needs reconnecting (the badge says
    // so) is reconnected from here, in place where it can be.
    if (connection && connectionNeedsSignIn(connection))
      options.push({
        icon: RefreshCw,
        label: t('settings.connectors.status.reconnect'),
        onClick: () =>
          reconnect(connection, tool.name === 'mcp_tool' ? tool.id : undefined),
        variant: 'default',
      });
    // The owner's connected tool (its connection is theirs) is managed on
    // the Connectors page, so it has no editor here; a teammate's opens the
    // tool editor like any other shared tool.
    if (!(tool.connection_id && isOwner(tool)))
      options.push(
        canEdit
          ? {
              icon: Pencil,
              label: t('settings.tools.edit'),
              onClick: () => setSelectedTool(tool),
              variant: 'default',
            }
          : {
              icon: Eye,
              label: t('settings.tools.view'),
              onClick: () => setSelectedTool(tool),
              variant: 'default',
            },
      );
    // A connected server signs in again through its connection (Reconnect
    // above, for the caller's own); only an MCP tool without one keeps
    // the server form. The tool's own connection id decides, for everyone: a
    // teammate never sees the owner's connection, and the owner's loads
    // after the tools. A shared OAuth server's sign-in is the owner's to redo.
    if (
      tool.name === 'mcp_tool' &&
      !tool.connection_id &&
      can(tool, 'edit_credentials') &&
      !isSharedOAuthMcp(tool)
    ) {
      options.push({
        icon: RefreshCw,
        label: t('settings.tools.reconnect'),
        onClick: () => handleReconnect(tool),
        variant: 'default',
      });
    }
    if (can(tool, 'share')) {
      options.push({
        icon: Users,
        label: t('settings.tools.shareWithTeam'),
        onClick: () => setToolToShare(tool),
        variant: 'default',
      });
    }
    if (can(tool, 'delete')) {
      options.push({
        icon: Trash2,
        label: t('settings.tools.delete'),
        onClick: () => handleDeleteTool(tool),
        variant: 'destructive',
      });
    }
    return options;
  };

  const fetchMcpStatuses = React.useCallback(() => {
    userService
      .getMCPAuthStatus(token)
      .then((res) => res.json())
      .then((data) => {
        if (data.success && data.statuses) {
          setMcpStatuses(data.statuses);
        }
      })
      .catch(() => {});
  }, [token]);

  const { reconnect, modals: signInModals } = useSignInAgain({
    onConnected: () => getUserTools(),
  });

  const getUserTools = () => {
    setLoading(true);
    userService
      .getUserTools(token)
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load tools (${res.status})`);
        return res.json();
      })
      .then((data) => {
        // Pure builtins (agent-only, e.g. a future builtin without an
        // agentless path) carry no per-user state and only apply when
        // added to an agent, so hide them from the management page. Dual-
        // registered tools (``scheduler``: builtin + default) stay visible
        // here so the user can toggle the default off in agentless chats.
        const filtered = (data.tools || []).filter(
          (tool: UserToolType) => tool.default || !tool.builtin,
        );
        setUserTools(filtered);
        setLoadFailed(false);
        setLoading(false);
      })
      .catch((error) => {
        console.error('Error fetching tools:', error);
        setLoadFailed(true);
        setLoading(false);
      });
  };

  const setToolInChat = (toolId: string, value: boolean) =>
    setUserTools((prevTools) =>
      prevTools.map((tool) =>
        tool.id !== toolId
          ? tool
          : isOwner(tool)
            ? { ...tool, status: value, in_chat: value }
            : { ...tool, in_chat: value },
      ),
    );

  // The switch moves at once and flips back when the server refuses it.
  const updateToolStatus = (toolId: string, newStatus: boolean) => {
    setToolInChat(toolId, newStatus);
    const fail = () => {
      setToolInChat(toolId, !newStatus);
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t('settings.tools.statusUpdateFailed'),
        }),
      );
    };
    userService
      .updateToolStatus({ id: toolId, status: newStatus }, token)
      .then((response: Response) => {
        if (!response.ok) fail();
      })
      .catch((error: unknown) => {
        console.error('Failed to update tool status:', error);
        fail();
      });
  };

  // The caller's own connection behind a connected tool (only their own
  // connections are loaded): the card names its account.
  const connectionOf = (tool: UserToolType) =>
    tool.connection_id
      ? connections.find((c) => c.id === tool.connection_id)
      : undefined;

  const handleGoBack = () => {
    setSelectedTool(null);
    getUserTools();
    fetchMcpStatuses();
  };

  const handleToolAdded = (toolId: string) => {
    userService
      .getUserTools(token)
      .then((res) => res.json())
      .then((data) => {
        const newTool = data.tools.find(
          (tool: UserToolType) => tool.id === toolId,
        );
        if (newTool) {
          setSelectedTool(newTool);
        } else {
          console.error('Newly added tool not found');
        }
      })
      .catch((error) => console.error('Error fetching tools:', error));
  };

  const handleDevicePaired = (deviceId: string) => {
    setAddToolModalState('INACTIVE');
    userService
      .getUserTools(token)
      .then((res) => res.json())
      .then((data) => {
        const newTool = data.tools.find(
          (toolItem: UserToolType) =>
            toolItem.name === 'remote_device' &&
            toolItem.config?.device_id === deviceId,
        );
        if (newTool) setSelectedTool(newTool);
        else console.error('Paired device tool not found');
      })
      .catch((error) => console.error('Error fetching tools:', error));
  };

  React.useEffect(() => {
    getUserTools();
    fetchMcpStatuses();
    dispatch(loadConnectors({ token }));
  }, []);

  // The Connectors page opens a new OpenAPI tool here as an unsaved draft:
  // the spec import opens straight away and the tool is created on save.
  const routeState = location.state as {
    openToolId?: string;
    newApiTool?: boolean;
  } | null;
  const openToolId = routeState?.openToolId;
  const newApiTool = routeState?.newApiTool;
  React.useEffect(() => {
    if (!openToolId) return;
    handleToolAdded(openToolId);
    navigate(location.pathname, { replace: true, state: null });
  }, [openToolId]);
  React.useEffect(() => {
    if (!newApiTool) return;
    navigate(location.pathname, { replace: true, state: null });
    userService
      .getAvailableTools(token)
      .then((res) => res.json())
      .then((data) => {
        const template = (data.data as AvailableToolType[] | undefined)?.find(
          (candidate) => candidate.name === 'api_tool',
        );
        if (!template) return;
        setSelectedTool({
          id: '',
          name: template.name,
          displayName: template.displayName,
          customName: '',
          description: template.description,
          config: {},
          actions: template.actions,
          status: true,
        } as unknown as UserToolType);
      })
      .catch(() => undefined);
  }, [newApiTool]);

  const filteredTools = userTools.filter((tool) =>
    (tool.customName || tool.displayName)
      .toLowerCase()
      .includes(searchTerm.toLowerCase()),
  );
  // Grouped like the composer's picker. Paged in group order, so a group
  // that runs past a page carries on (under its header) on the next one.
  const orderedTools = groupTools(filteredTools, connections, catalog).flatMap(
    (group) => group.tools,
  );
  const {
    page: toolsPage,
    setPage: setToolsPage,
    pageItems: pageTools,
  } = useClientPage(orderedTools, SHORT_LIST_PAGE_SIZE, searchTerm);
  const pageGroups = groupTools(pageTools, connections, catalog);

  const groupTitle = (group: ToolGroup<UserToolType>) =>
    group.kind === 'builtIn' ? (
      t('settings.tools.groupBuiltIn')
    ) : group.kind === 'custom' ? (
      t('agents.form.toolsPopup.groupCustom')
    ) : (
      <span className="flex items-center gap-2">
        {group.service?.icon ? (
          <ConnectorIcon
            icon={group.service.icon}
            className="size-4 shrink-0"
          />
        ) : null}
        {group.service?.name}
      </span>
    );

  // The state leads the badge row: the caller's own connection needing a
  // sign-in, or a custom MCP server's sign-in. "Configured" is not a
  // health check, so it gets none.
  const stateBadge = (tool: UserToolType) => {
    const connection = connectionOf(tool);
    const mcpStatus =
      tool.name === 'mcp_tool' && !connection
        ? mcpStatuses[tool.id]
        : undefined;
    if (connectionNeedsSignIn(connection) || mcpStatus === 'needs_auth')
      return (
        <Badge variant="warning">
          {t('settings.connectors.status.reconnect')}
        </Badge>
      );
    if (mcpStatus === 'connected')
      return (
        <Badge variant="success">
          {t('settings.connectors.status.connected')}
        </Badge>
      );
    return null;
  };

  const renderTile = (tool: UserToolType) => {
    const connection = connectionOf(tool);
    const service = toolServiceOf(tool, connections, catalog);
    const connector = service?.connector;
    // A catalog service reads as the catalog describes it; a custom server
    // keeps the description it came with. The account is on the tile's own
    // line, so the title drops the " · account" the server adds to tell
    // accounts apart in pickers.
    const fullName = tool.customName || tool.displayName;
    const title =
      connection && fullName.startsWith(`${connection.name} · `)
        ? connection.name
        : fullName;
    const description =
      connector && connector.publisher !== 'custom'
        ? connectorDescription(t, connector)
        : tool.description;
    const account = connection ? accountLine(t, connection) : null;
    return (
      <ConnectorTile
        key={tool.id}
        // A connected tool shows its service's logo, as the composer does.
        icon={
          service?.icon ? (
            <ConnectorIcon icon={service.icon} className="size-6 shrink-0" />
          ) : (
            <ToolIcon
              name={tool.name}
              title={t('settings.tools.toolIconTitle', {
                interpolation: { escapeValue: false },
                name: tool.displayName,
              })}
              className="size-6 shrink-0"
            />
          )
        }
        title={title}
        titleAs="h3"
        description={description}
        menu={
          !tool.default ? (
            <ActionMenu
              options={getMenuOptions(tool)}
              triggerLabel={t('settings.tools.settingsIconAlt')}
            />
          ) : undefined
        }
        badges={
          <>
            {stateBadge(tool)}
            {/* The default copy of a built-in tool (it has no menu), told
                apart from one the user added. */}
            {tool.default && (
              <Badge variant="neutral">
                {t('settings.tools.defaultBadge')}
              </Badge>
            )}
            <RoleBadge item={tool} />
          </>
        }
        // Which account this is (each account of a service is its own
        // tool) and the caller's own "In my chats" switch, named for screen
        // readers only. A shared tool without use_in_own can't be in the
        // caller's chats at all, so it has no switch.
        footer={
          account || canAddToolToOwn(tool) ? (
            <>
              {account && (
                <span className="min-w-0 truncate" title={account}>
                  {account}
                </span>
              )}
              {canAddToolToOwn(tool) && (
                <Switch
                  className="ml-auto shrink-0"
                  checked={toolInChat(tool)}
                  onCheckedChange={(checked) =>
                    updateToolStatus(tool.id, checked)
                  }
                  aria-label={t('settings.tools.useInMyChatsAria', {
                    interpolation: { escapeValue: false },
                    toolName: tool.customName || tool.displayName,
                  })}
                />
              )}
            </>
          ) : undefined
        }
      />
    );
  };

  return (
    <div>
      {selectedTool ? (
        selectedTool.name === 'remote_device' ? (
          <RemoteDeviceConfig
            tool={selectedTool as UserToolType}
            handleGoBack={handleGoBack}
          />
        ) : (
          <ToolConfig
            tool={selectedTool}
            setTool={setSelectedTool}
            handleGoBack={handleGoBack}
          />
        )
      ) : (
        <div>
          <div className="relative flex flex-col">
            <PageToolbar
              intro={t('settings.tools.subtitle')}
              search={
                <SearchInput
                  maxLength={256}
                  label={t('settings.tools.searchPlaceholder')}
                  name="Document-search-input"
                  id="tool-search-input"
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                />
              }
              action={
                <Button
                  type="button"
                  size="field"
                  shape="pill"
                  onClick={() => {
                    setAddToolModalState('ACTIVE');
                  }}
                >
                  {t('settings.tools.addTool')}
                </Button>
              }
              divider
            />
            {loading ? (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                <SkeletonLoader component="toolCards" count={6} />
              </div>
            ) : loadFailed ? (
              <EmptyState
                tone="destructive"
                illustration="none"
                title={t('settings.tools.loadError')}
                onRetry={getUserTools}
              />
            ) : userTools.length === 0 ? (
              <EmptyState
                title={t('settings.tools.noToolsYet')}
                action={
                  <div className="flex flex-wrap justify-center gap-2">
                    <Button
                      type="button"
                      shape="pill"
                      onClick={() => setAddToolModalState('ACTIVE')}
                    >
                      {t('settings.tools.addTool')}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      shape="pill"
                      onClick={() =>
                        navigate('/settings/connectors?capability=tools')
                      }
                    >
                      {t('settings.tools.connectService')}
                    </Button>
                  </div>
                }
              />
            ) : filteredTools.length === 0 ? (
              <EmptyState
                size="xs"
                illustration="none"
                title={t('settings.tools.noToolsFound')}
              />
            ) : (
              <>
                <div className="flex flex-col gap-8">
                  {pageGroups.map((group) => (
                    <section key={group.key} className="flex flex-col gap-3">
                      <SectionHeader size="sm" title={groupTitle(group)} />
                      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                        {group.tools.map(renderTile)}
                      </div>
                    </section>
                  ))}
                </div>
                <Pagination
                  page={toolsPage}
                  pageSize={SHORT_LIST_PAGE_SIZE}
                  total={filteredTools.length}
                  onPageChange={setToolsPage}
                  rangeLabel={(range) =>
                    t('settings.tools.pageRange', pageRangeParams(range))
                  }
                />
              </>
            )}
          </div>
          <AddToolModal
            message={t('settings.tools.selectToolSetup')}
            modalState={addToolModalState}
            setModalState={setAddToolModalState}
            getUserTools={getUserTools}
            onToolAdded={handleToolAdded}
            onDevicePaired={handleDevicePaired}
          />
          <ConfirmationModal
            message={t('settings.tools.deleteWarning', {
              interpolation: { escapeValue: false },
              toolName:
                toolToDelete?.customName || toolToDelete?.displayName || '',
            })}
            description={t('settings.tools.deleteConsequence')}
            modalState={deleteModalState}
            setModalState={setDeleteModalState}
            handleSubmit={confirmDeleteTool}
            error={t('settings.tools.deleteFailed')}
            submitLabel={t('settings.tools.delete')}
            variant="destructive"
          />
          {signInModals}
          <MCPServerModal
            modalState={reconnectModalState}
            setModalState={setReconnectModalState}
            server={reconnectTool}
            onServerSaved={() => {
              setReconnectTool(null);
              getUserTools();
              fetchMcpStatuses();
            }}
          />
          {toolToShare && (
            <ShareToTeamModal
              resourceType="tool"
              resourceId={toolToShare.id}
              resourceName={toolToShare.customName || toolToShare.displayName}
              credentials={shareCredentials(toolToShare)}
              onClose={() => {
                setToolToShare(null);
                getUserTools();
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}
