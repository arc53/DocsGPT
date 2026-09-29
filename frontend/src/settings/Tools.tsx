import { Eye, Pencil, Plug, RefreshCw, Trash2, Users } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';

import devicesService from '../api/services/devicesService';
import userService from '../api/services/userService';
import PageToolbar from '../components/PageToolbar';
import SearchInput from '../components/SearchInput';
import RoleBadge from '../components/RoleBadge';
import SkeletonLoader from '../components/SkeletonLoader';
import ToolIcon from '../components/ToolIcon';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Card,
  CardDescription,
  CardFooter,
  CardTitle,
} from '../components/ui/card';
import { Label } from '../components/ui/label';
import { Switch } from '../components/ui/switch';
import { ActionMenu, type MenuOption } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import ConnectionDrawer from '../connectors/ConnectionDrawer';
import ConnectorIcon from '../connectors/ConnectorIcon';
import {
  connectionNeedsSignIn,
  loadConnectors,
  selectConnections,
  selectConnectorCatalog,
} from '../connectors/connectorsSlice';
import { connectorDescription } from '../connectors/i18n';
import type { Connection, ConnectorDefinition } from '../connectors/types';
import useConnectorLauncher from '../connectors/useConnectorLauncher';
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
  // The connection panel, opened here for a connected tool's service.
  const [managed, setManaged] = React.useState<{
    connector: ConnectorDefinition;
    connectionId: string;
  } | null>(null);
  const [mcpStatuses, setMcpStatuses] = React.useState<{
    [toolId: string]: string;
  }>({});

  // A connection-backed tool shares its connection's account or asks each
  // member to connect their own; the share dialog shows that choice.
  const shareCredentials = (
    tool: UserToolType,
  ): ShareCredentials | undefined => {
    const connection = tool.connection_id
      ? connections.find((c) => c.id === tool.connection_id)
      : undefined;
    if (!connection) return undefined;
    const policy = catalog.find(
      (c) => c.key === connection.connector_key,
    )?.credential_policy;
    return {
      toolId: tool.id,
      connectorName: connection.name,
      account: connection.account_label,
      mode: tool.credential_mode === 'member' ? 'member' : 'owner',
      forcedMode: policy === 'owner' || policy === 'member' ? policy : null,
      hasWrites: (tool.actions ?? []).some(
        (action) => action.access === 'write',
      ),
    };
  };

  const handleDeleteTool = (tool: UserToolType) => {
    setToolToDelete(tool);
    setDeleteModalState('ACTIVE');
  };

  const confirmDeleteTool = () => {
    if (!toolToDelete) return;
    const afterDelete = () => {
      getUserTools();
      fetchMcpStatuses();
      setDeleteModalState('INACTIVE');
      setToolToDelete(null);
    };
    // Remote-device tools front a paired device + live session token. Revoke
    // the device server-side (marks revoked, closes any session, invalidates
    // the token, and drops the user_tools row) instead of deleting only the
    // tool row, which would leave the daemon polling with a live token.
    const deviceId =
      toolToDelete.name === 'remote_device'
        ? toolToDelete.config?.device_id
        : undefined;
    if (deviceId) {
      devicesService
        .revoke(deviceId, token)
        .then(afterDelete)
        .catch((error) => console.error('Failed to revoke device:', error));
      return;
    }
    userService
      .deleteTool({ id: toolToDelete.id }, token)
      .then((response: Response) => {
        if (response.ok) return afterDelete();
        setDeleteModalState('INACTIVE');
        dispatch(
          showActionToast({
            variant: 'destructive',
            message: t('settings.tools.deleteFailed'),
          }),
        );
      })
      .catch((error: unknown) =>
        console.error('Failed to delete tool:', error),
      );
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
    // Only the caller's own connections are loaded, so a connection here
    // means the caller owns it and manages it in place.
    const connection = connectionOf(tool);
    const options: MenuOption[] = [
      connection
        ? {
            icon: Plug,
            label: t('settings.connectors.manageConnection'),
            onClick: () => handleSettingsClick(tool),
            variant: 'default',
          }
        : canEdit
          ? {
              icon: Pencil,
              label: t('settings.tools.edit'),
              onClick: () => handleSettingsClick(tool),
              variant: 'default',
            }
          : {
              icon: Eye,
              label: t('settings.tools.view'),
              onClick: () => handleSettingsClick(tool),
              variant: 'default',
            },
    ];
    // A connected server reconnects on its connector page, like any other
    // connection; only an MCP tool without one keeps the server form. A
    // teammate never sees the owner's connection, so its id alone rules
    // them out. A shared OAuth server's sign-in is the owner's to redo.
    const hasConnection = isOwner(tool) ? !!connection : !!tool.connection_id;
    if (
      tool.name === 'mcp_tool' &&
      !hasConnection &&
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

  const getUserTools = () => {
    setLoading(true);
    userService
      .getUserTools(token)
      .then((res) => {
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
        setLoading(false);
      })
      .catch((error) => {
        console.error('Error fetching tools:', error);
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

  // A connected tool is managed on its connector's page (account, on/off,
  // permissions); only other tools open the tool editor here.
  const connectionOf = (tool: UserToolType) =>
    tool.connection_id
      ? connections.find((c) => c.id === tool.connection_id)
      : undefined;
  const handleSettingsClick = (tool: UserToolType) => {
    const connection = connectionOf(tool);
    if (connection) {
      const connector = catalog.find((c) => c.key === connection.connector_key);
      if (connector) setManaged({ connector, connectionId: connection.id });
      else
        navigate(
          `/settings/connectors?connector=${encodeURIComponent(connection.connector_key)}`,
        );
      return;
    }
    setSelectedTool(tool);
  };

  const { launch, modals } = useConnectorLauncher({
    onConnected: () => getUserTools(),
  });
  // What tells two accounts of one service apart on their cards: the name
  // the owner gave it, else what identifies it.
  const accountLine = (connection: Connection) =>
    connection.account_name
      ? connection.account_name
      : connection.auth_kind === 'api_key'
        ? t('settings.connectors.detail.keyEnding', {
            hint: connection.account_label,
            interpolation: { escapeValue: false },
          })
        : connection.account_label;

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
            ) : userTools.length === 0 ? (
              <EmptyState title={t('settings.tools.noToolsFound')} />
            ) : (
              (() => {
                const filtered = userTools.filter((tool) =>
                  (tool.customName || tool.displayName)
                    .toLowerCase()
                    .includes(searchTerm.toLowerCase()),
                );
                return filtered.length === 0 ? (
                  <EmptyState title={t('settings.tools.noToolsFound')} />
                ) : (
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {filtered.map((tool, index) => {
                      const connection = connectionOf(tool);
                      const connector = connection
                        ? catalog.find(
                            (c) => c.key === connection.connector_key,
                          )
                        : undefined;
                      // A catalog service reads as the catalog describes it;
                      // a custom server keeps the description it came with.
                      // The account is on the card's own line, so the title
                      // drops the " · account" the server adds to tell
                      // accounts apart in pickers.
                      const fullName = tool.customName || tool.displayName;
                      const title =
                        connection &&
                        fullName.startsWith(`${connection.name} · `)
                          ? connection.name
                          : fullName;
                      const description =
                        connector && connector.publisher !== 'custom'
                          ? connectorDescription(t, connector)
                          : tool.description;
                      return (
                        <Card
                          key={index}
                          variant="filled"
                          padding="lg"
                          className="relative h-52 justify-between overflow-hidden"
                        >
                          {!tool.default && (
                            <ActionMenu
                              options={getMenuOptions(tool)}
                              triggerLabel={t('settings.tools.settingsIconAlt')}
                              className="absolute top-3 right-3 z-10"
                            />
                          )}
                          <div className="w-full">
                            <div className="flex w-full items-center gap-2 px-1">
                              <ToolIcon
                                name={tool.name}
                                title={t('settings.tools.toolIconTitle', {
                                  interpolation: { escapeValue: false },
                                  name: tool.displayName,
                                })}
                                className="size-6"
                              />
                              {tool.default && (
                                <Badge variant="neutral">
                                  {t('settings.tools.builtIn')}
                                </Badge>
                              )}
                              {connectionNeedsSignIn(connection) && (
                                <Badge variant="warning">
                                  {t('settings.connectors.health.signInAgain')}
                                </Badge>
                              )}
                              {tool.name === 'mcp_tool' &&
                                !connection &&
                                mcpStatuses[tool.id] && (
                                  <Badge
                                    variant={
                                      mcpStatuses[tool.id] === 'connected'
                                        ? 'success'
                                        : mcpStatuses[tool.id] === 'needs_auth'
                                          ? 'warning'
                                          : 'neutral'
                                    }
                                  >
                                    {mcpStatuses[tool.id] === 'connected'
                                      ? t('settings.tools.authStatus.connected')
                                      : mcpStatuses[tool.id] === 'needs_auth'
                                        ? t(
                                            'settings.tools.authStatus.needsAuth',
                                          )
                                        : t(
                                            'settings.tools.authStatus.configured',
                                          )}
                                  </Badge>
                                )}
                              <RoleBadge item={tool} />
                            </div>
                            <div className="mt-[9px] px-1">
                              <CardTitle
                                as="h2"
                                title={title}
                                className="truncate capitalize"
                              >
                                {title}
                              </CardTitle>
                              <CardDescription
                                size="xs"
                                className="mt-1 line-clamp-4 max-h-24 overflow-hidden break-words"
                                title={description}
                              >
                                {description}
                              </CardDescription>
                            </div>
                          </div>
                          {/* Which account this is (each account of a
                              service is its own tool) and the caller's own
                              "In my chats" switch share the meta row. A
                              shared tool without use_in_own can't be in the
                              caller's chats at all, so it has no switch. */}
                          {(connection || canAddToolToOwn(tool)) && (
                            <CardFooter>
                              {connection && (
                                <span className="flex min-w-0 items-center gap-2">
                                  <ConnectorIcon
                                    icon={connection.icon}
                                    className="size-3.5 shrink-0"
                                  />
                                  <span
                                    className="truncate"
                                    title={accountLine(connection)}
                                  >
                                    {accountLine(connection)}
                                  </span>
                                </span>
                              )}
                              {canAddToolToOwn(tool) && (
                                <span className="ml-auto flex shrink-0 items-center gap-2">
                                  <Label
                                    htmlFor={`toolToggle-${index}`}
                                    className="text-muted-foreground text-xs font-normal"
                                  >
                                    {t('settings.tools.inMyChats')}
                                  </Label>
                                  <Switch
                                    checked={toolInChat(tool)}
                                    onCheckedChange={(checked) =>
                                      updateToolStatus(tool.id, checked)
                                    }
                                    id={`toolToggle-${index}`}
                                    aria-label={t(
                                      'settings.tools.useInMyChatsAria',
                                      {
                                        interpolation: { escapeValue: false },
                                        toolName:
                                          tool.customName || tool.displayName,
                                      },
                                    )}
                                  />
                                </span>
                              )}
                            </CardFooter>
                          )}
                        </Card>
                      );
                    })}
                  </div>
                );
              })()
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
            modalState={deleteModalState}
            setModalState={setDeleteModalState}
            handleSubmit={confirmDeleteTool}
            submitLabel={t('settings.tools.delete')}
            variant="destructive"
          />
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
          <ConnectionDrawer
            connector={managed?.connector ?? null}
            initialConnectionId={managed?.connectionId}
            onClose={() => {
              setManaged(null);
              getUserTools();
              dispatch(loadConnectors({ token }));
            }}
            onConnect={(connector, options) => {
              setManaged(null);
              launch(connector, options);
            }}
          />
          {modals}
          {toolToShare && (
            <ShareToTeamModal
              resourceType="tool"
              resourceId={toolToShare.id}
              resourceName={toolToShare.customName || toolToShare.displayName}
              // Whose account shares use is the owner's choice alone.
              credentials={
                isOwner(toolToShare) ? shareCredentials(toolToShare) : undefined
              }
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
