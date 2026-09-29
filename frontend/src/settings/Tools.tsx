import { Eye, Pencil, RefreshCw, Trash2, Users } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import devicesService from '../api/services/devicesService';
import userService from '../api/services/userService';
import PageToolbar from '../components/PageToolbar';
import SearchInput from '../components/SearchInput';
import RoleBadge from '../components/RoleBadge';
import SkeletonLoader from '../components/SkeletonLoader';
import ToolIcon from '../components/ToolIcon';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardDescription, CardTitle } from '../components/ui/card';
import { Label } from '../components/ui/label';
import { Switch } from '../components/ui/switch';
import { ActionMenu, type MenuOption } from '../components/ui/dropdown-menu';
import { EmptyState } from '../components/ui/empty-state';
import { useLoaderState } from '../hooks';
import AddToolModal from '../modals/AddToolModal';
import ConfirmationModal from '../modals/ConfirmationModal';
import MCPServerModal from '../modals/MCPServerModal';
import { ActiveState } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import ShareToTeamModal from '../teams/ShareToTeamModal';
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
  const dispatch = useDispatch();

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
  const [mcpStatuses, setMcpStatuses] = React.useState<{
    [toolId: string]: string;
  }>({});

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
    const options: MenuOption[] = [
      canEdit
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
    // A shared OAuth server's sign-in is the owner's to redo.
    if (
      tool.name === 'mcp_tool' &&
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

  const handleSettingsClick = (tool: UserToolType) => {
    setSelectedTool(tool);
  };

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
  }, []);
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
                    {filtered.map((tool, index) => (
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
                            {tool.name === 'mcp_tool' &&
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
                                      ? t('settings.tools.authStatus.needsAuth')
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
                              title={tool.customName || tool.displayName}
                              className="truncate capitalize"
                            >
                              {tool.customName || tool.displayName}
                            </CardTitle>
                            <CardDescription
                              size="xs"
                              className="mt-1 line-clamp-4 max-h-24 overflow-hidden break-words"
                              title={tool.description}
                            >
                              {tool.description}
                            </CardDescription>
                          </div>
                        </div>
                        {/* A shared tool without use_in_own can't be in the
                            caller's chats at all, so there is no switch. */}
                        {canAddToolToOwn(tool) && (
                          <div className="absolute right-4 bottom-4 flex items-center gap-2">
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
                              aria-label={t('settings.tools.useInMyChatsAria', {
                                interpolation: { escapeValue: false },
                                toolName: tool.customName || tool.displayName,
                              })}
                            />
                          </div>
                        )}
                      </Card>
                    ))}
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
          {toolToShare && (
            <ShareToTeamModal
              resourceType="tool"
              resourceId={toolToShare.id}
              resourceName={toolToShare.customName || toolToShare.displayName}
              onClose={() => setToolToShare(null)}
            />
          )}
        </div>
      )}
    </div>
  );
}
